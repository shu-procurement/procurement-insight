# 第 9 章 · 可运行示例

### 1. 需求调查报告自动生成

```bash
curl -X POST http://localhost:8001/chat/multi-agent/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "生成某实验设备的市场需求调查报告", "session_id": "demo"}'
```

### 2. 市场供给分析 API

```bash
cd market-api && npm install && npm run dev      # :8010
curl "http://localhost:8010/api/market/overview?keyword=显微镜"
```

### 3. 评测脚本

```bash
cd evaluation && python run_metrics.py
```


> 请把 `samples/` 中的示例文件替换为自己的测试数据；示例数据不含任何真实业务信息。
