# 政采公告市场分析 API（:8010）

从 `zc_wlsjcj_cjgg.sql`（采购公告）与 `zc_wlsjcj_cjs.sql`（成交结果）导入约 1.7 万条记录，
为第9章的市场供给分析、分位数定额与需求调查报告提供数据服务。

```bash
npm install
npm run import:market -- --cjgg /path/to/zc_wlsjcj_cjgg.sql --cjs /path/to/zc_wlsjcj_cjs.sql
npm run dev
```

完整端点说明见 `MARKET_MODULE.md`。数据文件未随仓库发布，请自行准备脱敏数据。
