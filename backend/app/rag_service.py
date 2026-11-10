from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from fastapi import HTTPException, UploadFile
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader, TextLoader
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
from sqlalchemy.orm import Session

from .config import Settings
from .database import DocumentRecord, get_document_by_hash

logger = logging.getLogger(__name__)


class UnsupportedFileTypeError(Exception):
    """Raised when the uploaded file type cannot be processed."""


@dataclass
class RetrievedContext:
    """Lightweight representation of a retrieved document snippet."""

    document_id: str | None
    original_name: str | None
    content: str


_EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_VECTORSTORE_CACHE: dict[str, Chroma] = {}
_RERANKER_CACHE: CrossEncoder | None = None
_BM25_CACHE: dict[str, Tuple[BM25Okapi, List[Document]]] = {}
_EMBEDDINGS_CACHE: HuggingFaceEmbeddings | None = None  # 添加嵌入模型缓存


def get_embeddings() -> HuggingFaceEmbeddings:
    """Return a cached embedding model instance."""
    global _EMBEDDINGS_CACHE
    if _EMBEDDINGS_CACHE is None:
        _EMBEDDINGS_CACHE = HuggingFaceEmbeddings(model_name=_EMBEDDING_MODEL_NAME)
    return _EMBEDDINGS_CACHE


def ingest_text_chunk(
    session: Session,
    settings: Settings,
    doc_id: str,
    content: str,
    metadata: dict
) -> None:
    """将文本块向量化并存入知识库（用于文件上传）"""
    try:
        # 创建 Document 对象
        doc = Document(page_content=content, metadata=metadata)
        
        # 获取向量数据库
        vectorstore = get_vectorstore(settings)
        
        # 添加文档（这一步可能较慢）
        vectorstore.add_documents([doc], ids=[doc_id])
        
        # 清除 BM25 缓存，强制重新构建
        key = str(settings.chroma_dir)
        if key in _BM25_CACHE:
            del _BM25_CACHE[key]
        
    except Exception as e:
        logger.error(f"❌ 文本块向量化失败 {doc_id}: {e}", exc_info=True)
        raise


def get_vectorstore(settings: Settings) -> Chroma:
    """Return a cached Chroma vector store bound to the project data directory."""
    key = str(settings.chroma_dir)
    store = _VECTORSTORE_CACHE.get(key)
    if store is None:
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        store = Chroma(
            collection_name="default",
            embedding_function=get_embeddings(),
            persist_directory=str(settings.chroma_dir),
        )
        _VECTORSTORE_CACHE[key] = store
    return store


def _determine_loader(path: Path) -> TextLoader | PyPDFLoader | Docx2txtLoader:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".py"}:
        return TextLoader(str(path), encoding="utf-8")
    if suffix == ".pdf":
        return PyPDFLoader(str(path))
    if suffix == ".docx":
        return Docx2txtLoader(str(path))
    raise UnsupportedFileTypeError(f"Unsupported file type: {suffix}")


async def ingest_document(
    upload: UploadFile, settings: Settings, session: Session
) -> DocumentRecord:
    """Persist a document, index its chunks into the vector store and track metadata."""
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    raw_bytes = await upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="上传文件为空。")

    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    existing = get_document_by_hash(session, content_hash)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"该文档已存在（ID: {existing.id}）。",
        )

    original_name = Path(upload.filename or "unnamed").name
    doc_id = uuid.uuid4().hex
    stored_filename = f"{doc_id}_{original_name}"
    stored_path = upload_dir / stored_filename

    with open(stored_path, "wb") as output:
        output.write(raw_bytes)

    try:
        loader = _determine_loader(stored_path)
        documents = loader.load()
    except UnsupportedFileTypeError as error:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail=str(error)) from error
    except Exception as error:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"解析文档失败：{error}") from error

    # 使用较小的chunk_size以提升处理速度
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,  # 较小的chunk处理更快
        chunk_overlap=50,  # 减小重叠以加快速度
        separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
    )
    chunks = splitter.split_documents(documents)
    if not chunks:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="未能从文档中提取任何文本内容。")

    for index, chunk in enumerate(chunks):
        chunk.metadata["document_id"] = doc_id
        chunk.metadata["chunk_index"] = index
        chunk.metadata["original_name"] = original_name
        chunk.metadata.setdefault("source", original_name)

    # 向量化和索引（这个步骤可能需要一些时间）
    logger.info(f"开始向量化文档: {original_name}, 共 {len(chunks)} 个片段")
    
    vectorstore = get_vectorstore(settings)
    ids = [f"{doc_id}_{index}" for index in range(len(chunks))]
    vectorstore.add_documents(chunks, ids=ids)
    logger.info(f"向量添加完成，正在持久化...")
    vectorstore.persist()
    logger.info(f"文档处理完成: {original_name}")
    
    # 清除 BM25 缓存，强制重建索引
    key = str(settings.chroma_dir)
    if key in _BM25_CACHE:
        del _BM25_CACHE[key]
        logger.info("已清除 BM25 缓存，下次检索时将重建")

    record = DocumentRecord(
        id=doc_id,
        original_name=original_name,
        stored_path=str(stored_path),
        file_size=len(raw_bytes),
        content_hash=content_hash,
        mime_type=upload.content_type,
        chunk_count=len(chunks),
        summary=_generate_summary(chunks),
    )
    session.add(record)
    session.commit()
    return record


def _generate_summary(chunks: List[Document]) -> str:
    joined = " ".join(chunk.page_content.strip() for chunk in chunks[:3])
    return joined[:500]


def list_documents(session: Session) -> List[DocumentRecord]:
    """Return documents ordered by creation time (desc)."""
    statement = (
        session.query(DocumentRecord)
        .order_by(DocumentRecord.created_at.desc())
    )
    return list(statement.all())


def delete_document(document_id: str, settings: Settings, session: Session) -> None:
    """Remove document metadata, vector entries and stored file."""
    record = session.get(DocumentRecord, document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="文档不存在。")

    try:
        # 删除向量数据库中的相关向量
        vectorstore = get_vectorstore(settings)
        
        # 获取所有该文档的 chunk IDs
        chunk_ids = [f"{document_id}_{i}" for i in range(record.chunk_count)]
        
        # 使用 IDs 删除而不是 where 条件
        if chunk_ids:
            logger.info(f"删除文档向量: {document_id}, 共 {len(chunk_ids)} 个片段")
            try:
                vectorstore.delete(ids=chunk_ids)
                # 新版 Chroma 自动持久化，不需要手动 persist
                logger.info(f"向量删除成功")
                
                # 清除所有缓存，强制重新加载
                key = str(settings.chroma_dir)
                if key in _VECTORSTORE_CACHE:
                    del _VECTORSTORE_CACHE[key]
                    logger.info(f"已清除向量数据库缓存")
                if key in _BM25_CACHE:
                    del _BM25_CACHE[key]
                    logger.info(f"已清除 BM25 缓存")
            except Exception as e:
                logger.warning(f"向量删除失败（可能已不存在）: {e}")
        
        # 删除本地文件
        stored_path = Path(record.stored_path)
        if stored_path.exists():
            stored_path.unlink()
            logger.info(f"文件删除成功: {stored_path}")
        else:
            logger.warning(f"文件不存在: {stored_path}")
        
        # 删除数据库记录
        session.delete(record)
        session.commit()
        logger.info(f"文档记录删除成功: {document_id}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文档失败: {e}", exc_info=True)
        session.rollback()
        raise HTTPException(status_code=500, detail=f"删除文档失败: {str(e)}")


def get_reranker() -> CrossEncoder:
    """Return a cached ReRank model instance."""
    global _RERANKER_CACHE
    if _RERANKER_CACHE is None:
        logger.info(f"加载 ReRank 模型: {_RERANK_MODEL_NAME}")
        _RERANKER_CACHE = CrossEncoder(_RERANK_MODEL_NAME)
        logger.info("ReRank 模型加载完成")
    return _RERANKER_CACHE


def _build_bm25_index(settings: Settings) -> Tuple[BM25Okapi | None, List[Document]]:
    """构建 BM25 索引（从向量数据库中获取所有文档）"""
    key = str(settings.chroma_dir)
    if key in _BM25_CACHE:
        return _BM25_CACHE[key]
    
    try:
        vectorstore = get_vectorstore(settings)
        # 获取所有文档
        all_docs = vectorstore.get()
        
        if not all_docs or not all_docs.get("documents"):
            logger.warning("向量数据库为空，无法构建 BM25 索引")
            return None, []
        
        # 构建文档对象列表
        documents = []
        for i, doc_text in enumerate(all_docs["documents"]):
            metadata = all_docs["metadatas"][i] if all_docs.get("metadatas") else {}
            documents.append(Document(page_content=doc_text, metadata=metadata))
        
        # 分词（简单按空格和标点分割）
        tokenized_corpus = [
            doc.page_content.replace("，", " ").replace("。", " ")
            .replace("！", " ").replace("？", " ").split()
            for doc in documents
        ]
        
        bm25 = BM25Okapi(tokenized_corpus)
        _BM25_CACHE[key] = (bm25, documents)
        logger.info(f"BM25 索引构建完成，共 {len(documents)} 个文档")
        return bm25, documents
    except Exception as e:
        logger.error(f"构建 BM25 索引失败: {e}", exc_info=True)
        return None, []


def _reciprocal_rank_fusion(
    results_list: List[List[Tuple[Document, float]]], k: int = 60
) -> List[Tuple[Document, float]]:
    """
    使用 Reciprocal Rank Fusion (RRF) 算法融合多个检索结果
    
    Args:
        results_list: 多个检索结果列表，每个结果是 [(doc, score), ...]
        k: RRF 常数，默认 60
    
    Returns:
        融合后的结果列表
    """
    # 计算每个文档的 RRF 分数
    doc_scores: dict[str, float] = {}
    doc_objects: dict[str, Document] = {}
    
    for results in results_list:
        for rank, (doc, _) in enumerate(results, start=1):
            # 使用文档内容作为唯一标识
            doc_id = doc.page_content[:100]  # 取前100字符作为ID
            
            if doc_id not in doc_scores:
                doc_scores[doc_id] = 0
                doc_objects[doc_id] = doc
            
            # RRF 公式: 1 / (k + rank)
            doc_scores[doc_id] += 1.0 / (k + rank)
    
    # 按分数排序
    sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
    
    # 返回文档和分数
    return [(doc_objects[doc_id], score) for doc_id, score in sorted_docs]


def retrieve_context(
        query: str,
        settings: Settings,
        top_k: int,
        selected_keywords: List[str] = None  # 新增参数：用户二次筛选后的关键词
) -> List[RetrievedContext]:
    """
    增强版检索：混合检索（向量 + BM25）+ ReRank
    支持通过 selected_keywords 进行查询扩展
    """
    vectorstore = get_vectorstore(settings)

    # 融合关键词构造最终的检索查询词
    search_query = query
    if selected_keywords:
        search_query = f"{query} {' '.join(selected_keywords)}"
        logger.info(f"启用查询扩展，扩展后检索词: '{search_query}'")

    try:
        # 1. 向量检索（召回 top_k * 3）
        # 使用扩充后的 search_query 进行向量搜索
        vector_results = vectorstore.similarity_search_with_score(search_query, k=top_k * 3)
        logger.info(f"向量检索: '{search_query}', 找到 {len(vector_results)} 个结果")

        # 2. BM25 关键词检索（召回 top_k * 3）
        bm25, bm25_docs = _build_bm25_index(settings)
        bm25_results = []

        if bm25 and bm25_docs:
            # 使用扩充后的 search_query 进行分词
            query_tokens = search_query.replace("，", " ").replace("。", " ").split()
            bm25_scores = bm25.get_scores(query_tokens)

            top_indices = sorted(
                range(len(bm25_scores)),
                key=lambda i: bm25_scores[i],
                reverse=True
            )[:top_k * 3]

            bm25_results = [(bm25_docs[i], bm25_scores[i]) for i in top_indices]
            logger.info(f"BM25 检索: 找到 {len(bm25_results)} 个结果")

        # 3. 混合检索（RRF 融合）
        if bm25_results:
            merged_results = _reciprocal_rank_fusion([vector_results, bm25_results])
            logger.info(f"混合检索: 融合后共 {len(merged_results)} 个结果")
        else:
            merged_results = vector_results
            logger.info("仅使用向量检索结果")

        # 4. ReRank 二次排序（取 top_k * 2 进行重排）
        candidates = merged_results[:top_k * 2]

        if len(candidates) > 1:
            reranker = get_reranker()
            # ReRank 时，使用扩展后的 query 与 document 进行相关性评估效果更好
            pairs = [[search_query, doc.page_content] for doc, _ in candidates]
            rerank_scores = reranker.predict(pairs)

            reranked = sorted(
                zip(candidates, rerank_scores),
                key=lambda x: x[1],
                reverse=True
            )

            final_results = [(doc, score) for (doc, _), score in reranked[:top_k]]
            logger.info(f"ReRank 完成，最终返回 {len(final_results)} 个结果")
        else:
            final_results = candidates[:top_k]

        # 5. 转换为 RetrievedContext
        snippets: List[RetrievedContext] = []
        for doc, score in final_results:
            snippets.append(
                RetrievedContext(
                    document_id=doc.metadata.get("document_id"),
                    original_name=doc.metadata.get("original_name"),
                    content=doc.page_content.strip(),
                )
            )

        return snippets

    except Exception as e:
        logger.error(f"检索失败: {e}", exc_info=True)
        try:
            results = vectorstore.similarity_search(search_query, k=top_k)
            return [
                RetrievedContext(
                    document_id=doc.metadata.get("document_id"),
                    original_name=doc.metadata.get("original_name"),
                    content=doc.page_content.strip(),
                )
                for doc in results
            ]
        except:
            return []

def retrieve_context_with_confidence(
    query: str, settings: Settings, top_k: int, confidence_threshold: float = 0.3,
selected_keywords: List[str] = None
) -> Tuple[List[RetrievedContext], str]:
    """
    带置信度评分的检索，如果检索质量低则返回低置信度标记
    
    Args:
        query: 用户查询
        settings: 配置对象
        top_k: 返回结果数量
        confidence_threshold: 置信度阈值（ReRank 分数）
    
    Returns:
        (检索结果列表, 置信度标记: "high" 或 "low")
    """
    vectorstore = get_vectorstore(settings)
    
    try:
        # 1. 传递 selected_keywords
        snippets = retrieve_context(query, settings, top_k, selected_keywords)

        if not snippets:
            return [], "low"

        # 2. ReRank 置信度计算依然可以使用组合后的词
        search_query = query if not selected_keywords else f"{query} {' '.join(selected_keywords)}"
        reranker = get_reranker()
        pairs = [[search_query, snippet.content] for snippet in snippets]
        scores = reranker.predict(pairs)
        
        # 3. 计算平均分数（scores 是 numpy 数组）
        avg_score = float(scores.mean()) if len(scores) > 0 else 0
        max_score = float(scores.max()) if len(scores) > 0 else 0
        
        logger.info(f"置信度评估 - 平均分: {avg_score:.4f}, 最高分: {max_score:.4f}")
        
        # 4. 判断置信度（如果最高分都低于阈值，说明知识库中可能没有相关内容）
        if max_score < confidence_threshold:
            logger.warning(f"检索置信度低 (max={max_score:.4f} < {confidence_threshold})")
            return snippets, "low"
        
        return snippets, "high"
        
    except Exception as e:
        logger.error(f"置信度评估失败: {e}", exc_info=True)
        # 降级处理
        snippets = retrieve_context(query, settings, top_k)
        return snippets, "unknown"


async def expand_query_keywords(query: str, settings: Settings) -> List[str]:
    """
    查询扩展：智能解析用户输入的问题，自动识别核心产品/行业关键词，并扩充同义词或细分品类。
    返回 8-12 个关键词，供前端展示和用户二次筛选。
    """
    # 局部导入避免潜在的循环依赖
    from .graph_agent import invoke_llm, parse_json_from_llm

    logger.info(f"🔍 正在为查询智能扩充关键词: '{query}'")

    prompt = f"""
    你是一个专业的采购与数据检索助手。请智能解析用户输入的问题，自动识别出问题中的【核心产品、行业或服务】实体，并为其生成 8-12 个高度相关的同义词、细分品类、上下级概念或行业专业术语。
    这些扩充词将用于在数据库中进行全面检索，以防遗漏。

    【示例】
    用户问题：“帮我分析一下牛奶行业的采购趋势”
    识别的核心词：“牛奶”
    扩充关键词：["牛乳", "液态奶", "鲜牛奶", "纯牛奶", "灭菌乳", "巴氏奶", "常温奶", "全脂牛奶", "低脂牛奶", "脱脂牛奶"]

    用户问题：{query}

    请仅返回一个 JSON 格式的字典，包含一个 "keywords" 列表，列表中全部为字符串格式的扩充词。不要有任何其他解释、前缀或 Markdown 标记。
    示例格式：
    {{
        "keywords": ["关键词1", "关键词2", "关键词3"]
    }}
    """

    try:
        # 调用大模型生成关键词
        # 适当调高 temperature (例如 0.4) 可以让模型发散思维，找出更多细分品类
        llm_response, _ = await invoke_llm(
            messages=[{"role": "user", "content": prompt}],
            settings=settings,
            temperature=0.4,
            max_tokens=300,
        )

        parsed_data = parse_json_from_llm(llm_response)
        keywords = parsed_data.get("keywords", [])

        # 确保返回格式正确，并限制在最多 12 个以内，防止前端溢出
        if not isinstance(keywords, list):
            return []

        logger.info(f"✅ 查询扩展完成，生成联想词: {keywords[:12]}")
        return keywords[:12]

    except Exception as e:
        logger.error(f"❌ 查询扩展（联想词生成）失败: {e}", exc_info=True)
        return []
