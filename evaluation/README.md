# Evaluation Toolkit

这个目录用于测试 3 个指标：

- 平均响应时间
- 搜索 Recall@10
- 幻觉率

## 运行前提

先启动项目服务：

- Django: `http://127.0.0.1:8000`
- FastAPI: `http://127.0.0.1:8001`

## 运行方式

在项目根目录执行：

```powershell
python evaluation/run_metrics.py --rounds 10
```

如果你想换测试集：

```powershell
python evaluation/run_metrics.py --cases evaluation/cases/sample_cases.json --rounds 10
```

## 输出文件

默认输出到 `evaluation/output/`：

- `metrics_report.json`
- `metrics_runs.csv`
- `metrics_report.html`
- `response_time_chart.svg`
- `recall_at_10_chart.svg`
- `hallucination_rate_chart.svg`

## 幻觉率说明

当前实现是“字段落地核对”：

- 让多智能体接口按 JSON 返回固定字段
- 用接口返回的 `mysql_data` 字段集合做支撑性校验
- 若回答字段不在 `mysql_data` 对应数据中，记为不受支持字段

这个版本适合课程设计、答辩和小规模实验。  
如果你后面要做论文级评测，可以再扩展成：

- 文本级 claim 抽取
- 证据句对齐
- LLM-as-a-judge 二次判分
