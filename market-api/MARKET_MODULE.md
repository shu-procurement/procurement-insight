# 市场分析模块

基于上海政府采购网历史公告的 **SQLite 样本库**，提供公告浏览、筛选与 AI 市场趋势报告。

> 默认导入 1000 条公告样本；全量约 1.7 万条。统计结果不代表全量上海采购市场。

## 快速开始

### 1. 导入数据

默认读取桌面 SQL 文件，也可通过 CLI 或环境变量指定路径：

```bash
# 默认 1000 条样本
npm run import:market

# 自定义条数
npm run import:market -- --limit 500

# 全量导入（约 1.7 万公告，SQLite ~50MB，首次需数分钟）
npm run import:market -- --limit 0

# 自定义 SQL 路径
npm run import:market -- --cjgg /path/to/zc_wlsjcj_cjgg.sql --cjs /path/to/zc_wlsjcj_cjs.sql
```

环境变量（可选，见 `.env.example`）：

- `PROCUREMENT_CJGG` — 公告 SQL 路径
- `PROCUREMENT_CJS` — 成交 SQL 路径

生成 `data/procurement.sqlite`（已 gitignore）。

### 2. 启动服务

**方式 A — 同时启动前端 + 市场 API：**

```bash
npm run dev:all
```

**方式 B — 分别启动：**

```bash
npm run market:api   # http://127.0.0.1:8010
npm run dev          # http://127.0.0.1:5173
```

### 3. 使用

1. 打开首页，切换到 **市场分析** Tab
2. **公告浏览**：关键词（含搜索建议与本地历史）、31 省地区、时间、金额区间筛选；点击查看详情与成交明细
3. **AI 报告**：输入关键词，生成 Markdown 市场趋势分析（报告存 localStorage）

## API 端点（`/api/market` 代理）

| 路径 | 说明 |
|------|------|
| `GET /announcements` | 分页列表（`search` `region` `time` `amount`） |
| `GET /announcements/:wid` | 详情 + 成交 |
| `GET /announcements/suggest` | 搜索建议 |
| `GET /stats/cards` | 统计卡片 |
| `GET /stats/regions` | 地区分布 |
| `GET /stats/top-buyers` | Top 采购单位 |
| `GET /stats/by-keywords` | 关键词 scoped 列表 |

## 与 Flask 审核功能的关系

Flask 招标智能审核系统的核心能力已改写为 TypeScript 并接入采购全流程：

- **招标文件识别** → `StageTenderDoc` → 识别已有文件 Tab（含八项评分标准提取）
- **四块合规审核** → `StageReview`（review 阶段）
- **围标串标分析** → `StageBidReview` 串标 Tab
- **八维度快速评分** → `StageEvaluation` 快速评分 Tab
- **合同上传审核** → `StageContract` 上传合同审核 Tab

工作流顺序：`demand → … → tenderDoc → review → announce → … → award → contract → inquiry → …`
