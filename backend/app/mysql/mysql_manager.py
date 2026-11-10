import json
from typing import List, Optional
import pymysql
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import row
from sqlalchemy.exc import SQLAlchemyError
import logging
log = logging.getLogger(__name__)

import json
from datetime import datetime, date, timedelta
from decimal import Decimal

# 1. 在文件顶部增加一个自定义的 JSON 编码器类
class DBJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, timedelta):
            return str(obj)  # 将 timedelta 转换为字符串，如 "1:30:00"
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

class MySQLDatabaseManager:
    """MySQL数据库管理器，负责数据库连接和基本操作"""
    def __init__(self,connection_string:str) :
        """初始化Mysql数据库连接
        Args:
            connection_string: Mysql连接字符串，格式为
                mysql+pymysql://user:password@host:port/database

        """
        self.engine=create_engine(connection_string,pool_size=5,pool_recycle=3600)
    def get_table_names(self) -> list[str]:
        try:
            inspector =inspect(self.engine)
            return inspector.get_table_names()
        except SQLAlchemyError as e:
            log.exception(e)
            raise ValueError(f"获取表名失败：{str(e)}")
    def get_table_with_comments(self) -> List[dict]:
        try:
            query =text("""
                SELECT TABLE_NAME,TABLE_COMMENT
                FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_TYPE = 'BASE TABLE'
                    AND TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME
                        """)
            with self.engine.connect() as connection:
                result =connection.execute(query)
                tables_info = [{'table_name':row[0],'table_comment':row[1]} for row in result]
                return tables_info
        except SQLAlchemyError as e:
            log.exception(e)
            raise ValueError(f"获取表面及其描述信息失败{str(e)}")

    def get_table_schema(self, table_names: Optional[List[str]] = None) -> str:
        try:
            inspector = inspect(self.engine)
            schema_info = []

            # 如果没有指定表名，则获取所有表
            tables_to_process = table_names if table_names else inspector.get_table_names()

            for table_name in tables_to_process:
                # 1. 获取基础元数据
                columns = inspector.get_columns(table_name)
                pk_constraint = inspector.get_pk_constraint(table_name)
                primary_keys = pk_constraint['constrained_columns'] if pk_constraint else []
                foreign_keys = inspector.get_foreign_keys(table_name)
                indexes = inspector.get_indexes(table_name)

                # 2. 获取表本身的注释
                table_comment = inspector.get_table_comment(table_name)
                t_comment = table_comment.get('text') if table_comment else "无表注释"

                # 3. 构造表头
                table_schema = [f"### 表名: {table_name} ({t_comment})"]
                table_schema.append("列信息:")

                # 4. 遍历列信息
                for column in columns:
                    pk_indicator = " [主键]" if column['name'] in primary_keys else ""
                    comment = column.get('comment') or '无注释'
                    col_type = str(column['type'])
                    table_schema.append(f"  - {column['name']} ({col_type}){pk_indicator} | 注释：{comment}")

                # 5. 补全外键逻辑
                if foreign_keys:
                    table_schema.append("外键约束:")
                    for fk in foreign_keys:
                        # 格式：[本地列] -> 目标表.目标列
                        constrained_cols = ", ".join(fk['constrained_columns'])
                        referred_table = fk['referred_table']
                        referred_cols = ", ".join(fk['referred_columns'])
                        table_schema.append(f"  - {constrained_cols} -> {referred_table}.({referred_cols})")

                # 6. 补全索引逻辑 (可选，有助于 AI 优化复杂查询)
                if indexes:
                    table_schema.append("索引信息:")
                    for idx in indexes:
                        unique = " [唯一]" if idx.get('unique') else ""
                        idx_cols = ", ".join(idx['column_names'])
                        table_schema.append(f"  - {idx['name']}: ({idx_cols}){unique}")

                # 将单个表的信息汇总
                schema_info.append("\n".join(table_schema))

            return "\n\n---\n\n".join(schema_info)

        except Exception as e:
            # 使用你之前定义的日志工具
            if hasattr(self, 'logger'):
                self.logger.error(f"解析数据库 Schema 失败: {str(e)}")
            return f"获取 Schema 失败: {str(e)}"
    def execute_query(self,query:str) ->str:
        forbidden_columns = ['insert','update','delete','drop','alter','create','grant','truncate']
        query_lower=query.lower().strip()
        if not query_lower.startswith(('select','with')) and any(
            keyword in query_lower for keyword in forbidden_columns):
            raise ValueError("出于安全目的考虑，只允许执行select查询和with查询")
        try:
            with self.engine.connect() as connection:
                result =connection.execute(text(query))
                columns=result.keys()
                rows = result.fetchmany(100)
                if not rows:
                    return "查询结果为空"
                result_data=[]
                for row in rows:
                    row_dict={}
                    for i,col in enumerate(columns):
                        try:
                            if row[i] is not None:
                                json.dumps(row[i])
                            row_dict[col]=row[i]
                        except(TypeError, ValueError):
                            row_dict[col]=row[i]
                    result_data.append(row_dict)
                return json.dumps(result_data, ensure_ascii=False, indent=2, cls=DBJSONEncoder)
        except SQLAlchemyError as e:
            log.exception(e)
            raise ValueError(f"SQL执行错误{str(e)}")
    def validate_query(self, query:str) ->str:
        if not query or not query.strip():
            return "错误：查询不能为空"
        query_lower= query.lower().strip()
        if not query_lower.startswith(('select','with')):
            return "警告：建议使用select或with查询，其他操作可能被限制"
        try:
            with self.engine.connect() as connection:
                if self.engine.dialect.name == 'mysql':
                    explain_query=text(f"EXPLAIN {query}")
                else:
                    explain_query=text(f"EXPLAIN {query}")
                connection.execute(explain_query)
                return "SQL查询语法正确(已通过EXPLAIN验证)"
        except  Exception as e:
            log.exception(e)
            return f"SQL语法错误: {str(e)}"

