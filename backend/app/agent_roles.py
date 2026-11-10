"""
智能体角色定义
定义各个专家智能体的节点函数和能力
"""
from __future__ import annotations
import pymysql
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .config import Settings
from .database import ToolRecord
from .graph_agent import invoke_llm, parse_json_from_llm
from .rag_service import retrieve_context
from .shared_workspace import MultiAgentState, SharedWorkspace
from .tool_service import execute_tool

logger = logging.getLogger(__name__)


def get_agent_prompt(
        default_prompt: str,
        **kwargs
) -> str:
    """
    获取智能体的prompt并替换占位符

    Args:
        default_prompt: 硬编码的默认prompt模板
        **kwargs: 用于替换prompt中的占位符，如 user_query, task_description 等

    Returns:
        处理后的prompt字符串
    """
    prompt = default_prompt

    # 替换占位符
    try:
        import re

        # 1. 先替换双花括号为单花括号（兼容性处理）
        prompt = prompt.replace("{{", "{").replace("}}", "}")

        # 2. 替换常见的占位符
        prompt = prompt.replace("{user_query}", str(kwargs.get("user_query", "")))
        prompt = prompt.replace("{task_description}", str(kwargs.get("task_description", "")))
        prompt = prompt.replace("{analysis_context}", str(kwargs.get("analysis_context", "")))
        prompt = prompt.replace("{full_context}", str(kwargs.get("full_context", "")))
        prompt = prompt.replace("{final_answer}", str(kwargs.get("final_answer", "")))

        # 3. 替换其他自定义占位符
        for key, value in kwargs.items():
            placeholder = f"{{{key}}}"
            if placeholder in prompt:
                prompt = prompt.replace(placeholder, str(value))

        # 4. 检查未替换的占位符（警告）
        unmatched = re.findall(r'\{(\w+)\}', prompt)
        if unmatched:
            # 过滤掉已经替换的占位符
            replaced_placeholders = ["user_query", "task_description", "analysis_context",
                                     "full_context", "final_answer"] + list(kwargs.keys())
            truly_unmatched = [p for p in unmatched if p not in replaced_placeholders]

            if truly_unmatched:
                logger.warning(f"⚠️ [Prompt处理] 未替换的占位符: {truly_unmatched}")

    except Exception as e:
        logger.warning(f"⚠️ [Prompt处理] 替换占位符时出错: {e}")

    return prompt


# ==================== 检索专家（Retrieval Specialist） ====================

async def retrieval_specialist_node(
    state: MultiAgentState,
    settings: Settings,
    session: Session,
    tool_records: List[ToolRecord],
) -> Dict[str, Any]:
    """
    检索专家智能体
    
    职责：
    - 知识库检索（RAG）
    - 网络搜索
    - 文档查找
    
    能力：
    - 向量检索
    - 关键词搜索
    - 网页搜索工具
    """
    logger.info("🔍 [检索专家] 开始执行检索任务...")
    
    workspace = SharedWorkspace(state)
    agent_id = "retrieval_specialist"
    
    # 注册智能体
    workspace.register_agent(agent_id)
    workspace.update_agent_status(agent_id, "running")
    
    user_query = state.get("user_query", "")
    use_knowledge_base = state.get("use_knowledge_base", False)
    selected_keywords = state.get("selected_keywords", [])

    retrieval_results = {}
    thoughts = []
    observations = []
    
    try:
        # 1. 知识库检索（智能版：带置信度评估）
        if use_knowledge_base:
            try:
                logger.info("📚 执行知识库检索（带置信度评估）...")
                
                # 使用带置信度的检索函数
                from .rag_service import retrieve_context_with_confidence
                
                contexts, confidence = retrieve_context_with_confidence(
                    query=user_query,
                    settings=settings,
                    top_k=5,
                    confidence_threshold=0.3,  # 置信度阈值
                    selected_keywords=selected_keywords
                )
                
                # 根据置信度判断是否使用检索结果
                if contexts and confidence == "high":
                    # 高置信度：使用检索结果
                    retrieval_results["knowledge_base"] = [
                        {
                            "document_id": ctx.document_id,
                            "original_name": ctx.original_name,
                            "content": ctx.content[:500],
                        }
                        for ctx in contexts
                    ]
                    thoughts.append(f"✅ 从知识库检索到 {len(contexts)} 个高相关性片段")
                    observations.append(
                        f"知识库检索完成：找到 {len(contexts)} 个相关文档（高置信度）"
                    )
                    logger.info(f"✅ 知识库检索成功，置信度：{confidence}")
                    
                elif contexts and confidence == "low":
                    # 低置信度：不使用检索结果，记录日志
                    thoughts.append(f"⚠️ 知识库检索置信度较低，内容可能不相关")
                    observations.append(
                        f"知识库检索完成，但相关性较低（将优先使用其他信息源）"
                    )
                    logger.warning(f"⚠️ 知识库检索置信度低，跳过使用检索结果")
                    # 不添加到 retrieval_results，让后续流程使用工具调用
                    
                else:
                    # 未找到内容
                    thoughts.append("知识库检索未找到相关内容")
                    observations.append("知识库为空或未找到相关内容")
                    logger.info("知识库检索为空")
            
            except Exception as e:
                logger.error(f"知识库检索失败: {e}")
                thoughts.append(f"知识库检索失败: {str(e)}")
        
        # 2. 智能工具调用（通用方案）- 让LLM自己判断需要什么工具
        has_kb_results = "knowledge_base" in retrieval_results and len(retrieval_results["knowledge_base"]) > 0
        
        # 构建工具描述
        from .tool_service import BUILTIN_TOOLS
        
        tool_descriptions = []
        available_tools_map = {}  # tool_key -> tool_record
        
        for tool in tool_records:
            try:
                import json
                config = json.loads(tool.config or "{}")
                builtin_key = config.get("builtin_key")
                
                if builtin_key and builtin_key in BUILTIN_TOOLS:
                    tool_def = BUILTIN_TOOLS[builtin_key]
                    tool_descriptions.append(
                        f"- **{tool_def.name}** ({builtin_key}): {tool_def.description}"
                    )
                    available_tools_map[builtin_key] = tool
            except:
                continue
        
        if available_tools_map:
            # 构建详细的工具schema信息
            tool_schemas = []
            for tool_key, tool in available_tools_map.items():
                config = json.loads(tool.config or "{}")
                builtin_key = config.get("builtin_key")
                if builtin_key and builtin_key in BUILTIN_TOOLS:
                    tool_def = BUILTIN_TOOLS[builtin_key]
                    tool_schemas.append({
                        "key": builtin_key,
                        "name": tool_def.name,
                        "description": tool_def.description,
                        "schema": tool_def.input_schema
                    })
            
            # 使用LLM智能判断需要调用哪些工具
            tool_selection_prompt = f"""你是一个工具调用专家。请分析用户问题，判断是否需要调用工具来完成任务。

【用户问题】：{user_query}

【知识库检索状态】：{"✅ 已找到 " + str(len(retrieval_results.get("knowledge_base", []))) + " 个相关内容" if has_kb_results else "❌ 知识库无相关内容或未启用"}

【可用工具及其参数】：
{json.dumps(tool_schemas, ensure_ascii=False, indent=2)}

【判断规则】：
1. 检索专家的核心职责是**收集信息**，不负责最终内容输出
2. ✅ 应该调用：web_search（网页搜索）、search_knowledge（知识库检索）等信息获取工具
3. ❌ 不要调用：write_note（写入笔记）、draw_diagram（绘制图表）等内容输出工具
4. 内容输出工具应该在分析和总结完成后由后续专家调用
5. 如果用户问题需要实时数据（天气、新闻、最新信息等），应该调用web_search

【参数说明】：
- 对于web_search工具：提供清晰的搜索查询，num_results通常设为5-10
- 对于search_knowledge工具：提供准确的查询关键词，top_k设为3-5
- 对于其他信息获取工具：提供完整的必需参数

请以JSON格式输出需要调用的工具（只返回JSON，不要其他解释）：
{{
  "need_tools": true/false,
  "tools_to_call": [
    {{
      "tool_key": "工具的key",
      "reason": "调用原因",
      "arguments": {{完整的参数对象}}
    }}
  ],
  "reasoning": "判断理由"
}}
"""
            
            try:
                logger.info("🤖 使用LLM智能判断需要调用的工具...")
                
                tool_decision, _ = await invoke_llm(
                    messages=[{"role": "user", "content": tool_selection_prompt}],
                    settings=settings,
                    temperature=0.1,  # 降低温度提高确定性
                    max_tokens=1500,  # 优化：工具选择不需要太多tokens
                )
                
                decision_data = parse_json_from_llm(tool_decision)
                need_tools = decision_data.get("need_tools", False)
                tools_to_call = decision_data.get("tools_to_call", [])
                reasoning = decision_data.get("reasoning", "")
                
                logger.info(f"🧠 LLM判断：need_tools={need_tools}, 理由={reasoning}")
                
                if need_tools and tools_to_call:
                    thoughts.append(f"LLM决策：需要调用 {len(tools_to_call)} 个工具")
                    
                    # 执行LLM建议的工具调用
                    for tool_call in tools_to_call:
                        tool_key = tool_call.get("tool_key")
                        tool_reason = tool_call.get("reason", "")
                        tool_args = tool_call.get("arguments", {})
                        
                        if tool_key in available_tools_map:
                            try:
                                tool_record = available_tools_map[tool_key]
                                logger.info(f"🔧 执行工具：{tool_key}，原因：{tool_reason}")
                                
                                # 对于需要生成内容的工具，先用LLM生成内容
                                if tool_key == "write_note":
                                    # 确保有filename
                                    if not tool_args.get("filename"):
                                        tool_args["filename"] = f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                                    
                                    # 如果内容为空或太短，则生成内容
                                    if not tool_args.get("content") or len(str(tool_args.get("content", ""))) < 100:
                                        logger.info(f"📝 为write_note工具生成内容...")
                                        kb_context = ""
                                        if retrieval_results.get("knowledge_base"):
                                            kb_context = "\n\n".join([f"【文档片段 {i+1}】\n{ctx.content}" 
                                                                      for i, ctx in enumerate(retrieval_results.get("knowledge_base", [])[:5])])
                                        
                                        # 收集所有可用的上下文信息（包括其他工具的结果）
                                        tool_results_context = ""
                                        if retrieval_results:
                                            for tool_name, tool_data in retrieval_results.items():
                                                if tool_name != "knowledge_base" and isinstance(tool_data, dict):
                                                    result_str = tool_data.get("result", "")
                                                    if result_str:
                                                        tool_results_context += f"\n\n【{tool_name}工具结果】：\n{result_str[:2000]}"  # 限制长度
                                        
                                        content_prompt = f"""请根据以下信息生成完整的笔记内容：

【用户需求】：{user_query}

【知识库内容】：
{kb_context if kb_context else "（无相关知识库内容）"}
{tool_results_context}

【任务】：根据用户的具体需求，生成一份详细的技术总结文档（Markdown格式）。
- 如果用户要求分析某个主题，请提供全面的分析
- 如果用户要求总结前沿内容，请重点关注最新进展和未来方向
- 如果用户要求识别创新点，请明确指出突破性的技术点
- 文档应结构清晰、内容充实、逻辑连贯

请直接输出完整的Markdown文档内容，不要有任何前缀说明。"""
                                        
                                        content, _ = await invoke_llm(
                                            messages=[{"role": "user", "content": content_prompt}],
                                            settings=settings,
                                            temperature=0.6,  # 优化：降低温度
                                            max_tokens=2000,  # 优化：减少token限制
                                        )
                                        tool_args["content"] = content.strip()
                                        logger.info(f"✅ 已生成笔记内容，长度：{len(content)} 字符")
                                
                                elif tool_key == "draw_diagram":
                                    # 确保有filename
                                    if not tool_args.get("filename"):
                                        tool_args["filename"] = f"diagram_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                                    
                                    # 如果diagram_code为空或太短，则生成代码
                                    if not tool_args.get("diagram_code") or len(str(tool_args.get("diagram_code", ""))) < 50:
                                        logger.info(f"🎨 为draw_diagram工具生成图表代码...")
                                        kb_context = ""
                                        if retrieval_results.get("knowledge_base"):
                                            kb_context = "\n\n".join([f"【文档片段 {i+1}】\n{ctx.content}" 
                                                                      for i, ctx in enumerate(retrieval_results.get("knowledge_base", [])[:5])])
                                        
                                        # 收集所有可用的上下文信息（包括其他工具的结果）
                                        tool_results_context = ""
                                        if retrieval_results:
                                            for tool_name, tool_data in retrieval_results.items():
                                                if tool_name != "knowledge_base" and isinstance(tool_data, dict):
                                                    result_str = tool_data.get("result", "")
                                                    if result_str:
                                                        tool_results_context += f"\n\n【{tool_name}工具结果】：\n{result_str[:1500]}"  # 限制长度
                                        
                                        diagram_prompt = f"""请根据以下信息生成Mermaid思维导图代码：

【用户需求】：{user_query}

【知识库内容】：
{kb_context if kb_context else "（无相关知识库内容）"}
{tool_results_context}

【任务】：根据用户需求和提供的信息，生成一个结构清晰的Mermaid思维导图（graph TD格式）。
- 提取核心主题和关键概念
- 构建合理的层级结构
- 突出重要的关联关系
- 确保图表易于理解

【语法要求】：
- 使用标准的 graph TD 格式
- 节点格式：A[文本内容]
- 连接格式：A --> B
- 不要使用 ::icon、:::class、classDef 等高级语法
- 不要使用 subgraph（子图）
- 保持语法简洁标准

请直接输出完整的Mermaid代码，不要有markdown代码块标记（不要```mermaid），不要有任何前缀说明。
示例格式：
graph TD
    A[主题] --> B[子概念1]
    A --> C[子概念2]
    B --> B1[细节]
"""
                                        
                                        diagram_code, _ = await invoke_llm(
                                            messages=[{"role": "user", "content": diagram_prompt}],
                                            settings=settings,
                                            temperature=0.5,  # 优化：降低温度
                                            max_tokens=1500,  # 优化：减少token限制
                                        )
                                        # 清理可能的markdown代码块标记
                                        diagram_code = diagram_code.strip()
                                        if diagram_code.startswith("```"):
                                            diagram_code = diagram_code.split("```", 2)[1]
                                            if diagram_code.startswith("mermaid"):
                                                diagram_code = diagram_code[7:]
                                            diagram_code = diagram_code.strip()
                                        if diagram_code.endswith("```"):
                                            diagram_code = diagram_code[:-3].strip()
                                        
                                        # 清理不支持的Mermaid语法
                                        import re
                                        # 移除 ::icon(...) 语法
                                        diagram_code = re.sub(r'\s*::icon\([^)]*\)', '', diagram_code)
                                        # 移除 :::className 语法
                                        diagram_code = re.sub(r'\s*:::[^\s\n]+', '', diagram_code)
                                        # 移除 classDef 定义
                                        diagram_code = re.sub(r'classDef\s+\w+\s+[^\n]+\n?', '', diagram_code)
                                        # 移除 class 赋值
                                        diagram_code = re.sub(r'class\s+[\w,]+\s+\w+\s*\n?', '', diagram_code)
                                        
                                        tool_args["diagram_code"] = diagram_code
                                        logger.info(f"✅ 已生成图表代码，长度：{len(diagram_code)} 字符")
                                
                                # 执行工具
                                result = execute_tool(
                                    tool=tool_record,
                                    arguments=tool_args,
                                    settings=settings,
                                    session=session,
                                )
                                
                                # 保存结果
                                retrieval_results[tool_key] = {
                                    "arguments": tool_args,
                                    "result": result,
                                }
                                
                                thoughts.append(f"✅ 工具调用成功：{tool_key}")
                                observations.append(f"工具 {tool_key} 执行完成：{tool_reason}")
                                logger.info(f"✅ 工具 {tool_key} 调用成功")
                                
                            except Exception as e:
                                logger.error(f"工具 {tool_key} 调用失败: {e}")
                                thoughts.append(f"❌ 工具 {tool_key} 调用失败: {str(e)}")
                        else:
                            logger.warning(f"⚠️ 工具 {tool_key} 不可用")
                else:
                    thoughts.append(f"LLM判断：无需调用工具（{reasoning}）")
                    logger.info(f"💡 LLM判断无需工具调用：{reasoning}")
                    
            except Exception as e:
                logger.error(f"智能工具判断失败: {e}")
                thoughts.append(f"智能工具判断失败，跳过工具调用")
        
        # 4. 存储结果到共享工作空间
        workspace.store_agent_result(agent_id, retrieval_results)
        workspace.set_shared_data("retrieval_results", retrieval_results)
        
        # 5. 发送结果消息给协调器
        workspace.send_message(
            from_agent=agent_id,
            to_agent="orchestrator",
            message_type="result",
            content={
                "status": "completed",
                "retrieval_results": retrieval_results,
                "summary": f"检索完成，共找到 {len(retrieval_results)} 类结果",
            },
        )
        
        workspace.update_agent_status(agent_id, "completed")
        
        logger.info(f"✅ [检索专家] 执行完成，找到 {len(retrieval_results)} 类结果")
        
        return {
            "agent_thoughts": {agent_id: thoughts},
            "agent_observations": {agent_id: observations},
            "retrieved_contexts": retrieval_results.get("knowledge_base", []),
        }
    
    except Exception as e:
        logger.error(f"❌ [检索专家] 执行失败: {e}", exc_info=True)
        workspace.update_agent_status(agent_id, "failed")
        workspace.send_message(
            from_agent=agent_id,
            to_agent="orchestrator",
            message_type="error",
            content={"error": str(e)},
        )
        
        return {
            "agent_thoughts": {agent_id: [f"执行失败: {str(e)}"]},
            "error": str(e),
        }


# ==================== 分析专家（Analysis Specialist） ====================

async def analysis_specialist_node(
    state: MultiAgentState,
    settings: Settings,
    session: Session,
) -> Dict[str, Any]:
    """
    分析专家智能体
    
    职责：
    - 数据分析
    - 内容理解
    - 关键信息提取
    
    能力：
    - 文本分析（使用 LLM）
    - 数据提取
    - 模式识别
    """
    logger.info("📊 [分析专家] 开始执行分析任务...")
    
    workspace = SharedWorkspace(state)
    agent_id = "analysis_specialist"
    
    workspace.register_agent(agent_id)
    workspace.update_agent_status(agent_id, "running")
    
    user_query = state.get("user_query", "")
    thoughts = []
    observations = []

    try:
        # 1. 获取检索专家和MySQL专家的结果
        retrieval_results = workspace.get_shared_data("retrieval_results", {})
        mysql_results = workspace.get_shared_data("mysql_results", {})  # 新增：获取MySQL结果

        if not retrieval_results and not mysql_results:
            thoughts.append("未找到检索结果或数据库查询结果，使用用户查询进行分析")
            analysis_context = f"用户查询：{user_query}"
        else:
            # 构建分析上下文
            context_parts = []

            # MySQL查询结果（新增）
            if mysql_results:
                context_parts.append("## MySQL数据库查询结果")

                # 提取SQL和结果
                sql_query = mysql_results.get('sql_query', '')
                result_count = mysql_results.get('result_count', 0)
                answer = mysql_results.get('answer', '')
                data = mysql_results.get('data', [])

                if sql_query:
                    context_parts.append(f"### 执行的SQL查询\n{sql_query}")

                if result_count > 0:
                    # 显示前5条数据供分析
                    import json
                    display_data = data[:5] if isinstance(data, list) else data
                    context_parts.append(
                        f"### 查询结果（共{result_count}条，显示前5条）\n"
                        f"{json.dumps(display_data, ensure_ascii=False, indent=2)}"
                    )

                if answer:
                    context_parts.append(f"### 数据库查询总结\n{answer}")

                thoughts.append(f"获取到MySQL查询结果：{result_count}条记录")

            # 知识库检索结果
            if "knowledge_base" in retrieval_results:
                kb_contexts = retrieval_results["knowledge_base"]
                context_parts.append(
                    f"## 知识库内容（{len(kb_contexts)} 个片段）\n"
                    + "\n".join([
                        f"- {ctx.get('content', '')[:200]}"
                        for ctx in kb_contexts[:3]
                    ])
                )

            # 网络搜索结果
            if "web_search" in retrieval_results:
                search_data = retrieval_results["web_search"]
                context_parts.append(
                    f"## 搜索结果（关键词: {search_data.get('query', '')}):\n"
                    f"{search_data.get('results', '')[:500]}"
                )

            analysis_context = "\n\n".join(context_parts)
            thoughts.append(f"获取到检索和数据库查询结果，准备分析")
        
        # 2. 使用 LLM 进行深度分析
        logger.info("🤔 使用 LLM 进行内容分析...")
        
        # 获取当前子任务的描述，以便针对性分析
        current_subtask = workspace.get_current_subtask()
        task_description = current_subtask.description if current_subtask else "深度分析内容"
        
        # 默认prompt（如果数据库中没有激活的模板，使用这个）
        default_analysis_prompt = f"""你是一个资深的技术分析专家和研究顾问。请对以下内容进行深度、系统化的分析。

【任务要求】：{task_description}

【用户问题】：{user_query}

【待分析内容】：
{analysis_context}

【分析维度】请从以下多个维度进行深入分析：

1. **核心概念识别**：
   - 识别并解释核心技术概念、术语
   - 区分基础概念与高级概念

2. **关键信息提取**：
   - 提取重要事实、数据、统计信息
   - 识别关键论点和结论
   - 标注信息来源（如有）

3. **技术原理分析**（如适用）：
   - 解释技术实现原理
   - 分析技术架构和设计思路
   - 对比不同技术方案的优劣

4. **关联性分析**：
   - 发现概念之间的逻辑关系
   - 识别因果关系、演进关系
   - 构建知识图谱式的关联

5. **趋势与洞察**：
   - 识别技术演进趋势
   - 发现潜在问题和挑战
   - 预测未来发展方向

6. **批判性思考**：
   - 指出信息的局限性
   - 识别可能存在的偏见或争议
   - 提出需要进一步验证的点

以 JSON 格式输出分析结果：
{{
  "core_concepts": [
    {{"concept": "概念名称", "explanation": "详细解释", "importance": "high|medium|low"}}
  ],
  "key_facts": [
    {{"fact": "事实描述", "source": "来源（如有）", "confidence": "high|medium|low"}}
  ],
  "key_data": [
    {{"data_point": "数据点", "value": "具体数值或描述", "context": "背景说明"}}
  ],
  "technical_principles": [
    {{"principle": "原理名称", "explanation": "原理解释", "advantages": ["优势1"], "limitations": ["局限1"]}}
  ],
  "relationships": [
    {{"from": "概念A", "to": "概念B", "relationship_type": "因果|演进|对比|补充", "description": "关系描述"}}
  ],
  "trends_insights": [
    {{"trend": "趋势描述", "evidence": "支持证据", "implications": "影响分析"}}
  ],
  "critical_notes": [
    {{"note_type": "局限性|争议点|待验证", "description": "详细说明"}}
  ],
  "analysis_summary": "全面的分析总结（300-500字）",
  "confidence_score": 0.0-1.0
}}

要求：
- 分析要深入、系统、全面
- 保持客观，避免主观臆断
- 优先使用提供的内容，标注推理部分
- 长度：500-1000字的深度分析

只返回 JSON，不要其他解释。
"""
        
        # 从数据库获取激活的prompt，如果没有则使用默认prompt
        analysis_prompt = get_agent_prompt(
            default_prompt=default_analysis_prompt,
            user_query=user_query,
            task_description=task_description,
            analysis_context=analysis_context
        )
        
        llm_response, _ = await invoke_llm(
            messages=[{"role": "user", "content": analysis_prompt}],
            settings=settings,
            temperature=0.4,  # 保持适中温度
            max_tokens=2000,  # 优化：减少token限制
        )
        
        # 解析 LLM 响应
        analysis_result = parse_json_from_llm(llm_response)
        
        thoughts.append("完成内容分析，提取了关键信息")
        observations.append(
            f"分析完成：识别 {len(analysis_result.get('core_topics', []))} 个核心主题，"
            f"{len(analysis_result.get('key_facts', []))} 个关键事实"
        )
        
        # 3. 存储结果
        workspace.store_agent_result(agent_id, analysis_result)
        workspace.set_shared_data("analysis_result", analysis_result)
        
        # 4. 发送结果消息
        workspace.send_message(
            from_agent=agent_id,
            to_agent="orchestrator",
            message_type="result",
            content={
                "status": "completed",
                "analysis_result": analysis_result,
            },
        )
        
        workspace.update_agent_status(agent_id, "completed")
        
        logger.info("✅ [分析专家] 分析完成")
        
        return {
            "agent_thoughts": {agent_id: thoughts},
            "agent_observations": {agent_id: observations},
        }
    
    except Exception as e:
        logger.error(f"❌ [分析专家] 执行失败: {e}", exc_info=True)
        workspace.update_agent_status(agent_id, "failed")
        workspace.send_message(
            from_agent=agent_id,
            to_agent="orchestrator",
            message_type="error",
            content={"error": str(e)},
        )
        
        return {
            "agent_thoughts": {agent_id: [f"执行失败: {str(e)}"]},
            "error": str(e),
        }


# ==================== 总结专家（Summarization Specialist） ====================

async def summarization_specialist_node(
    state: MultiAgentState,
    settings: Settings,
    session: Session,
    tool_records: Optional[List["ToolRecord"]] = None,
) -> Dict[str, Any]:
    """
    总结专家智能体
    
    职责：
    - 信息整合
    - 报告生成
    - 结构化输出
    
    能力：
    - 内容总结
    - 报告撰写
    - 格式转换
    """
    logger.info("📝 [总结专家] 开始执行总结任务...")
    
    workspace = SharedWorkspace(state)
    agent_id = "summarization_specialist"
    
    workspace.register_agent(agent_id)
    workspace.update_agent_status(agent_id, "running")
    
    user_query = state.get("user_query", "")
    thoughts = []
    observations = []

    try:
        # 1. 收集所有智能体的结果
        retrieval_results = workspace.get_shared_data("retrieval_results", {})
        mysql_results = workspace.get_shared_data("mysql_results", {})  # 新增：获取MySQL结果
        analysis_result = workspace.get_shared_data("analysis_result", {})

        # 2. 构建总结上下文（包含MySQL查询结果）
        context_parts = []

        # MySQL数据库查询结果（新增）
        if mysql_results:
            context_parts.append("## MySQL数据库查询结果")

            sql_query = mysql_results.get('sql_query', '')
            result_count = mysql_results.get('result_count', 0)
            answer = mysql_results.get('answer', '')
            data = mysql_results.get('data', [])

            if sql_query:
                context_parts.append(f"### 执行的SQL查询\n```sql\n{sql_query}\n```")

            if result_count > 0:
                import json
                # 显示前10条数据
                display_data = data[:10] if isinstance(data, list) else data
                context_parts.append(
                    f"### 查询结果（共{result_count}条，显示前10条）\n"
                    f"```json\n{json.dumps(display_data, ensure_ascii=False, indent=2)}\n```"
                )

            if answer:
                context_parts.append(f"### 数据库查询总结\n{answer}")

        if retrieval_results:
            context_parts.append("## 检索与工具执行结果")

            # 知识库检索结果
            if "knowledge_base" in retrieval_results:
                kb_contexts = retrieval_results["knowledge_base"]
                context_parts.append(
                    f"### 知识库内容（{len(kb_contexts)} 个片段）\n"
                    + "\n".join([
                        f"{i + 1}. {ctx.get('content', '')[:300]}"
                        for i, ctx in enumerate(kb_contexts)
                    ])
                )

            # 通用工具结果处理 - 自动处理所有工具（天气、搜索、笔记等）
            tool_result_keys = [k for k in retrieval_results.keys() if k != "knowledge_base"]

            for tool_key in tool_result_keys:
                tool_data = retrieval_results[tool_key]

                # 获取工具名称
                from .tool_service import BUILTIN_TOOLS
                tool_name = BUILTIN_TOOLS.get(tool_key,
                                              type('obj', (object,), {'name': tool_key.replace('_', ' ').title()})).name

                # 提取结果内容
                if isinstance(tool_data, dict):
                    result_content = tool_data.get("result", "") or tool_data.get("data", "") or str(tool_data)
                else:
                    result_content = str(tool_data)

                # 限制长度
                result_preview = result_content[:1000] if len(result_content) > 1000 else result_content

                context_parts.append(
                    f"### {tool_name} 执行结果\n{result_preview}"
                )

        if analysis_result:
            context_parts.append("## 分析结果")
            context_parts.append(f"核心主题: {', '.join(analysis_result.get('core_topics', []))}")
            context_parts.append(f"关键发现: " + "; ".join(analysis_result.get('key_findings', [])[:3]))
            context_parts.append(f"分析总结: {analysis_result.get('analysis_summary', '')}")

        full_context = "\n\n".join(context_parts)

        thoughts.append("收集了所有智能体的结果（包括MySQL查询），准备生成总结")

        # 3. 使用 LLM 生成综合总结
        logger.info("✍️ 使用 LLM 生成综合总结...")

        # 获取当前子任务描述
        current_subtask = workspace.get_current_subtask()
        task_description = current_subtask.description if current_subtask else "生成全面的总结报告"

        # 检查是否有深度分析结果
        has_deep_analysis = analysis_result and "core_concepts" in analysis_result

        # 判断信息质量（包含MySQL查询）
        has_kb_info = "knowledge_base" in retrieval_results and len(retrieval_results.get("knowledge_base", [])) > 0
        has_mysql_info = mysql_results and mysql_results.get('result_count', 0) > 0

        # 构建信息源说明 - 自动识别所有已执行的工具和查询
        info_sources = []
        if has_mysql_info:
            info_sources.append("MySQL数据库查询")
        if has_kb_info:
            info_sources.append("知识库内容")

        # 通用处理：列出所有已执行的工具
        tool_result_keys = [k for k in retrieval_results.keys() if k != "knowledge_base"]
        if tool_result_keys:
            from .tool_service import BUILTIN_TOOLS
            for tool_key in tool_result_keys:
                tool_name = BUILTIN_TOOLS.get(tool_key,
                                              type('obj', (object,), {'name': tool_key.replace('_', ' ').title()})).name
                info_sources.append(tool_name)

        if info_sources:
            info_quality_note = f"✅ 已获取：{' + '.join(info_sources)}"
        else:
            info_quality_note = "⚠️ 检索信息有限，请基于自身知识合理回答，并说明信息来源的局限性"
        
        # 默认prompt（如果数据库中没有激活的模板，使用这个）
        default_summarization_prompt = f"""你是一个资深的智能助手。请基于以下信息，为用户生成清晰、准确的回答。

【任务要求】：{task_description}

【用户问题】：{user_query}

【收集到的信息】：
{full_context if full_context else "（未检索到特定信息）"}

【信息来源说明】：{info_quality_note}

【回答要求】：

1. **智能选择信息源**：
   - 如果有多个信息源（知识库、网络搜索），优先使用最相关的
   - 不要强制使用不相关的知识库内容
   - 如果网络搜索更准确，优先使用搜索结果
   - 如果信息不足或不相关，请诚实说明

2. **回答方式**：
   - **简单对话问题**：直接、简洁地回答（200-400字）
   - **信息查询**：提供准确信息，列出关键点（400-800字）
   - **研究报告**：使用 Markdown 格式，结构化组织（800-1500字）

3. **内容质量**：
   - 准确性第一：不编造不确定的信息
   - 直接回答用户问题，不要过度铺陈
   - 使用清晰的 Markdown 格式（标题、列表、引用）
   - 语言自然流畅，避免生硬的报告体

4. **特殊情况处理**：
   - 如果知识库内容与问题无关 → 忽略知识库，使用其他信息源或自身知识
   - 如果网络搜索结果更准确 → 优先使用搜索结果
   - 如果信息不足 → 坦诚说明，给出建议

5. **禁止行为**：
   - ❌ 不要强制凑字数成为冗长的报告
   - ❌ 不要使用无关的知识库内容
   - ❌ 不要编造数据或引用
   - ❌ 不要使用过于正式的报告模板（除非用户明确要求报告）

{"【补充】：已有深度分析结果，请充分利用分析专家提供的洞察" if has_deep_analysis else ""}

现在请直接、准确地回答用户问题：
"""
        
        # 从数据库获取激活的prompt，如果没有则使用默认prompt
        summarization_prompt = get_agent_prompt(
            default_prompt=default_summarization_prompt,
            user_query=user_query,
            task_description=task_description,
            full_context=full_context if full_context else "（未检索到特定信息）",
            info_quality_note=info_quality_note,
            has_deep_analysis="已有深度分析结果，请充分利用分析专家提供的洞察" if has_deep_analysis else ""
        )
        
        final_answer, _ = await invoke_llm(
            messages=[{"role": "user", "content": summarization_prompt}],
            settings=settings,
            temperature=0.45,  # 优化：降低温度提高稳定性
            max_tokens=2000,  # 优化：减少token限制提升速度
        )
        
        # 检查是否是错误消息
        if final_answer.startswith("LLM 调用") or len(final_answer) < 50:
            logger.warning(f"⚠️ [总结专家] LLM 响应异常: {final_answer}")
            # 降级策略：生成简单总结
            fallback_answer = f"""# {user_query}

## 执行摘要
本次多智能体协作完成了以下工作：

### 检索结果
{"✅ 已完成知识库检索和网络搜索" if retrieval_results else "⚠️ 检索信息有限"}

### 分析结果
{"✅ 已完成深度分析" if analysis_result else "⚠️ 分析信息有限"}

## 说明
由于LLM响应超时或异常，系统生成了简化版报告。建议：
1. 重新提交问题
2. 简化问题描述
3. 检查网络连接

原始错误信息：{final_answer}
"""
            final_answer = fallback_answer
            thoughts.append("LLM响应异常，使用降级策略生成简化报告")
        else:
            thoughts.append("生成了综合总结回答")
        
        observations.append(f"总结完成，生成回答长度：{len(final_answer)} 字符")
        
        # 4. 检查是否需要保存文件（write_note、draw_diagram）
        if tool_records:
            # 检查用户是否要求保存文件
            save_keywords = ["写入", "保存", "写", "生成文件", "创建文件", "保存到", "写入笔记", "绘制", "画", "思维导图"]
            user_wants_save = any(keyword in user_query for keyword in save_keywords)
            
            if user_wants_save:
                logger.info("📝 检测到用户要求保存文件，准备调用文件保存工具...")
                
                # 构建可用工具映射
                from .tool_service import BUILTIN_TOOLS
                available_tools_map = {}
                for tool in tool_records:
                    try:
                        config = json.loads(tool.config or "{}")
                        builtin_key = config.get("builtin_key")
                        if builtin_key and builtin_key in BUILTIN_TOOLS:
                            available_tools_map[builtin_key] = tool
                    except:
                        continue
                
                # 从用户查询中提取文件名（如果指定了）
                specified_filename = None
                if "名字为" in user_query or "名为" in user_query:
                    import re
                    match = re.search(r'(?:名字为|名为)\s*([^\s，。]+\.md)', user_query)
                    if match:
                        specified_filename = match.group(1)
                
                # 检查是否需要生成思维导图
                needs_diagram = "draw_diagram" in available_tools_map and any(kw in user_query for kw in ["思维导图", "绘制", "画图", "图表"])
                diagram_code = None
                
                if needs_diagram:
                    try:
                        # 生成思维导图代码
                        logger.info(f"🎨 为思维导图生成Mermaid代码...")
                        diagram_prompt = f"""请根据以下报告内容生成Mermaid思维导图代码：

【报告内容】：
{final_answer[:3000]}

【任务】：提取报告的核心主题和关键概念，生成一个结构清晰的Mermaid思维导图（graph TD格式）。
- 提取核心主题和关键概念
- 构建合理的层级结构
- 突出重要的关联关系

【语法要求】：
- 使用标准的 graph TD 格式
- 节点格式：A[文本内容]
- 连接格式：A --> B
- 不要使用 ::icon、:::class、classDef 等高级语法
- 不要使用 subgraph（子图）
- 保持语法简洁标准

请直接输出完整的Mermaid代码，不要有markdown代码块标记（不要```mermaid），不要有任何前缀说明。
示例格式：
graph TD
    A[主题] --> B[子概念1]
    A --> C[子概念2]
    B --> B1[细节]
"""
                        
                        diagram_code, _ = await invoke_llm(
                            messages=[{"role": "user", "content": diagram_prompt}],
                            settings=settings,
                            temperature=0.7,
                            max_tokens=2000,
                        )
                        # 清理可能的markdown代码块标记
                        diagram_code = diagram_code.strip()
                        if diagram_code.startswith("```"):
                            diagram_code = diagram_code.split("```", 2)[1]
                            if diagram_code.startswith("mermaid"):
                                diagram_code = diagram_code[7:]
                            diagram_code = diagram_code.strip()
                        if diagram_code.endswith("```"):
                            diagram_code = diagram_code[:-3].strip()
                        
                        # 清理不支持的Mermaid语法
                        import re
                        # 移除 ::icon(...) 语法
                        diagram_code = re.sub(r'\s*::icon\([^)]*\)', '', diagram_code)
                        # 移除 :::className 语法
                        diagram_code = re.sub(r'\s*:::[^\s\n]+', '', diagram_code)
                        # 移除 classDef 定义
                        diagram_code = re.sub(r'classDef\s+\w+\s+[^\n]+\n?', '', diagram_code)
                        # 移除 class 赋值
                        diagram_code = re.sub(r'class\s+[\w,]+\s+\w+\s*\n?', '', diagram_code)
                        
                        logger.info(f"✅ 已生成思维导图代码，长度：{len(diagram_code)} 字符")
                    except Exception as e:
                        logger.error(f"❌ 生成思维导图代码失败: {e}")
                        thoughts.append(f"⚠️ 思维导图生成失败: {str(e)}")
                
                # 检查是否需要write_note
                if "write_note" in available_tools_map and any(kw in user_query for kw in ["笔记", "报告", "总结", "写入", "保存"]):
                    try:
                        # 构建文件内容：报告 + 思维导图（如果生成）
                        file_content = final_answer
                        
                        if diagram_code:
                            # 如果用户指定了同一个文件名，将思维导图追加到报告中
                            if specified_filename:
                                file_content += f"\n\n---\n\n# 思维导图\n\n```mermaid\n{diagram_code}\n```\n"
                                thoughts.append("✅ 已将报告和思维导图合并写入同一文件")
                            else:
                                # 如果没指定文件名，思维导图会单独保存
                                pass
                        
                        # 确定文件名
                        filename = specified_filename if specified_filename else f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                        
                        logger.info(f"📝 调用write_note工具，文件名：{filename}")
                        result = execute_tool(
                            tool=available_tools_map["write_note"],
                            arguments={"filename": filename, "content": file_content},
                            settings=settings,
                            session=session,
                        )
                        thoughts.append(f"✅ 已保存报告到文件：{filename}")
                        observations.append(f"报告已保存到 {filename}")
                        logger.info(f"✅ 文件保存成功：{filename}")
                    except Exception as e:
                        logger.error(f"❌ 保存文件失败: {e}")
                        thoughts.append(f"⚠️ 文件保存失败: {str(e)}")
                
                # 如果用户没有指定文件名，且需要单独保存思维导图
                if needs_diagram and diagram_code and not specified_filename:
                    try:
                        filename = f"diagram_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                        logger.info(f"🎨 调用draw_diagram工具，文件名：{filename}")
                        result = execute_tool(
                            tool=available_tools_map["draw_diagram"],
                            arguments={"filename": filename, "diagram_code": diagram_code},
                            settings=settings,
                            session=session,
                        )
                        thoughts.append(f"✅ 已保存思维导图到文件：{filename}")
                        observations.append(f"思维导图已保存到 {filename}")
                        logger.info(f"✅ 思维导图保存成功：{filename}")
                    except Exception as e:
                        logger.error(f"❌ 保存思维导图失败: {e}")
                        thoughts.append(f"⚠️ 思维导图保存失败: {str(e)}")
        
        # 5. 存储结果
        workspace.store_agent_result(agent_id, {"final_answer": final_answer})
        workspace.set_shared_data("final_answer", final_answer)
        
        # 6. 发送结果消息
        workspace.send_message(
            from_agent=agent_id,
            to_agent="orchestrator",
            message_type="result",
            content={
                "status": "completed",
                "final_answer": final_answer,
            },
        )
        
        workspace.update_agent_status(agent_id, "completed")
        
        logger.info("✅ [总结专家] 总结完成")
        
        return {
            "agent_thoughts": {agent_id: thoughts},
            "agent_observations": {agent_id: observations},
            "final_answer": final_answer,
        }
    
    except Exception as e:
        logger.error(f"❌ [总结专家] 执行失败: {e}", exc_info=True)
        workspace.update_agent_status(agent_id, "failed")
        workspace.send_message(
            from_agent=agent_id,
            to_agent="orchestrator",
            message_type="error",
            content={"error": str(e)},
        )
        
        return {
            "agent_thoughts": {agent_id: [f"执行失败: {str(e)}"]},
            "error": str(e),
        }


# ==================== 验证专家（Verification Specialist） ====================

async def verification_specialist_node(
    state: MultiAgentState,
    settings: Settings,
    session: Session,
) -> Dict[str, Any]:
    """
    验证专家智能体（可选）
    
    职责：
    - 质量检查
    - 事实核查
    - 一致性验证
    
    能力：
    - 信息验证
    - 质量评估
    """
    logger.info("✔️ [验证专家] 开始执行验证任务...")
    
    workspace = SharedWorkspace(state)
    agent_id = "verification_specialist"
    
    workspace.register_agent(agent_id)
    workspace.update_agent_status(agent_id, "running")
    
    thoughts = []
    observations = []
    
    try:
        # 1. 获取最终答案
        final_answer = workspace.get_shared_data("final_answer", "")
        
        if not final_answer:
            thoughts.append("未找到最终答案，跳过验证")
            workspace.update_agent_status(agent_id, "skipped")
            return {
                "agent_thoughts": {agent_id: thoughts},
            }
        
        # 2. 使用 LLM 进行质量评估
        logger.info("🔍 使用 LLM 进行质量验证...")
        
        # 默认prompt（如果数据库中没有激活的模板，使用这个）
        default_verification_prompt = f"""请评估以下回答的质量：

回答内容：
{final_answer}

请从以下维度评估（0-10分）：
1. 准确性：信息是否准确可靠
2. 完整性：是否全面回答了问题
3. 清晰度：表达是否清晰易懂
4. 相关性：是否与问题相关

以 JSON 格式输出评估结果：
{{
  "accuracy_score": 0-10,
  "completeness_score": 0-10,
  "clarity_score": 0-10,
  "relevance_score": 0-10,
  "overall_score": 0-10,
  "issues": ["问题1", "问题2", ...],
  "suggestions": ["建议1", "建议2", ...],
  "verdict": "通过" 或 "需要改进"
}}

只返回 JSON，不要其他解释。
"""
        
        # 从数据库获取激活的prompt，如果没有则使用默认prompt
        verification_prompt = get_agent_prompt(
            default_prompt=default_verification_prompt,
            final_answer=final_answer
        )
        
        llm_response, _ = await invoke_llm(
            messages=[{"role": "user", "content": verification_prompt}],
            settings=settings,
            temperature=0.2,
            max_tokens=800,
        )
        
        verification_result = parse_json_from_llm(llm_response)
        
        overall_score = verification_result.get("overall_score", 7)
        verdict = verification_result.get("verdict", "通过")
        
        thoughts.append(f"完成质量验证，总分：{overall_score}/10")
        observations.append(f"验证结果：{verdict}，总分 {overall_score}/10")
        
        # 3. 存储结果
        workspace.store_agent_result(agent_id, verification_result)
        workspace.set_shared_data("verification_result", verification_result)
        
        # 4. 发送结果消息
        workspace.send_message(
            from_agent=agent_id,
            to_agent="orchestrator",
            message_type="result",
            content={
                "status": "completed",
                "verification_result": verification_result,
            },
        )
        
        workspace.update_agent_status(agent_id, "completed")
        
        logger.info(f"✅ [验证专家] 验证完成，结果：{verdict}")
        
        return {
            "agent_thoughts": {agent_id: thoughts},
            "agent_observations": {agent_id: observations},
            "quality_score": overall_score / 10.0,
        }
    
    except Exception as e:
        logger.error(f"❌ [验证专家] 执行失败: {e}", exc_info=True)
        workspace.update_agent_status(agent_id, "failed")
        workspace.send_message(
            from_agent=agent_id,
            to_agent="orchestrator",
            message_type="error",
            content={"error": str(e)},
        )
        
        return {
            "agent_thoughts": {agent_id: [f"执行失败: {str(e)}"]},
            "error": str(e),
        }
# ==================== Mysql专家（Mysql Specialist） ====================
async def mysql_specialist_node(
        state: MultiAgentState,
        settings: Settings,
        session: Session,
) -> Dict[str, Any]:
    """
    MySQL数据库专家智能体

    职责：
    - 与SQL数据库交互
    - 生成并执行SQL查询
    - 返回查询结果

    工作流程：
    1. 查看数据库中有哪些表可以查询
    2. 查询相关表的模式结构信息
    3. 创建语法正确的SQL查询语句
    4. 检查查询语句
    5. 执行查询并查看结果
    6. 基于查询结果返回最终答案
    """
    logger.info("🗄️ [MySQL专家] 开始执行数据库查询任务...")

    workspace = SharedWorkspace(state)
    agent_id = "mysql_specialist"

    # 注册智能体
    workspace.register_agent(agent_id)
    workspace.update_agent_status(agent_id, "running")

    user_query = state.get("user_query", "")

    mysql_results = {}  # 存储查询结果
    thoughts = []
    observations = []

    try:
        # 动态导入MySQL管理器
        from .mysql.mysql_manager import MySQLDatabaseManager

        # 从配置中正确获取数据库连接信息
        mysql_config = getattr(settings, 'mysql_config', None)

        if not mysql_config:
            error_msg = "MySQL配置未找到。请在config.py中正确配置mysql_config字段。"
            logger.error(error_msg)
            raise Exception(error_msg)

        # 正确读取配置字典中的值
        db_config = {
            "host": mysql_config.get('host', '127.0.0.1'),
            "port": mysql_config.get('port', 3306),
            "username": mysql_config.get('username', 'root'),
            "password": mysql_config.get('password', 'your-mysql-password'),
            "database": mysql_config.get('database', 'test'),
        }

        logger.info(
            f"🔌 准备连接MySQL: {db_config['username']}@{db_config['host']}:{db_config['port']}/{db_config['database']}")

        connection_string = (
            f"mysql+pymysql://{db_config['username']}:{db_config['password']}"
            f"@{db_config['host']}:{db_config['port']}/{db_config['database']}"
        )

        # 初始化数据库管理器
        try:
            db_manager = MySQLDatabaseManager(connection_string)
            logger.info(f"✅ MySQL连接已建立：{db_config['database']}")
            thoughts.append(f"已连接到数据库：{db_config['database']}")
        except Exception as conn_error:
            error_msg = f"数据库连接失败: {str(conn_error)}"
            logger.error(f"❌ {error_msg}")
            raise Exception(error_msg)

        # ===== 步骤1: 查看数据库中有哪些表可以查询 =====
        logger.info("📊 步骤1：查看数据库中有哪些表...")
        tables_info = db_manager.get_table_with_comments()

        if not tables_info:
            raise Exception("数据库中没有表")

        # 格式化表信息
        tables_desc = []
        for table_info in tables_info:
            table_name = table_info['table_name']
            table_comment = table_info['table_comment']
            if table_comment and not table_comment.isspace():
                tables_desc.append(f"- {table_name}: {table_comment}")
            else:
                tables_desc.append(f"- {table_name}")

        tables_text = "\n".join(tables_desc)
        thoughts.append(f"发现 {len(tables_info)} 个数据库表")
        observations.append(f"数据库表列表：\n{tables_text}")

        # ===== 步骤2: 查询相关表的模式结构信息 =====
        logger.info("🔍 步骤2：确定需要查询哪些表并获取其结构...")

        # 让LLM判断需要查询哪些表
        table_selection_prompt = f"""你是一个SQL数据库专家。根据用户问题，从以下表中选择需要查询的表。

【用户问题】：{user_query}

【数据库中的表】：
{tables_text}

请以JSON格式输出（只返回JSON，不要其他内容）：
{{
  "selected_tables": ["table1", "table2", ...],
  "reason": "选择理由"
}}
"""

        selection_response, _ = await invoke_llm(
            messages=[{"role": "user", "content": table_selection_prompt}],
            settings=settings,
            temperature=0.1,
            max_tokens=2000,
        )

        selection_data = parse_json_from_llm(selection_response)
        selected_tables = selection_data.get("selected_tables", [])
        selection_reason = selection_data.get("reason", "")

        if not selected_tables:
            raise Exception("未能确定需要查询的表")

        logger.info(f"✅ 选择了 {len(selected_tables)} 个表：{selected_tables}")
        thoughts.append(f"选择表：{', '.join(selected_tables)}")
        thoughts.append(f"理由：{selection_reason}")

        # 获取选中表的详细结构
        schema_info = db_manager.get_table_schema(selected_tables)
        observations.append(f"已获取 {len(selected_tables)} 个表的结构信息")

        # ===== 步骤3: 创建语法正确的SQL查询语句 =====
        logger.info("💡 步骤3：生成SQL查询语句...")

        # 🎯 核心修改：强化扩展关键词的 OR 查询逻辑
        selected_keywords = state.get("selected_keywords", [])
        keyword_condition_text = ""
        if selected_keywords:
            keyword_condition_text = f"\n【必须使用的查询关键词（必须用 OR 逻辑连接）】：{', '.join(selected_keywords)}\n"

        sql_generation_prompt = f"""你是一个专门设计用于与SQL数据库交互的AI智能体。
        给定一个输入问题，你需要创建一个语法正确的MySQL查询语句。

        【用户问题】：{user_query}{keyword_condition_text}

        【数据库结构】：
        {schema_info}

        【🔥核弹级强制要求 - 违背将导致系统崩溃🔥】：
        1. **绝对禁止任何统计与聚合**：即使问题中包含“采购量”、“总金额”、“分布”、“趋势”、“统计”等要求统计的字眼，你也**绝对禁止**使用 GROUP BY、COUNT()、SUM()、AVG() 等聚合函数！你的唯一任务是查出包含这些数据的**原始明细记录**（如具体的项目名称、金额、时间、链接等）。
        2. **🔥必须使用关键词过滤且严格使用 OR 连接🔥**：请在 WHERE 条件中，必须把提供的【查询关键词】加入到过滤条件中（对标题或项目名称等相关字段进行模糊匹配）。如果有多个关键词，它们之间**必须使用 OR 连接**包裹在括号内，绝对不能使用 AND。
           ✅ 正确示例：WHERE (XMMC LIKE '%词1%' OR XMMC LIKE '%词2%' OR XMMC LIKE '%词3%')
           ❌ 错误示例：WHERE XMMC LIKE '%词1%' AND XMMC LIKE '%词2%'
        3. 必须限制数据条数：返回最多 1000 条（LIMIT 1000），并按时间降序排列（如果有时间字段）。
        4. 绝对不要对数据库执行任何 DML 语句（INSERT、UPDATE、DELETE 等），只使用 SELECT。

        请严格以JSON格式输出（必须是原生合法的JSON字符串，绝对不要加 ```json 标签，不要换行截断）：
        {{
          "sql_query": "你生成的SQL明细查询语句",
          "explanation": "简短说明"
        }}
        """

        sql_response, _ = await invoke_llm(
            messages=[{"role": "user", "content": sql_generation_prompt}],
            settings=settings,
            temperature=0.0,
            max_tokens=8000,
        )

        sql_data = parse_json_from_llm(sql_response)
        sql_query = sql_data.get("sql_query", "")
        sql_explanation = sql_data.get("explanation", "")

        if not sql_query:
            raise Exception("未能生成SQL查询语句")

        logger.info(f"📝 生成的SQL：{sql_query}")
        thoughts.append("已生成SQL查询")
        observations.append(f"SQL: {sql_query}")
        observations.append(f"说明: {sql_explanation}")

        # ===== 步骤4: 检查查询语句 =====
        logger.info("✓ 步骤4：检查查询语句...")

        validation_result = db_manager.validate_query(sql_query)

        if "错误" in validation_result or "失败" in validation_result:
            # SQL验证失败，尝试修复
            logger.warning(f"⚠️ SQL验证失败：{validation_result}")
            thoughts.append("SQL验证失败，正在修复...")

            fix_prompt = f"""以下SQL查询验证失败，请修复并重新生成。

        【原SQL】：
        {sql_query}

        【错误信息】：
        {validation_result}

        【数据库结构】：
        {schema_info}

        【🔥强制要求🔥】：
        1. 修复语法错误。
        2. **再次强调：绝对禁止**使用聚合函数(GROUP BY/COUNT/SUM)！必须返回原始明细数据。
        3. **必须包含关键词的 WHERE 模糊匹配条件，且多个关键词必须用 OR 连接！** 例如：WHERE (列名 LIKE '%词A%' OR 列名 LIKE '%词B%')。
        4. 限制结果为 LIMIT 1000。

        请以纯JSON格式输出修复后的SQL（绝对不要加 ```json 标签，确保JSON可被解析）：
        {{
          "sql_query": "修复后的明细查询SQL",
          "changes": "修复了什么"
        }}
        """

            fix_response, _ = await invoke_llm(
                messages=[{"role": "user", "content": fix_prompt}],
                settings=settings,
                temperature=0.0,
                max_tokens=6000,
            )

            fix_data = parse_json_from_llm(fix_response)
            sql_query = fix_data.get("sql_query", sql_query)
            changes = fix_data.get("changes", "")

            logger.info(f"🔧 修复后的SQL：{sql_query}")
            thoughts.append(f"已修复SQL：{changes}")
            observations.append(f"修复后的SQL: {sql_query}")

            # 再次验证
            validation_result = db_manager.validate_query(sql_query)

        if "语法正确" in validation_result or "通过" in validation_result:
            logger.info(f"✅ SQL验证通过")
            observations.append("SQL语法验证通过")
        else:
            logger.warning(f"⚠️ SQL验证警告：{validation_result}")
            observations.append(f"SQL验证结果：{validation_result}")

        # ===== 步骤5: 执行查询并查看结果 =====
        logger.info("⚙️ 步骤5：执行SQL查询...")

        query_result = db_manager.execute_query(sql_query)

        if not query_result or query_result == "查询结果为空":
            final_answer = "查询执行成功，但未返回任何数据。"
            mysql_results = {
                "sql_query": sql_query,
                "result_count": 0,
                "data": [],
                "answer": final_answer
            }
            logger.info("✅ 查询成功，但无数据")
        else:
            # 解析结果
            try:
                import json
                result_data = json.loads(query_result)
                result_count = len(result_data) if isinstance(result_data, list) else 0

                logger.info(f"✅ 查询成功，返回 {result_count} 条记录")
                observations.append(f"查询执行成功，返回 {result_count} 条记录")

                # ===== 步骤6: 基于查询结果返回最终答案 =====
                logger.info("📊 步骤6：基于查询结果生成最终答案...")

                # 限制显示的数据量，避免token过多
                display_data = result_data[:1000] if isinstance(result_data, list) else result_data

                answer_prompt = f"""你是一个SQL数据库专家。请基于查询结果，用自然语言回答用户的问题。

【用户问题】：{user_query}

【执行的SQL】：{sql_query}

【查询结果】（共{result_count}条）：
{json.dumps(display_data, ensure_ascii=False, indent=2)}

【要求】：
- 用清晰、简洁的语言回答用户问题
- 如果结果很多，提供关键统计信息
- 如果结果为空，说明可能的原因
- 不要只是重复数据，要进行分析和总结

请直接输出答案（不要JSON格式）：
"""

                final_answer, _ = await invoke_llm(
                    messages=[{"role": "user", "content": answer_prompt}],
                    settings=settings,
                    temperature=0.3,
                    max_tokens=1500,
                )

                final_answer = final_answer.strip()

                mysql_results = {
                    "sql_query": sql_query,
                    "result_count": result_count,
                    "data": result_data,
                    "answer": final_answer
                }

                observations.append(f"最终答案：{final_answer}")

            except json.JSONDecodeError:
                final_answer = f"查询执行成功，返回结果：\n{query_result}"
                mysql_results = {
                    "sql_query": sql_query,
                    "raw_result": query_result,
                    "answer": final_answer
                }
                observations.append(final_answer)

        # 存储结果到共享工作空间
        workspace.store_agent_result(agent_id, mysql_results)
        workspace.set_shared_data("mysql_results", mysql_results)

        # 发送结果消息给协调器
        workspace.send_message(
            from_agent=agent_id,
            to_agent="orchestrator",
            message_type="result",
            content={
                "status": "completed",
                "mysql_results": mysql_results,
                "summary": f"数据库查询完成，返回 {mysql_results.get('result_count', 0)} 条记录",
            },
        )

        workspace.update_agent_status(agent_id, "completed")

        logger.info(f"✅ [MySQL专家] 任务完成")

        return {
            "agent_thoughts": {agent_id: thoughts},
            "agent_observations": {agent_id: observations},
            "mysql_data": mysql_results.get("data", []),
        }

    except Exception as e:
        logger.error(f"❌ [MySQL专家] 执行失败: {e}", exc_info=True)
        workspace.update_agent_status(agent_id, "failed")
        workspace.send_message(
            from_agent=agent_id,
            to_agent="orchestrator",
            message_type="error",
            content={"error": str(e)},
        )

        return {
            "agent_thoughts": {agent_id: [f"执行失败: {str(e)}"]},
            "error": str(e),
        }
# ==================== 智能体注册表 ====================

AGENT_REGISTRY = {
    "retrieval_specialist": {
        "name": "检索专家",
        "description": "负责知识库检索和网络搜索",
        "node_function": retrieval_specialist_node,
        "capabilities": ["knowledge_base_retrieval", "web_search", "document_analysis"],
    },
    "analysis_specialist": {
        "name": "分析专家",
        "description": "负责数据分析和内容理解",
        "node_function": analysis_specialist_node,
        "capabilities": ["text_analysis", "data_extraction", "pattern_recognition"],
    },
    "summarization_specialist": {
        "name": "总结专家",
        "description": "负责信息整合和报告生成",
        "node_function": summarization_specialist_node,
        "capabilities": ["content_summarization", "report_generation", "format_conversion"],
    },
    "verification_specialist": {
        "name": "验证专家",
        "description": "负责质量检查和事实核查（可选）",
        "node_function": verification_specialist_node,
        "capabilities": ["quality_check", "fact_verification", "consistency_validation"],
    },
    "mysql_specialist": {
        "name": "MySQL数据库专家",
        "description": "负责数据库查询和数据分析",
        "node_function": mysql_specialist_node,
        "capabilities": ["database_query", "sql_generation", "data_retrieval", "schema_analysis"],
    },
}


def get_agent_by_id(agent_id: str) -> Optional[Dict[str, Any]]:
    """根据ID获取智能体信息"""
    return AGENT_REGISTRY.get(agent_id)


def list_available_agents() -> List[Dict[str, Any]]:
    """列出所有可用的智能体"""
    return [
        {
            "id": agent_id,
            "name": info["name"],
            "description": info["description"],
            "capabilities": info["capabilities"],
        }
        for agent_id, info in AGENT_REGISTRY.items()
    ]


def get_default_prompts() -> List[Dict[str, Any]]:
    """获取所有默认的prompt模板（硬编码的原始prompt）"""
    return [
        {
            "agent_id": "retrieval_specialist",
            "name": "检索专家-默认模板",
            "description": "系统默认的检索专家说明模板，作为示例参考（检索专家主要执行检索操作，不直接使用LLM）",
            "content": """检索专家智能体职责说明：

【智能体角色】：检索专家（Retrieval Specialist）

【主要职责】：
1. 知识库检索（RAG）
   - 使用向量检索从知识库中查找相关内容
   - 支持语义搜索和关键词匹配
   - 返回最相关的文档片段

2. 网络搜索
   - 当用户查询包含搜索关键词时，执行网络搜索
   - 获取最新的网络信息
   - 整合搜索结果

3. 文档查找
   - 分析用户查询，确定需要检索的文档类型
   - 执行相应的检索策略

【工作流程】：
1. 接收用户查询：{user_query}
2. 判断是否需要知识库检索（根据use_knowledge_base标志）
3. 判断是否需要网络搜索（根据查询关键词）
4. 执行相应的检索操作
5. 整理检索结果并返回给协调器

【输出格式】：
检索结果以结构化格式返回，包括：
- knowledge_base: 知识库检索结果列表
- web_search: 网络搜索结果（如果执行了搜索）

【注意事项】：
- 检索专家主要负责信息检索，不进行内容分析
- 检索结果会传递给分析专家进行进一步处理
- 确保检索结果的准确性和相关性"""
        },
        {
            "agent_id": "analysis_specialist",
            "name": "分析专家-默认模板",
            "description": "系统默认的分析专家prompt，作为示例参考",
            "content": """你是一个资深的技术分析专家和研究顾问。请对以下内容进行深度、系统化的分析。

【任务要求】：{task_description}

【用户问题】：{user_query}

【待分析内容】：
{analysis_context}

【分析维度】请从以下多个维度进行深入分析：

1. **核心概念识别**：
   - 识别并解释核心技术概念、术语
   - 区分基础概念与高级概念

2. **关键信息提取**：
   - 提取重要事实、数据、统计信息
   - 识别关键论点和结论
   - 标注信息来源（如有）

3. **技术原理分析**（如适用）：
   - 解释技术实现原理
   - 分析技术架构和设计思路
   - 对比不同技术方案的优劣

4. **关联性分析**：
   - 发现概念之间的逻辑关系
   - 识别因果关系、演进关系
   - 构建知识图谱式的关联

5. **趋势与洞察**：
   - 识别技术演进趋势
   - 发现潜在问题和挑战
   - 预测未来发展方向

6. **批判性思考**：
   - 指出信息的局限性
   - 识别可能存在的偏见或争议
   - 提出需要进一步验证的点

以 JSON 格式输出分析结果：
{{
  "core_concepts": [
    {{"concept": "概念名称", "explanation": "详细解释", "importance": "high|medium|low"}}
  ],
  "key_facts": [
    {{"fact": "事实描述", "source": "来源（如有）", "confidence": "high|medium|low"}}
  ],
  "key_data": [
    {{"data_point": "数据点", "value": "具体数值或描述", "context": "背景说明"}}
  ],
  "technical_principles": [
    {{"principle": "原理名称", "explanation": "原理解释", "advantages": ["优势1"], "limitations": ["局限1"]}}
  ],
  "relationships": [
    {{"from": "概念A", "to": "概念B", "relationship_type": "因果|演进|对比|补充", "description": "关系描述"}}
  ],
  "trends_insights": [
    {{"trend": "趋势描述", "evidence": "支持证据", "implications": "影响分析"}}
  ],
  "critical_notes": [
    {{"note_type": "局限性|争议点|待验证", "description": "详细说明"}}
  ],
  "analysis_summary": "全面的分析总结（300-500字）",
  "confidence_score": 0.0-1.0
}}

要求：
- 分析要深入、系统、全面
- 保持客观，避免主观臆断
- 优先使用提供的内容，标注推理部分
- 长度：500-1000字的深度分析

只返回 JSON，不要其他解释。"""
        },
        {
            "agent_id": "summarization_specialist",
            "name": "总结专家-默认模板",
            "description": "系统默认的总结专家prompt，作为示例参考",
            "content": """你是一个资深的研究报告撰写专家。请基于以下信息，为用户生成一份高质量、结构化的研究报告或答案。

【任务要求】：{task_description}

【用户问题】：{user_query}

【收集到的信息】：
{full_context}

【报告撰写要求】：

1. **结构化组织**：
   - 使用清晰的 Markdown 格式
   - 合理的标题层级（# ## ### ）
   - 如果是研究报告，包含：引言、主要内容、结论
   - 如果是技术分析，包含：概述、技术原理、应用案例、趋势分析

2. **内容深度**：
   - 不要只是罗列信息，要进行深度整合和提炼
   - 建立不同信息点之间的逻辑联系
   - 提供清晰的论证和推理过程
   - 突出关键发现和核心洞察

3. **表达质量**：
   - 语言流畅、专业、准确
   - 避免重复和冗余
   - 使用具体的数据和案例支撑论点
   - 适当使用列表、表格等形式

4. **信息来源**：
   - 优先使用提供的检索结果和分析结果
   - 如果引用具体数据或观点，可注明来源
   - 区分事实陈述和推理结论

5. **完整性**：
   - 全面回答用户提出的所有问题点
   - 不遗漏关键信息
   - 如果信息不足，明确指出

6. **长度要求**：
   - 简单问题：300-600字
   - 中等复杂度：600-1200字
   - 复杂研究报告：1200-2000字

【特别注意】：
- 这是多智能体协作的最终输出，要体现高质量
- 整合所有前序智能体的工作成果
- 确保报告的专业性和可读性
{has_deep_analysis}

现在请生成最终报告："""
        },
        {
            "agent_id": "verification_specialist",
            "name": "验证专家-默认模板",
            "description": "系统默认的验证专家prompt，作为示例参考",
            "content": """请评估以下回答的质量：

回答内容：
{final_answer}

请从以下维度评估（0-10分）：
1. 准确性：信息是否准确可靠
2. 完整性：是否全面回答了问题
3. 清晰度：表达是否清晰易懂
4. 相关性：是否与问题相关

以 JSON 格式输出评估结果：
{{
  "accuracy_score": 0-10,
  "completeness_score": 0-10,
  "clarity_score": 0-10,
  "relevance_score": 0-10,
  "overall_score": 0-10,
  "issues": ["问题1", "问题2", ...],
  "suggestions": ["建议1", "建议2", ...],
  "verdict": "通过" 或 "需要改进"
}}

只返回 JSON，不要其他解释。"""
        },
    ]
