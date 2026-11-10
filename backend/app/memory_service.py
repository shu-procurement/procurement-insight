"""
记忆服务 - 负责记忆的提取、检索、存储和管理
"""
from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import List, Optional, Dict, Any, Tuple

import httpx
from sqlalchemy.orm import Session

from .config import Settings
from .database import (
    Memory,
    SessionConfig,
    create_memory,
    get_memory_by_id,
    search_memories,
    update_memory,
    update_memory_access,
    get_session_config,
)
from .rag_service import get_embeddings
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma

logger = logging.getLogger(__name__)

# 记忆向量数据库缓存
_MEMORY_VECTORSTORE_CACHE: Dict[str, Chroma] = {}


# ==================== 记忆提取模块 ====================

async def extract_memories_from_conversation(
    conversation_text: str,
    settings: Settings,
    session_id: str,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    使用 LLM 从对话中提取重要信息作为记忆
    
    Args:
        conversation_text: 对话文本
        settings: 配置对象
        session_id: 会话ID
        user_id: 用户ID（可选）
    
    Returns:
        提取的记忆列表，每个记忆包含 type, content, importance
    """
    try:
        extraction_prompt = f"""分析以下对话，提取应该被长期记住的重要信息。

对话内容：
{conversation_text}

请提取以下类型的信息：
1. **fact** - 明确的事实信息（如：用户的名字、职业、工作地点、居住地、年龄、技能等）
   - **特别注意**：如果对话中提到用户的名字，必须提取为 fact 类型，重要性设为 90-100
   - 例如："我叫张三" → {{"type": "fact", "content": "用户的名字是张三", "importance": 95}}
2. **preference** - 用户的偏好和习惯（如：喜欢的食物、编程语言、工作习惯、兴趣爱好等）
3. **event** - 重要的事件或计划（如：生日、会议安排、旅行计划、重要日期等）
4. **relationship** - 人物关系或社交信息（如：家人、朋友、同事关系等）

请以 JSON 格式输出提取的记忆：
{{
  "memories": [
    {{
      "type": "fact|preference|event|relationship",
      "content": "记忆内容的简洁描述（使用第三人称，如'用户的名字是XXX'）",
      "importance": 50-100
    }}
  ]
}}

要求：
1. **必须提取用户姓名**：如果对话中提到用户的名字（如"我叫XXX"、"我是XXX"），必须提取为 fact 类型，importance 设为 90-100
2. 只提取真正重要、值得长期记住的信息
3. 内容要简洁、明确，使用第三人称描述（如"用户的名字是XXX"而不是"我的名字是XXX"）
4. importance 评分要合理：
   - 姓名、职业等关键信息：90-100
   - 重要偏好、事件：70-89
   - 一般信息：50-69
5. 如果对话中没有重要信息，返回空的 memories 数组
6. 只返回 JSON，不要其他解释
"""

        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        endpoint = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"

        payload = {
            "model": "deepseek-v3.2",
            "messages": [{"role": "user", "content": extraction_prompt}],
            "temperature": 0.3,
            "max_tokens": 1000,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            response = await client.post(endpoint, json=payload, headers=headers)

        if response.status_code != 200:
            logger.error(f"记忆提取 API 错误 {response.status_code}: {response.text}")
            return []

        data = response.json()
        reply_text = data["choices"][0]["message"]["content"]

        # 解析 JSON 响应
        memories = _parse_memory_extraction(reply_text)

        logger.info(f"从对话中提取了 {len(memories)} 条记忆")
        return memories

    except Exception as e:
        logger.error(f"记忆提取失败: {e}", exc_info=True)
        return []


def _parse_memory_extraction(text: str) -> List[Dict[str, Any]]:
    """解析 LLM 返回的记忆提取结果"""
    try:
        # 移除可能的 markdown 代码块标记
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        data = json.loads(cleaned)
        memories = data.get("memories", [])

        # 验证和清理记忆数据
        validated = []
        for mem in memories:
            mem_type = mem.get("type", "").lower()
            if mem_type not in ["fact", "preference", "event", "relationship"]:
                continue
            
            content = mem.get("content", "").strip()
            if not content:
                continue
            
            importance = int(mem.get("importance", 50))
            importance = max(50, min(100, importance))

            validated.append({
                "type": mem_type,
                "content": content,
                "importance": importance,
            })

        return validated

    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败: {e}, 原始文本: {text[:200]}")
        return []
    except Exception as e:
        logger.error(f"记忆解析失败: {e}", exc_info=True)
        return []


# ==================== 相似度检测模块 ====================

def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的相似度（0-1）
    使用 SequenceMatcher 计算序列相似度
    """
    if not text1 or not text2:
        return 0.0
    
    # 转换为小写并去除多余空格
    text1 = re.sub(r'\s+', ' ', text1.lower().strip())
    text2 = re.sub(r'\s+', ' ', text2.lower().strip())
    
    if text1 == text2:
        return 1.0
    
    similarity = SequenceMatcher(None, text1, text2).ratio()
    return similarity


def calculate_jaccard_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的 Jaccard 相似度（0-1）
    基于词汇集合的交集和并集
    """
    if not text1 or not text2:
        return 0.0
    
    # 分词（简单分词，按空格和标点）
    words1 = set(re.findall(r'\w+', text1.lower()))
    words2 = set(re.findall(r'\w+', text2.lower()))
    
    if not words1 or not words2:
        return 0.0
    
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    
    if union == 0:
        return 0.0
    
    return intersection / union


def find_similar_memory(
    session: Session,
    new_content: str,
    memory_type: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    threshold: float = 0.75,
) -> Optional[Tuple[Memory, float]]:
    """
    查找与新记忆相似的已有记忆

    注意：去重检查时全局搜索（忽略 session_id），避免在不同会话中创建重复记忆

    Args:
        session: 数据库会话
        new_content: 新记忆的内容
        memory_type: 记忆类型
        user_id: 用户ID（可选）
        session_id: 会话ID（可选，但在去重时会被忽略）
        threshold: 相似度阈值（0-1），超过此值认为相似

    Returns:
        (相似记忆, 相似度) 或 None
    """
    # 获取同类型的记忆（去重时全局搜索，不限制 session_id）
    similar_memories = search_memories(
        session=session,
        memory_type=memory_type,
        user_id=user_id,
        session_id=None,  # 🔧 去重时忽略 session_id，全局搜索避免重复
        limit=50,  # 增加搜索范围以提高去重准确率
    )
    logger.info(f"🔍 去重检查：新记忆='{new_content[:50]}...'，找到 {len(similar_memories)} 条同类型记忆")
    if not similar_memories:
        logger.info(f"✨ 没有找到相似记忆，将创建新记忆")
        return None
    best_match = None
    best_similarity = 0.0
    # 计算与每条记忆的相似度
    for memory in similar_memories:
        # 文本相似度
        text_sim = calculate_text_similarity(new_content, memory.content)
        # Jaccard 相似度
        jaccard_sim = calculate_jaccard_similarity(new_content, memory.content)

        # 综合相似度（文本相似度权重0.6，Jaccard相似度权重0.4）
        combined_sim = text_sim * 0.6 + jaccard_sim * 0.4

        logger.debug(f"相似度对比: 新记忆='{new_content[:50]}...' vs 已有='{memory.content[:50]}...' => text_sim={text_sim:.3f}, jaccard_sim={jaccard_sim:.3f}, combined={combined_sim:.3f}")

        if combined_sim > best_similarity:
            best_similarity = combined_sim
            best_match = memory

    # 如果相似度超过阈值，返回最佳匹配
    if best_match and best_similarity >= threshold:
        logger.info(f"🎯 发现相似记忆: {best_match.id}, 相似度: {best_similarity:.3f} (阈值={threshold}), 将合并")
        return (best_match, best_similarity)

    if best_match:
        logger.info(f"⚠️ 最相似记忆相似度 {best_similarity:.3f} 未达到阈值 {threshold}，将创建新记忆")

    return None


# ==================== 记忆合并模块 ====================

def merge_similar_memories(
    session: Session,
    existing_memory: Memory,
    new_content: str,
    new_importance: int,
    new_metadata: Optional[Dict[str, Any]] = None,
) -> Memory:
    """
    将新记忆合并到已有记忆中
    
    策略：
    1. 如果新内容更完整或更详细，更新内容
    2. 取更高的重要性评分
    3. 合并元数据
    4. 更新访问统计
    """
    # 判断哪个内容更好（更长或包含更多信息）
    existing_content = existing_memory.content
    should_update_content = False
    
    # 如果新内容更长或包含更多关键词，认为是更好的版本
    if len(new_content) > len(existing_content) * 1.2:
        should_update_content = True
    elif len(new_content) > len(existing_content):
        # 新内容稍长，检查是否包含更多信息
        new_words = set(re.findall(r'\w+', new_content.lower()))
        existing_words = set(re.findall(r'\w+', existing_content.lower()))
        if len(new_words - existing_words) > len(existing_words - new_words):
            should_update_content = True
    
    # 更新内容（如果需要）
    final_content = new_content if should_update_content else existing_content
    
    # 取更高的重要性评分
    final_importance = max(existing_memory.importance_score, new_importance)
    
    # 准备元数据
    merged_metadata = new_metadata or {}
    merged_metadata["merged_count"] = merged_metadata.get("merged_count", 0) + 1
    merged_metadata["similarity_merge"] = True
    
    # 更新记忆
    updated_memory = update_memory(
        session=session,
        memory_id=existing_memory.id,
        content=final_content if should_update_content else None,
        importance_score=final_importance,
        metadata=merged_metadata,
    )
    
    logger.info(
        f"合并记忆: {existing_memory.id}, "
        f"内容{'已更新' if should_update_content else '保留'}, "
        f"重要性: {final_importance}"
    )
    
    return updated_memory


def save_memory_with_dedup(
    session: Session,
    content: str,
    memory_type: str,
    importance_score: int = 50,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
    threshold: float = 0.75,
) -> Memory:
    """
    保存记忆，并在保存前检查重复并合并
    
    Args:
        session: 数据库会话
        content: 记忆内容
        memory_type: 记忆类型
        importance_score: 重要性评分
        user_id: 用户ID
        session_id: 会话ID
        tags: 标签列表
        metadata: 元数据
        threshold: 相似度阈值
    
    Returns:
        保存或合并后的记忆对象
    """
    # 查找相似记忆
    similar_result = find_similar_memory(
        session=session,
        new_content=content,
        memory_type=memory_type,
        user_id=user_id,
        session_id=session_id,
        threshold=threshold,
    )
    
    if similar_result:
        existing_memory, similarity = similar_result
        # 合并到已有记忆
        merged_metadata = metadata or {}
        merged_metadata["similarity_score"] = similarity
        
        merged_memory = merge_similar_memories(
            session=session,
            existing_memory=existing_memory,
            new_content=content,
            new_importance=importance_score,
            new_metadata=merged_metadata,
        )
        
        return merged_memory
    else:
        # 没有找到相似记忆，保存新记忆
        new_memory = create_memory(
            session=session,
            content=content,
            memory_type=memory_type,
            importance_score=importance_score,
            user_id=user_id,
            session_id=session_id,
            tags=tags,
            metadata=metadata,
        )
        
        logger.info(f"创建新记忆: {new_memory.id}, 类型: {memory_type}")
        return new_memory


# ==================== 向量存储模块 ====================

def get_memory_vectorstore(settings: Settings) -> Chroma:
    """
    获取记忆向量数据库（独立的 collection）
    使用独立的 collection 存储记忆，与文档分开
    """
    key = str(settings.chroma_dir)
    store = _MEMORY_VECTORSTORE_CACHE.get(key)
    if store is None:
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        store = Chroma(
            collection_name="memories",
            embedding_function=get_embeddings(),
            persist_directory=str(settings.chroma_dir),
        )
        _MEMORY_VECTORSTORE_CACHE[key] = store
        logger.info("记忆向量数据库初始化完成")
    return store


def add_memory_to_vectorstore(
    memory_id: str,
    content: str,
    memory_type: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> None:
    """
    将记忆添加到向量数据库
    
    Args:
        memory_id: 记忆ID
        content: 记忆内容
        memory_type: 记忆类型
        user_id: 用户ID
        session_id: 会话ID（用于记忆隔离）
        settings: 配置对象
    """
    try:
        if settings is None:
            from .config import get_settings
            settings = get_settings()
        
        vectorstore = get_memory_vectorstore(settings)
        
        # 创建 Document 对象
        metadata = {
            "memory_id": memory_id,
            "memory_type": memory_type,
            # 显式设置 user_id 和 session_id，即使为 None
            # 这样可以确保向量库的 filter 能正确工作
            "user_id": user_id if user_id else "",
            "session_id": session_id if session_id else "",
        }
        
        doc = Document(page_content=content, metadata=metadata)
        
        # 添加到向量数据库
        vectorstore.add_documents([doc], ids=[memory_id])
        
        logger.debug(f"记忆已向量化: {memory_id}")
        
    except Exception as e:
        logger.error(f"向量化记忆失败 {memory_id}: {e}", exc_info=True)


def update_memory_in_vectorstore(
    memory_id: str,
    content: str,
    memory_type: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> None:
    """
    更新向量数据库中的记忆
    先删除旧向量，再添加新向量
    """
    try:
        if settings is None:
            from .config import get_settings
            settings = get_settings()
        
        vectorstore = get_memory_vectorstore(settings)
        
        # 删除旧向量
        try:
            vectorstore.delete(ids=[memory_id])
        except Exception as e:
            logger.warning(f"删除旧向量失败: {e}")
        
        # 添加新向量
        add_memory_to_vectorstore(
            memory_id=memory_id,
            content=content,
            memory_type=memory_type,
            user_id=user_id,
            session_id=session_id,
            settings=settings,
        )
        
        logger.debug(f"记忆向量已更新: {memory_id}")
        
    except Exception as e:
        logger.error(f"更新记忆向量失败 {memory_id}: {e}", exc_info=True)


def delete_memory_from_vectorstore(
    memory_id: str,
    settings: Optional[Settings] = None,
) -> None:
    """从向量数据库中删除记忆"""
    try:
        if settings is None:
            from .config import get_settings
            settings = get_settings()
        
        vectorstore = get_memory_vectorstore(settings)
        vectorstore.delete(ids=[memory_id])
        
        logger.debug(f"记忆向量已删除: {memory_id}")
        
    except Exception as e:
        logger.warning(f"删除记忆向量失败: {e}")


def delete_memory_complete(
    session: Session,
    memory_id: str,
    settings: Optional[Settings] = None,
) -> bool:
    """
    完整删除单条记忆（数据库 + 向量库）
    
    Returns:
        是否删除成功
    """
    from .database import delete_memory
    
    # 先删除向量
    delete_memory_from_vectorstore(memory_id, settings)
    
    # 再删除数据库记录
    success = delete_memory(session, memory_id)
    
    if success:
        logger.info(f"记忆已完整删除: {memory_id}")
    
    return success


# ==================== 混合检索模块 ====================

def _retrieve_memories_by_vector(
    query: str,
    session: Session,
    settings: Settings,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 5,
) -> List[Memory]:
    """使用向量检索记忆（语义相似度搜索）"""
    try:
        vectorstore = get_memory_vectorstore(settings)
        
        # 搜索候选
        search_k = min(limit * 5, 100)
        
        try:
            # 构建过滤条件（使用空字符串表示 None，确保能够过滤）
            filter_dict = {}
            if user_id:
                filter_dict["user_id"] = user_id
            if session_id:
                filter_dict["session_id"] = session_id
            
            # 执行向量搜索
            if filter_dict:
                results = vectorstore.similarity_search_with_score(
                    query,
                    k=search_k,
                    filter=filter_dict,
                )
            else:
                results = vectorstore.similarity_search_with_score(
                    query,
                    k=search_k,
                )
        except TypeError:
            # 如果不支持 filter，使用旧方法
            results = vectorstore.similarity_search_with_score(query, k=search_k)
        
        if not results:
            return []
        
        # 从向量结果中提取记忆ID和分数
        memory_scores = {}
        filtered_count = 0
        for doc, distance in results:
            memory_id = doc.metadata.get("memory_id")
            if not memory_id:
                continue
            
            # 过滤不匹配的用户/会话（使用空字符串表示 None）
            doc_user_id = doc.metadata.get("user_id", "")
            doc_session_id = doc.metadata.get("session_id", "")
            
            # 如果指定了 user_id，必须完全匹配（空字符串表示旧记忆没有 user_id）
            if user_id and doc_user_id != user_id:
                filtered_count += 1
                logger.debug(f"🚫 过滤记忆 {memory_id}：user_id 不匹配（要求={user_id}, 实际={doc_user_id}）")
                continue
            
            # 如果指定了 session_id，必须完全匹配（这样可以过滤掉其他会话和旧记忆）
            if session_id and doc_session_id != session_id:
                filtered_count += 1
                logger.debug(f"🚫 过滤记忆 {memory_id}：session_id 不匹配（要求={session_id}, 实际={doc_session_id}）")
                continue
            
            # 转换距离为相似度分数（0-1）
            similarity_score = max(0.0, 1.0 - (distance / 2.0))
            memory_scores[memory_id] = similarity_score
        
        if filtered_count > 0:
            logger.info(f"✂️ 向量检索过滤了 {filtered_count} 条不匹配的记忆")
        
        if not memory_scores:
            logger.info(f"❌ 向量检索没有找到匹配的记忆（session_id={session_id}）")
            return []
        
        # 从数据库加载记忆对象
        memories = []
        for memory_id, score in list(memory_scores.items())[:limit * 2]:
            memory = get_memory_by_id(session, memory_id)
            if memory:
                # 存储向量相似度分数
                memory._vector_score = score
                memories.append(memory)
                logger.debug(f"✅ 向量检索找到记忆: {memory_id}, session_id={memory.session_id}, 分数={score:.3f}")
        
        return memories[:limit]
        
    except Exception as e:
        logger.error(f"向量检索失败: {e}", exc_info=True)
        return []


async def retrieve_relevant_memories(
    session: Session,
    query: str,
    settings: Settings,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    max_memories: int = 5,
) -> List[Memory]:
    """
    检索与查询相关的记忆（混合检索）
    
    实现三层检索策略：
    1. 向量检索：使用 Chroma 进行语义搜索
    2. 关键词检索：SQL LIKE 查询作为补充
    3. 重要记忆补充：确保高重要性记忆（如姓名）始终可用
    
    Args:
        session: 数据库会话
        query: 查询文本
        settings: 配置对象
        user_id: 用户ID
        session_id: 会话ID（用于会话隔离）
        max_memories: 最大返回记忆数
    
    Returns:
        相关记忆列表
    """
    # 检查会话配置，决定是否共享记忆
    should_share = True
    if session_id:
        config = get_session_config(session, session_id)
        if config:
            should_share = config.share_memory
            logger.info(f"🔒 会话 {session_id} 的记忆共享设置: share_memory={should_share}")
        else:
            # 会话没有配置，从用户偏好中读取默认值
            from .database import get_user_preferences
            prefs = get_user_preferences(session, user_id or "default")
            if prefs:
                should_share = prefs.default_share_memory
                logger.info(f"🌐 会话 {session_id} 没有配置，使用用户偏好: share_memory={should_share}")
            else:
                logger.warning(f"⚠️ 会话 {session_id} 没有配置，且没有用户偏好，使用系统默认: share_memory={should_share}")
    
    # 如果不共享记忆，使用会话隔离
    effective_session_id = None if should_share else session_id
    
    if not should_share:
        logger.info(f"🔐 会话隔离模式：只检索 session_id={effective_session_id} 的记忆")
    
    all_memories = {}
    
    # 1. 向量检索
    vector_memories = _retrieve_memories_by_vector(
        query=query,
        session=session,
        settings=settings,
        user_id=user_id,
        session_id=effective_session_id,
        limit=max_memories,
    )
    for mem in vector_memories:
        all_memories[mem.id] = mem
    
    # 2. 关键词检索作为补充
    keyword_memories = search_memories(
        session=session,
        query=query,
        user_id=user_id,
        session_id=effective_session_id,
        min_importance=50,
        limit=max_memories,
    )
    for mem in keyword_memories:
        if mem.id not in all_memories:
            mem._vector_score = 0.0  # 没有向量分数
            all_memories[mem.id] = mem
    
    # 3. 补充重要的 fact 类型记忆（如姓名）
    if len(all_memories) < max_memories:
        important_memories = search_memories(
            session=session,
            memory_type="fact",
            user_id=user_id,
            session_id=effective_session_id,
            min_importance=80,
            limit=max_memories * 2,
        )
        for mem in important_memories:
            if mem.id not in all_memories and len(all_memories) < max_memories:
                mem._vector_score = 0.0
                all_memories[mem.id] = mem
    
    # 更新访问统计
    for mem_id in all_memories:
        update_memory_access(session, mem_id)
    
    # 综合评分排序
    sorted_memories = sorted(
        all_memories.values(),
        key=lambda m: (
            getattr(m, '_vector_score', 0.0) * 0.4 +  # 向量相似度权重
            m.importance_score / 100 * 0.3 +  # 重要性权重
            min(m.access_count / 10, 1.0) * 0.1 +  # 访问频率权重
            (1.0 if m.memory_type == "fact" else 0.5) * 0.2  # fact类型优先
        ),
        reverse=True,
    )[:max_memories]
    
    logger.info(f"混合检索找到 {len(sorted_memories)} 条相关记忆")
    return sorted_memories


# ==================== 记忆保存（含自动向量化）====================

async def save_conversation_and_extract_memories(
    session: Session,
    session_id: str,
    user_query: str,
    assistant_reply: str,
    settings: Settings,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Memory]:
    """
    保存对话并自动提取记忆
    
    Returns:
        新保存的记忆列表
    """
    # 首先保存对话消息到历史记录
    from .database import save_conversation_message
    
    try:
        # 保存用户消息
        save_conversation_message(
            session=session,
            session_id=session_id,
            role="user",
            content=user_query,
            user_id=user_id,
            metadata=metadata,
        )
        
        # 保存助手回复
        save_conversation_message(
            session=session,
            session_id=session_id,
            role="assistant",
            content=assistant_reply,
            user_id=user_id,
            metadata=metadata,
        )
        
        logger.debug(f"已保存对话到会话 {session_id}")
    except Exception as e:
        logger.error(f"保存对话消息失败: {e}", exc_info=True)
    
    # 检查会话配置
    config = get_session_config(session, session_id)
    if config and not config.auto_extract:
        logger.debug("会话禁用了自动提取，跳过记忆提取")
        return []
    
    # 构建对话文本
    conversation_text = f"用户: {user_query}\n助手: {assistant_reply}"
    
    # 提取记忆
    extracted_memories = await extract_memories_from_conversation(
        conversation_text=conversation_text,
        settings=settings,
        session_id=session_id,
        user_id=user_id,
    )
    
    # 保存提取的记忆（使用去重和合并逻辑，并自动向量化）
    saved_memories = []
    for mem in extracted_memories:
        try:
            # 使用去重保存（降低阈值，提高去重灵敏度）
            memory_record = save_memory_with_dedup(
                session=session,
                content=mem["content"],
                memory_type=mem["type"],
                importance_score=mem["importance"],
                user_id=user_id,
                session_id=session_id,
                metadata={"extracted_at": "auto", **(metadata or {})},
                threshold=0.65,  # 🔧 从 0.75 降低到 0.65，提高去重灵敏度
            )
            
            # 向量化
            add_memory_to_vectorstore(
                memory_id=memory_record.id,
                content=memory_record.content,
                memory_type=memory_record.memory_type,
                user_id=memory_record.user_id,
                session_id=memory_record.session_id,
                settings=settings,
            )
            
            saved_memories.append(memory_record)
            
        except Exception as e:
            logger.error(f"保存记忆失败: {e}", exc_info=True)
    
    logger.info(f"成功保存 {len(saved_memories)} 条记忆")
    return saved_memories


# ==================== 记忆格式化模块 ====================

def format_memories_for_prompt(memories: List[Memory]) -> str:
    """
    将记忆列表格式化为 LLM prompt（隐式格式）
    不显示"记忆"、"信息"等标签，只提供纯内容
    """
    if not memories:
        return ""
    
    return "\n".join(mem.content for mem in memories)













