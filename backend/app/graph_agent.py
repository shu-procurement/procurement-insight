"""
LangGraph Agent - 完整的智能体实现
支持：多步骤规划、并行执行、条件路由、状态持久化、人工介入
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Dict, List, Literal, Optional, Sequence, TypedDict, AsyncGenerator
import httpx
from .config import Settings
from .database import ToolRecord, get_session_factory

logger = logging.getLogger(__name__)


# ==================== LLM 调用工具 ====================

async def invoke_llm(
    messages: List[Dict[str, str]],
    settings: Settings,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
) -> tuple[str, Dict[str, Any]]:
    """
    调用 DeepSeek API 进行推理
    
    Args:
        messages: 对话消息列表
        settings: 配置对象
        temperature: 温度参数
        max_tokens: 最大 token 数
    
    Returns:
        (回复内容, 完整响应数据)
    """
    payload: Dict[str, Any] = {
        "model": "deepseek-v3.2",
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    endpoint = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:  # 增加到120秒
            response = await client.post(endpoint, json=payload, headers=headers)

        if response.status_code != 200:
            logger.error(
                "DeepSeek API error %s: %s", response.status_code, response.text
            )
            return f"API 调用失败: {response.status_code}", {}

        data = response.json()
        reply = data["choices"][0]["message"]["content"]
        return reply, data
    
    except httpx.TimeoutException as e:
        logger.error(f"LLM 调用超时（120秒）: {e}")
        return f"LLM 调用超时，请稍后重试", {}
    except Exception as e:
        logger.error(f"LLM 调用异常: {e}", exc_info=True)
        return f"LLM 调用失败: {str(e)}", {}


async def stream_llm(
    messages: List[Dict[str, str]],
    settings: Settings,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
) -> AsyncGenerator[str, None]:
    """
    流式调用 DeepSeek API
    """
    payload: Dict[str, Any] = {
        "model": "deepseek-v3.2",
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    endpoint = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    yield f"API Error: {response.status_code}"
                    return

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            content = data["choices"][0]["delta"].get("content", "")
                            if content:
                                yield content
                        except:
                            pass
    except Exception as e:
        logger.error(f"LLM Stream Error: {e}")
        yield f"Error: {str(e)}"


def parse_json_from_llm(text: str) -> Dict[str, Any]:
    """
    从 LLM 响应中提取 JSON
    支持处理 markdown 代码块包裹的 JSON
    """
    # 移除可能的 markdown 代码块标记
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    
    text = text.strip()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败: {e}, 原始文本: {text[:200]}")
        # 宽容解析：尝试截断到第一个可能完整的对象
        try:
            end_idx = max(text.rfind('}'), text.rfind(']'))
            if end_idx != -1:
                truncated = text[:end_idx+1]
                return json.loads(truncated)
        except Exception:
            pass
        # 返回默认结构
        return {
            "task_type": "信息查询",
            "steps": ["分析问题", "生成回答"],
            "required_tools": [],
            "need_knowledge_base": False
        }


def format_tools_description(tool_records: List[ToolRecord]) -> str:
    """格式化工具描述供 LLM 理解"""
    if not tool_records:
        return "无可用工具"
    
    descriptions = []
    for tool in tool_records:
        try:
            config = json.loads(tool.config or "{}")
            builtin_key = config.get("builtin_key", "")
            descriptions.append(
                f"- {tool.id}: {tool.name} ({builtin_key}) - {tool.description}"
            )
        except:
            descriptions.append(f"- {tool.id}: {tool.name} - {tool.description}")
    
    return "\n".join(descriptions)


def is_simple_query(query: str) -> bool:
    """
    判断是否为简单查询（无需 Agent 复杂推理）
    """
    if not query:
        return False

    # 1. 长度检查：太长通常不是简单指令
    if len(query) > 30:
        return False

    normalized = query.lower().strip()

    # 2. 排除复杂意图关键词
    complex_indicators = [
        "搜索", "查找", "查询", "天气", "画", "图", "笔记", "分析", "总结", "最新",
        "search", "weather", "draw", "diagram", "note", "analyze", "summary"
    ]
    if any(ind in normalized for ind in complex_indicators):
        return False

    # 3. 简单问候和基础问题（扩展：解释类问题如果不需要工具也算简单）
    simple_keywords = [
        "你好", "hello", "hi", "是谁", "名字", "再见", "goodbye",
        "谢谢", "thank", "晚安", "早安", "测试", "test",
        "帮助", "help", "功能", "介绍", "who are you",
        "早上好", "晚上好", "什么", "what is", "explain", "introduce",
        "告诉我", "tell me"
    ]

    for kw in simple_keywords:
        if kw in normalized:
            return True

    return False



