from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Callable, List
from .mysql.mysql_manager import MySQLDatabaseManager
import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import Settings
from .database import ToolExecutionLog, ToolRecord
from .rag_service import retrieve_context as rag_retrieve_context, list_documents as rag_list_documents


class ToolExecutionError(Exception):
    """Raised when executing a tool fails."""


@dataclass
class BuiltinToolDefinition:
    key: str
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any], Settings, Session], str]


def _slugify_filename(filename: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]", "-", filename).strip("-")
    if not sanitized:
        raise ToolExecutionError("文件名仅允许字母、数字、下划线、点或中划线。")
    return sanitized


def _handle_write_note(args: Dict[str, Any], settings: Settings, session: Session) -> str:  # noqa: ARG001
    filename = args.get("filename")
    content = args.get("content")
    if not filename or not isinstance(filename, str):
        raise ToolExecutionError("缺少 filename 字段。")
    if not content or not isinstance(content, str):
        raise ToolExecutionError("缺少 content 字段。")
    safe_name = _slugify_filename(filename)
    notes_dir = settings.data_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    target = notes_dir / safe_name
    target.write_text(content, encoding="utf-8")
    return f"已创建/覆盖笔记 {target} ，长度 {len(content)} 个字符。"


def _handle_list_documents(args: Dict[str, Any], settings: Settings, session: Session) -> str:  # noqa: ARG001
    records = rag_list_documents(session)
    if not records:
        return "知识库当前为空。"
    lines = []
    for record in records:
        lines.append(
            f"- {record.original_name} (ID: {record.id}, 片段: {record.chunk_count})"
        )
    return "知识库文档列表：\n" + "\n".join(lines[:20])


def _handle_search_knowledge(args: Dict[str, Any], settings: Settings, session: Session) -> str:  # noqa: ARG001
    query = args.get("query")
    if not query or not isinstance(query, str):
        raise ToolExecutionError("缺少 query 字段。")
    top_k = args.get("top_k", 3)
    try:
        top_k_int = int(top_k)
    except (TypeError, ValueError):
        top_k_int = 3
    snippets = rag_retrieve_context(query=query, settings=settings, top_k=top_k_int)
    if not snippets:
        return "未在知识库中检索到相关内容。"
    lines = []
    for idx, snippet in enumerate(snippets, start=1):
        name = snippet.original_name or "未知来源"
        lines.append(f"[{idx}] {name}\n{snippet.content}")
    return "检索到以下片段：\n" + "\n\n".join(lines)


def _handle_draw_diagram(args: Dict[str, Any], settings: Settings, session: Session) -> str:  # noqa: ARG001
    filename = args.get("filename")
    diagram_code = args.get("diagram_code")
    diagram_type = args.get("diagram_type", "flowchart")
    
    if not filename or not isinstance(filename, str):
        raise ToolExecutionError("缺少 filename 字段。")
    if not diagram_code or not isinstance(diagram_code, str):
        raise ToolExecutionError("缺少 diagram_code 字段。")
    
    safe_name = _slugify_filename(filename)
    if not safe_name.endswith(".md"):
        safe_name = safe_name.rsplit(".", 1)[0] + ".md" if "." in safe_name else safe_name + ".md"
    
    diagrams_dir = settings.data_dir / "diagrams"
    diagrams_dir.mkdir(parents=True, exist_ok=True)
    target = diagrams_dir / safe_name
    
    # 生成完整的 Markdown 内容
    content = f"""# 结构图：{safe_name.rsplit('.', 1)[0]}

## Mermaid 图表

```mermaid
{diagram_code}
```

---

**说明：**
- 使用支持 Mermaid 的编辑器查看（如 Typora、VS Code、在线编辑器）
- 在线查看：https://mermaid.live/
- 图表类型：{diagram_type}
"""
    
    target.write_text(content, encoding="utf-8")
    return f"已创建结构图文件 {target}，包含 {len(diagram_code)} 字符的 Mermaid 代码。可使用 Typora 或访问 https://mermaid.live/ 查看。"


def _handle_web_search(args: Dict[str, Any], settings: Settings, session: Session) -> str:  # noqa: ARG001
    """网页搜索工具 - 使用 DuckDuckGo"""
    query = args.get("query")
    num_results = args.get("num_results", 5)
    
    if not query or not isinstance(query, str):
        raise ToolExecutionError("缺少 query 字段。")
    
    try:
        num_results = int(num_results)
        if num_results < 1 or num_results > 10:
            num_results = 5
    except (TypeError, ValueError):
        num_results = 5
    
    try:
        # 使用 DuckDuckGo HTML 版本
        url = "https://html.duckduckgo.com/html/"
        params = {"q": query}
        
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.post(url, data=params, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            results = []
            for idx, result in enumerate(soup.select('.result')[:num_results], 1):
                title_elem = result.select_one('.result__a')
                snippet_elem = result.select_one('.result__snippet')
                url_elem = result.select_one('.result__url')
                
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    link = url_elem.get_text(strip=True) if url_elem else "无链接"
                    snippet = snippet_elem.get_text(strip=True) if snippet_elem else "无摘要"
                    
                    results.append(
                        f"[{idx}] {title}\n"
                        f"    🔗 {link}\n"
                        f"    📄 {snippet}"
                    )
            
            if not results:
                return f"❌ 未找到关于 '{query}' 的搜索结果。建议尝试其他关键词。"
            
            return f"🔍 搜索结果（关键词: {query}）：\n\n" + "\n\n".join(results)
            
    except httpx.TimeoutException:
        raise ToolExecutionError("搜索请求超时，请稍后重试。")
    except httpx.HTTPError as e:
        raise ToolExecutionError(f"搜索服务暂时不可用: {str(e)}")
    except Exception as e:
        raise ToolExecutionError(f"搜索失败: {str(e)}")


def _handle_fetch_webpage(args: Dict[str, Any], settings: Settings, session: Session) -> str:  # noqa: ARG001
    """获取网页内容 - 使用 Jina Reader"""
    url = args.get("url")
    
    if not url or not isinstance(url, str):
        raise ToolExecutionError("缺少 url 字段。")
    
    # 验证 URL 格式
    if not url.startswith(("http://", "https://")):
        raise ToolExecutionError("URL 必须以 http:// 或 https:// 开头。")
    
    try:
        # 使用 Jina Reader API - 自动转换为 Markdown
        jina_url = f"https://r.jina.ai/{url}"
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(jina_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "X-Return-Format": "markdown"
            })
            response.raise_for_status()
            
            content = response.text.strip()
            
            # 限制长度避免 token 过多
            max_length = 8000
            if len(content) > max_length:
                content = content[:max_length] + "\n\n...(内容过长，已截断)"
            
            if not content:
                return f"⚠️ 网页 {url} 的内容为空或无法提取。"
            
            return f"📄 网页内容（{url}）：\n\n{content}"
            
    except httpx.TimeoutException:
        raise ToolExecutionError("网页加载超时（30秒），请尝试其他网页或稍后重试。")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ToolExecutionError(f"网页不存在 (404): {url}")
        elif e.response.status_code == 403:
            raise ToolExecutionError(f"网页禁止访问 (403): {url}")
        else:
            raise ToolExecutionError(f"HTTP 错误 ({e.response.status_code}): {url}")
    except httpx.HTTPError as e:
        raise ToolExecutionError(f"网络请求失败: {str(e)}")
    except Exception as e:
        raise ToolExecutionError(f"获取网页内容失败: {str(e)}")


def _get_db_manager(settings: Settings) -> MySQLDatabaseManager:
    """获取数据库管理器实例（单例模式）"""
    # 使用缓存避免重复创建连接
    if not hasattr(_get_db_manager, '_manager'):
        connection_string = (
            f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_password}"
            f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
        )
        _get_db_manager._manager = MySQLDatabaseManager(connection_string)
    return _get_db_manager._manager


def _handle_mysql_list_tables(args: Dict[str, Any], settings: Settings, session: Session) -> str:
    """列出数据库中的所有表"""
    try:
        manager = _get_db_manager(settings)
        tables_info = manager.get_table_with_comments()

        if not tables_info:
            return "数据库中没有表。"

        result = f"数据库 '{settings.mysql_database}' 中共有 {len(tables_info)} 个表：\n\n"
        for i, table_info in enumerate(tables_info, 1):
            table_name = table_info['table_name']
            table_comment = table_info['table_comment']
            description = table_comment if table_comment and not table_comment.isspace() else "(无描述)"
            result += f"{i}. **{table_name}**\n   描述：{description}\n\n"

        return result
    except Exception as e:
        raise ToolExecutionError(f"获取表列表失败: {str(e)}")


def _handle_mysql_get_schema(args: Dict[str, Any], settings: Settings, session: Session) -> str:
    """获取表的详细结构信息"""
    table_names = args.get("table_names")

    if not table_names or not isinstance(table_names, str):
        raise ToolExecutionError("缺少 table_names 字段，应为逗号分隔的表名列表。")

    try:
        manager = _get_db_manager(settings)
        table_list = [name.strip() for name in table_names.split(',') if name.strip()]

        if not table_list:
            raise ToolExecutionError("table_names 不能为空。")

        schema_info = manager.get_table_schema(table_list)

        if not schema_info or schema_info.startswith("获取 Schema 失败"):
            return f"获取表结构失败，请检查表名是否正确：{table_names}"

        return f"表结构信息：\n\n{schema_info}"
    except Exception as e:
        raise ToolExecutionError(f"获取表结构失败: {str(e)}")


def _handle_mysql_query(args: Dict[str, Any], settings: Settings, session: Session) -> str:
    """执行SQL查询"""
    query = args.get("query")

    if not query or not isinstance(query, str):
        raise ToolExecutionError("缺少 query 字段。")

    try:
        manager = _get_db_manager(settings)

        # 验证SQL（可选）
        validation = manager.validate_query(query)
        if "错误" in validation or "失败" in validation:
            return f"⚠️ SQL验证警告：{validation}\n\n如果确认SQL正确，请检查语法。"

        # 执行查询
        result = manager.execute_query(query)

        if not result or result == "查询结果为空":
            return "✅ 查询执行成功，但未返回任何数据。"

        # 尝试解析结果统计
        try:
            import json
            data = json.loads(result)
            count = len(data) if isinstance(data, list) else 0
            return f"✅ 查询成功，返回 {count} 条记录：\n\n```json\n{result}\n```"
        except:
            return f"✅ 查询成功：\n\n{result}"

    except ValueError as e:
        # 安全检查失败
        raise ToolExecutionError(str(e))
    except Exception as e:
        raise ToolExecutionError(f"查询执行失败: {str(e)}")


def _handle_mysql_validate(args: Dict[str, Any], settings: Settings, session: Session) -> str:
    """验证SQL查询语法"""
    query = args.get("query")

    if not query or not isinstance(query, str):
        raise ToolExecutionError("缺少 query 字段。")

    try:
        manager = _get_db_manager(settings)
        result = manager.validate_query(query)
        return result
    except Exception as e:
        raise ToolExecutionError(f"验证失败: {str(e)}")

BUILTIN_TOOLS: Dict[str, BuiltinToolDefinition] = {
    "write_note": BuiltinToolDefinition(
        key="write_note",
        name="写入笔记文件",
        description="在 data/notes 目录下创建或覆盖笔记文件，可用于记录总结或执行结果。",
        input_schema={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "目标文件名，例如 summary.txt",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的文本内容。",
                },
            },
            "required": ["filename", "content"],
        },
        handler=_handle_write_note,
    ),
    "list_knowledge_docs": BuiltinToolDefinition(
        key="list_knowledge_docs",
        name="列出知识库文档",
        description="查看当前知识库中已登记的文档及其片段数量。",
        input_schema={"type": "object", "properties": {}},
        handler=_handle_list_documents,
    ),
    "search_knowledge": BuiltinToolDefinition(
        key="search_knowledge",
        name="知识库关键词检索",
        description="按语义检索知识库片段，返回最相关的几段文本。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要检索的问题或关键词。",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回片段数量（默认 3，最大 10）。",
                },
            },
            "required": ["query"],
        },
        handler=_handle_search_knowledge,
    ),
    "draw_diagram": BuiltinToolDefinition(
        key="draw_diagram",
        name="绘制结构图",
        description="使用 Mermaid 语法绘制流程图、架构图、时序图等结构图，保存为 Markdown 文件。支持 flowchart、sequence、class、state 等多种图表类型。",
        input_schema={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "目标文件名，例如 architecture.md",
                },
                "diagram_code": {
                    "type": "string",
                    "description": "Mermaid 语法的图表代码，例如 'flowchart TD\\n    A[开始] --> B[处理]'",
                },
                "diagram_type": {
                    "type": "string",
                    "description": "图表类型说明（可选），例如 'flowchart'、'sequence'、'class diagram' 等",
                },
            },
            "required": ["filename", "diagram_code"],
        },
        handler=_handle_draw_diagram,
    ),
    "web_search": BuiltinToolDefinition(
        key="web_search",
        name="网页搜索",
        description="在互联网上搜索信息。输入搜索关键词，返回相关网页的标题、链接和摘要。适合查找最新信息、新闻、技术文档等。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题，例如 '2024年人工智能发展趋势'",
                },
                "num_results": {
                    "type": "integer",
                    "description": "返回结果数量（1-10，默认5）",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        handler=_handle_web_search,
    ),
    "fetch_webpage": BuiltinToolDefinition(
        key="fetch_webpage",
        name="获取网页内容",
        description="读取指定网页的完整内容（Markdown格式）。适合深入阅读某个网页的详细信息。注意：会消耗较多 token。",
        input_schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "完整的网页 URL，例如 'https://example.com/article'",
                },
            },
            "required": ["url"],
        },
        handler=_handle_fetch_webpage,
    ),
    # ========== MySQL数据库工具 ==========
    "mysql_list_tables": BuiltinToolDefinition(
        key="mysql_list_tables",
        name="列出数据库表",
        description="列出MySQL数据库中的所有表及其描述信息。适合在开始查询前了解数据库结构。",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=_handle_mysql_list_tables,
    ),
    "mysql_get_schema": BuiltinToolDefinition(
        key="mysql_get_schema",
        name="获取表结构",
        description="获取指定表的详细结构信息，包括列定义、主键、外键、索引等。输入逗号分隔的表名列表。",
        input_schema={
            "type": "object",
            "properties": {
                "table_names": {
                    "type": "string",
                    "description": "逗号分隔的表名列表，例如 'users,orders' 或 'products'",
                },
            },
            "required": ["table_names"],
        },
        handler=_handle_mysql_get_schema,
    ),
    "mysql_query": BuiltinToolDefinition(
        key="mysql_query",
        name="执行SQL查询",
        description="执行MySQL SELECT查询并返回结果（JSON格式）。仅支持SELECT查询。适合数据检索和统计分析。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL SELECT查询语句，例如 'SELECT * FROM users WHERE age > 18 '",
                },
            },
            "required": ["query"],
        },
        handler=_handle_mysql_query,
    ),
    "mysql_validate": BuiltinToolDefinition(
        key="mysql_validate",
        name="验证SQL语法",
        description="在执行前验证SQL查询的语法是否正确。建议在执行复杂查询前先验证。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要验证的SQL查询语句",
                },
            },
            "required": ["query"],
        },
        handler=_handle_mysql_validate,
    ),
}


def list_builtin_options() -> List[Dict[str, Any]]:
    """Return builtin tool descriptors for UI usage."""
    return [
        {
            "key": tool.key,
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in BUILTIN_TOOLS.values()
    ]


def validate_tool_config(tool_type: str, config: Dict[str, Any]) -> None:
    """Validate tool configuration according to type."""
    if tool_type == "builtin":
        builtin_key = config.get("builtin_key")
        if not builtin_key:
            raise HTTPException(status_code=422, detail="builtin 类型必须提供 builtin_key。")
        if builtin_key not in BUILTIN_TOOLS:
            raise HTTPException(status_code=422, detail="未知的 builtin_key。")
    elif tool_type == "http_get":
        base_url = config.get("base_url")
        if not base_url or not isinstance(base_url, str):
            raise HTTPException(status_code=422, detail="http_get 工具需要 base_url。")
    else:
        raise HTTPException(status_code=422, detail=f"暂不支持的工具类型: {tool_type}")


def record_tool_log(
    session: Session,
    tool: ToolRecord,
    arguments: Dict[str, Any],
    result: str | None,
    success: bool,
    error_message: str | None = None,
) -> None:
    """Persist a tool execution log entry."""
    log = ToolExecutionLog(
        id=uuid.uuid4().hex,
        tool_id=tool.id,
        tool_name=tool.name,
        arguments=json.dumps(arguments, ensure_ascii=False),
        result_preview=(result or "")[:500],
        success=success,
        error_message=error_message,
    )
    session.add(log)
    session.commit()


def execute_tool(
    tool: ToolRecord,
    arguments: Dict[str, Any],
    settings: Settings,
    session: Session,
) -> str:
    """Execute a tool and log the outcome."""
    config = json.loads(tool.config)
    arguments = arguments or {}
    if tool.tool_type == "builtin":
        builtin_key = config["builtin_key"]
        definition = BUILTIN_TOOLS[builtin_key]
        try:
            result = definition.handler(arguments, settings, session)
            record_tool_log(session, tool, arguments, result, success=True)
            return result
        except ToolExecutionError as error:
            record_tool_log(
                session, tool, arguments, result=None, success=False, error_message=str(error)
            )
            raise HTTPException(status_code=400, detail=str(error)) from error
    elif tool.tool_type == "http_get":
        base_url = config["base_url"].rstrip("/")
        path = arguments.get("path", "")
        params = arguments.get("params")
        if params is not None and not isinstance(params, dict):
            raise HTTPException(status_code=422, detail="params 必须是对象。")
        url = f"{base_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, params=params)
            response.raise_for_status()
            text = response.text[:1000]
            record_tool_log(session, tool, arguments, text, success=True)
            return f"GET {url} 成功（HTTP {response.status_code}）：\n{text}"
        except httpx.HTTPError as error:
            record_tool_log(
                session,
                tool,
                arguments,
                result=None,
                success=False,
                error_message=str(error),
            )
            raise HTTPException(status_code=502, detail=f"HTTP 工具调用失败：{error}") from error
    else:
        raise HTTPException(status_code=422, detail=f"未知工具类型：{tool.tool_type}")


def build_tool_prompt(tool_records: List[ToolRecord]) -> str:
    """Assemble a natural language instruction describing available tools."""
    lines = [
        "你可以使用以下 MCP 工具。需要调用时，请输出：",
        "<tool_call>{\"tool_id\": \"工具ID\", \"arguments\": {键值对}}</tool_call>",
        "如果无需调用，请直接回答用户问题。",
        "",
    ]
    for record in tool_records:
        config = json.loads(record.config)
        schema_desc = ""
        if record.tool_type == "builtin":
            builtin = BUILTIN_TOOLS.get(config.get("builtin_key", ""))
            if builtin:
                schema_desc = json.dumps(builtin.input_schema, ensure_ascii=False)
        elif record.tool_type == "http_get":
            schema_desc = json.dumps(
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "追加在 base_url 之后的路径"},
                        "params": {"type": "object", "description": "可选的查询参数对象"},
                    },
                },
                ensure_ascii=False,
            )
        lines.append(
            f"- 工具ID: {record.id}\n  名称: {record.name}\n  类型: {record.tool_type}\n"
            f"  描述: {record.description}\n  参数Schema: {schema_desc}"
        )
    return "\n".join(lines)


def parse_tool_call(response_text: str) -> Dict[str, Any] | None:
    """Extract tool call JSON payload from model response."""
    match = re.search(r"<tool_call>(.*?)</tool_call>", response_text, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1).strip())
        if not isinstance(payload, dict):
            return None
        return payload
    except json.JSONDecodeError:
        return None


def load_tool_config(tool: ToolRecord) -> Dict[str, Any]:
    """Return the JSON config for a tool."""
    return json.loads(tool.config)
