# procurement-insight · 数据知识服务与预算赋能

> 《协同采购：人工智能时代政府采购治理变革》**第 9 章**配套开源项目。
> 五章对应五个独立仓库，本仓库聚焦「数据知识服务与预算赋能」场景，clone 后即可按下方步骤复现该章实践案例。

多智能体市场供给分析与需求调查报告自动生成系统；LangGraph「规划器—执行器—汇总器」+ 共享工作空间、MySQL 专家 Text-to-SQL 安全校验，配套 1.7 万条政采公告市场分析 API。

- **技术栈**：Python 3.9+ / Django / FastAPI / LangGraph / MySQL；市场 API 为 Node.js
- **服务端口**：8000 / 8001（Django + FastAPI）、8010（市场分析 API）
- **许可证**：MIT（见 `LICENSE`）

## 场景能力

1. 零基预算与成本预算绩效「问核控评」全链嵌入的数据支撑
2. 分位数法、参数化与作业成本法生成支出定额标准
3. 规划器—执行器—汇总器编排与 SharedWorkspace 共享工作空间
4. 检索、MySQL、分析、总结、校验五类专家智能体协作
5. Text-to-SQL 只读安全校验、历史报告复用与「一屏三域」驾驶舱

## 快速开始

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt -r frontend/requirements.txt
cp .env.example .env                       # 含 MYSQL_* 与 DEEPSEEK_API_KEY
cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
cd frontend && python manage.py runserver 8000
# 可选市场分析 API：cd market-api && npm install && npm run dev（:8010）
```

> 所有 API 密钥、数据库口令与签名密钥均通过 `.env` 注入，源码不含真实凭据。
> 复制 `.env.example` 为 `.env` 后填写；`.env` 已被 `.gitignore` 排除，详见 `SECURITY.md`。
>
> **密钥配置（部署前必读）**：完整申请入口、字段表与校验方法见 [docs/密钥配置指南.md](docs/密钥配置指南.md)；
> 复制模板填值后运行 `python3 scripts/check_env.py` 校验，返回 `[OK]` 再启动服务。
> 绝不把 `.env` 提交到 Git，也不要把密钥回填进源码，详见 `SECURITY.md`。

## 本章核心模块

| 路径 | 作用 |
|---|---|
| `backend/app/multi_agent.py` | LangGraph 多智能体协调器 |
| `backend/app/agent_roles.py` | 五类专家智能体定义 |
| `backend/app/shared_workspace.py` | 共享工作空间与状态传递 |
| `backend/app/mysql/mysql_manager.py` | Text-to-SQL 安全校验与只读查询 |
| `market-api/server/market-api.ts` | 政采公告市场分析 API（:8010） |
| `market-api/scripts/import-procurement-sqlite.ts` | 公告 SQL 导入 SQLite |

完整流程、接口参数与演练步骤见 `docs/场景指南.md`；可直接运行的调用示例见 `examples/`。

## 完整部署文档

- `docs/场景指南.md`：本章场景的操作流程、接口示例与验证点
- `docs/`：安装说明、架构说明、规则清单与系统截图说明
- 原系统架构文档位于 `docs/ARCHITECTURE.md`（若适用）

## 安全与数据

请勿把 `.env`、运行日志、业务数据库或含真实供应商信息的文件提交到公开仓库。
涉及合同、发票、投标文件的运行数据应置于校内网络或本地环境。

---

*本项目由本书团队以 MIT 许可证公开发布，欢迎 Issue 与 Pull Request。*
