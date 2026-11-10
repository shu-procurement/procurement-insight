import argparse
import csv
import html
import json
import math
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CASES_FILE = BASE_DIR / "cases" / "sample_cases.json"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"


@dataclass
class SearchCase:
    name: str
    query: str
    relevant_keywords: List[str]


@dataclass
class HallucinationCase:
    name: str
    prompt: str
    answer_type: str
    required_fields: List[str]
    selected_keywords: List[str]


def load_cases(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def median(values: List[float]) -> float:
    return statistics.median(values) if values else 0.0


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[int(rank)]
    weight = rank - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "report"


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def normalize_text(text: str) -> str:
    clean = strip_tags(text)
    clean = clean.replace("\u3000", " ")
    clean = re.sub(r"\s+", " ", clean)
    return clean.lower().strip()


def contains_any_keyword(text: str, keywords: List[str]) -> bool:
    normalized = normalize_text(text)
    return any(keyword.lower().strip() in normalized for keyword in keywords if keyword.strip())


def extract_search_titles(html_text: str) -> List[str]:
    titles = re.findall(r'<h3 class="card-title"[^>]*>.*?(?:<a [^>]*>)?([^<]+)', html_text, flags=re.S)
    cleaned = []
    for title in titles:
        text = html.unescape(strip_tags(title)).strip()
        if text:
            cleaned.append(text)
    return cleaned


def extract_search_total_count(html_text: str) -> Optional[int]:
    patterns = [
        r"共匹配到\s*<strong>(\d+)</strong>",
        r"共找到\s*<strong>(\d+)</strong>",
        r"共\s*(\d+)\s*条采购公告",
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def compute_recall_at_k(retrieved_titles: List[str], relevant_keywords: List[str], k: int = 10) -> Tuple[float, int]:
    top_k = retrieved_titles[:k]
    hits = sum(1 for title in top_k if contains_any_keyword(title, relevant_keywords))
    relevant_total = max(len(relevant_keywords), 1)
    recall = hits / relevant_total
    return min(recall, 1.0), hits


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    retries: int = 4,
    retry_delay_seconds: float = 2.0,
    **kwargs: Any,
) -> httpx.Response:
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code not in {429, 502, 503, 504}:
                return response
            last_error = httpx.HTTPStatusError(
                f"Transient server status {response.status_code} for {url}",
                request=response.request,
                response=response,
            )
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_error = exc

        if attempt < retries:
            time.sleep(retry_delay_seconds)

    if isinstance(last_error, httpx.HTTPStatusError):
        raise last_error
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Request failed unexpectedly: {method} {url}")


def coerce_json_payload(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def score_hallucination(answer_data: Dict[str, Any], mysql_data: List[Dict[str, Any]], required_fields: List[str]) -> Dict[str, Any]:
    mysql_fields = set()
    for row in mysql_data or []:
        mysql_fields.update(str(key).strip() for key in row.keys())

    answer_keys = set(str(key).strip() for key in answer_data.keys())
    supported = []
    unsupported = []

    for field in required_fields:
        if field in answer_keys and field in mysql_fields:
            supported.append(field)
        else:
            unsupported.append(field)

    hallucination_rate = len(unsupported) / max(len(required_fields), 1)
    grounded_rate = len(supported) / max(len(required_fields), 1)
    return {
        "supported_fields": supported,
        "unsupported_fields": unsupported,
        "grounded_rate": grounded_rate,
        "hallucination_rate": hallucination_rate,
        "mysql_fields": sorted(mysql_fields),
    }


def build_hallucination_instruction(case: HallucinationCase) -> str:
    fields_text = ", ".join(case.required_fields)
    return (
        f"{case.prompt}\n\n"
        f"请只根据数据库查到的内容回答，并严格输出 JSON。"
        f" JSON 中必须包含这些字段：{fields_text}。"
        f" 如果某个字段无法从数据中确定，请填 null，不要编造。"
    )


def run_response_time_tests(client: httpx.Client, django_base_url: str, fastapi_base_url: str, response_cases: List[Dict[str, Any]], rounds: int) -> List[Dict[str, Any]]:
    results = []
    for case in response_cases:
        name = case["name"]
        target = case["target"]
        method = str(case.get("method", "GET")).upper()
        path = case["path"]
        params = case.get("params", {})
        json_body = case.get("json")
        repeat = int(case.get("repeat", rounds))

        if target == "django":
            base_url = django_base_url.rstrip("/")
        elif target == "fastapi":
            base_url = fastapi_base_url.rstrip("/")
        else:
            raise ValueError(f"Unsupported target: {target}")

        url = f"{base_url}{path}"

        for run_index in range(1, repeat + 1):
            start = time.perf_counter()
            response = request_with_retry(
                client,
                method,
                url,
                params=params,
                json=json_body,
                timeout=120.0,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            results.append(
                {
                    "metric": "response_time",
                    "case_name": name,
                    "target": target,
                    "run_index": run_index,
                    "status_code": response.status_code,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "ok": response.is_success,
                }
            )
    return results


def run_search_recall_tests(client: httpx.Client, django_base_url: str, search_cases: List[SearchCase], rounds: int) -> List[Dict[str, Any]]:
    results = []
    base_url = django_base_url.rstrip("/")
    for case in search_cases:
        for run_index in range(1, rounds + 1):
            url = f"{base_url}/announcements/?{urlencode({'search': case.query})}"
            start = time.perf_counter()
            response = request_with_retry(client, "GET", url, timeout=120.0)
            elapsed_ms = (time.perf_counter() - start) * 1000
            response.raise_for_status()
            html_text = response.text
            titles = extract_search_titles(html_text)
            recall_at_10, hits = compute_recall_at_k(titles, case.relevant_keywords, k=10)
            total_count = extract_search_total_count(html_text)
            results.append(
                {
                    "metric": "recall_at_10",
                    "case_name": case.name,
                    "query": case.query,
                    "run_index": run_index,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "retrieved_titles": titles[:10],
                    "hits": hits,
                    "relevant_total": len(case.relevant_keywords),
                    "recall_at_10": round(recall_at_10, 4),
                    "total_count": total_count,
                }
            )
    return results


def run_hallucination_tests(client: httpx.Client, fastapi_base_url: str, hallucination_cases: List[HallucinationCase], rounds: int) -> List[Dict[str, Any]]:
    results = []
    base_url = fastapi_base_url.rstrip("/")
    for case in hallucination_cases:
        prompt = build_hallucination_instruction(case)
        for run_index in range(1, rounds + 1):
            start = time.perf_counter()
            response = request_with_retry(
                client,
                "POST",
                f"{base_url}/chat/multi-agent",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "selected_keywords": case.selected_keywords,
                    "use_knowledge_base": True,
                    "use_tools": True,
                    "execution_mode": "sequential",
                },
                timeout=180.0,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            response.raise_for_status()
            payload = response.json()
            answer_text = payload.get("reply", "")
            answer_data = coerce_json_payload(answer_text) or {}
            mysql_data = payload.get("mysql_data", []) or []
            score = score_hallucination(answer_data, mysql_data, case.required_fields)
            results.append(
                {
                    "metric": "hallucination_rate",
                    "case_name": case.name,
                    "prompt": case.prompt,
                    "run_index": run_index,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "quality_score": payload.get("quality_score"),
                    "required_fields": case.required_fields,
                    "answer_data": answer_data,
                    "mysql_data_count": len(mysql_data),
                    "supported_fields": score["supported_fields"],
                    "unsupported_fields": score["unsupported_fields"],
                    "grounded_rate": round(score["grounded_rate"], 4),
                    "hallucination_rate": round(score["hallucination_rate"], 4),
                    "mysql_fields": score["mysql_fields"],
                }
            )
    return results


def summarize_response_time(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[float]] = {}
    for item in results:
        grouped.setdefault(item["case_name"], []).append(item["elapsed_ms"])

    summaries = []
    for case_name, values in grouped.items():
        summaries.append(
            {
                "metric": "response_time",
                "case_name": case_name,
                "avg_ms": round(sum(values) / len(values), 2),
                "median_ms": round(median(values), 2),
                "p95_ms": round(percentile(values, 0.95), 2),
                "min_ms": round(min(values), 2),
                "max_ms": round(max(values), 2),
                "sample_count": len(values),
            }
        )
    return summaries


def summarize_recall(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[float]] = {}
    for item in results:
        grouped.setdefault(item["case_name"], []).append(item["recall_at_10"])

    summaries = []
    for case_name, values in grouped.items():
        summaries.append(
            {
                "metric": "recall_at_10",
                "case_name": case_name,
                "avg_recall_at_10": round(sum(values) / len(values), 4),
                "median_recall_at_10": round(median(values), 4),
                "min_recall_at_10": round(min(values), 4),
                "max_recall_at_10": round(max(values), 4),
                "sample_count": len(values),
            }
        )
    return summaries


def summarize_hallucination(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[float]] = {}
    for item in results:
        grouped.setdefault(item["case_name"], []).append(item["hallucination_rate"])

    summaries = []
    for case_name, values in grouped.items():
        summaries.append(
            {
                "metric": "hallucination_rate",
                "case_name": case_name,
                "avg_hallucination_rate": round(sum(values) / len(values), 4),
                "median_hallucination_rate": round(median(values), 4),
                "min_hallucination_rate": round(min(values), 4),
                "max_hallucination_rate": round(max(values), 4),
                "sample_count": len(values),
            }
        )
    return summaries


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write("")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def svg_bar_chart(title: str, labels: List[str], values: List[float], color: str, max_value: Optional[float] = None, suffix: str = "") -> str:
    width = 860
    height = 340
    left = 160
    top = 40
    chart_width = 640
    bar_height = 28
    gap = 16
    max_value = max_value if max_value is not None else (max(values) if values else 1.0)
    max_value = max(max_value, 1e-9)
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="24" y="28" font-size="20" font-family="Arial" fill="#111827">{html.escape(title)}</text>',
    ]
    for idx, (label, value) in enumerate(zip(labels, values)):
        y = top + idx * (bar_height + gap)
        bar_width = (value / max_value) * chart_width
        svg_parts.append(f'<text x="24" y="{y + 19}" font-size="13" font-family="Arial" fill="#374151">{html.escape(label)}</text>')
        svg_parts.append(f'<rect x="{left}" y="{y}" width="{chart_width}" height="{bar_height}" rx="6" fill="#E5E7EB"/>')
        svg_parts.append(f'<rect x="{left}" y="{y}" width="{bar_width:.2f}" height="{bar_height}" rx="6" fill="{color}"/>')
        svg_parts.append(f'<text x="{left + chart_width + 10}" y="{y + 19}" font-size="13" font-family="Arial" fill="#111827">{value:.4f}{suffix}</text>')
    svg_parts.append("</svg>")
    return "".join(svg_parts)


def write_svg(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(content)


def render_html_report(
    output_path: Path,
    response_summary: List[Dict[str, Any]],
    recall_summary: List[Dict[str, Any]],
    hallucination_summary: List[Dict[str, Any]],
    response_chart_file: str,
    recall_chart_file: str,
    hallucination_chart_file: str,
) -> None:
    def rows_html(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "<p>No data.</p>"
        headers = sorted({key for row in rows for key in row.keys()})
        table = ["<table><thead><tr>"]
        table.extend(f"<th>{html.escape(h)}</th>" for h in headers)
        table.append("</tr></thead><tbody>")
        for row in rows:
            table.append("<tr>")
            for header in headers:
                table.append(f"<td>{html.escape(str(row.get(header, '')))}</td>")
            table.append("</tr>")
        table.append("</tbody></table>")
        return "".join(table)

    html_text = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Procurement System Metrics Report</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 24px;
      color: #111827;
      background: #F9FAFB;
    }}
    h1, h2 {{
      margin: 0 0 12px 0;
    }}
    .section {{
      background: #ffffff;
      border: 1px solid #E5E7EB;
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 20px;
    }}
    img {{
      max-width: 100%;
      border: 1px solid #E5E7EB;
      border-radius: 8px;
      background: white;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 14px;
    }}
    th, td {{
      border: 1px solid #E5E7EB;
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #F3F4F6;
    }}
  </style>
</head>
<body>
  <h1>采购系统评测报告</h1>

  <div class="section">
    <h2>平均响应时间</h2>
    <img src="{html.escape(response_chart_file)}" alt="平均响应时间图表">
    {rows_html(response_summary)}
  </div>

  <div class="section">
    <h2>Search Recall@10</h2>
    <img src="{html.escape(recall_chart_file)}" alt="Recall@10 图表">
    {rows_html(recall_summary)}
  </div>

  <div class="section">
    <h2>幻觉率</h2>
    <img src="{html.escape(hallucination_chart_file)}" alt="幻觉率图表">
    {rows_html(hallucination_summary)}
  </div>
</body>
</html>
"""
    output_path.write_text(html_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run procurement system metrics and generate charts.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_FILE, help="Path to JSON case file.")
    parser.add_argument("--django-base-url", default="http://127.0.0.1:8000", help="Django base URL.")
    parser.add_argument("--fastapi-base-url", default="http://127.0.0.1:8001", help="FastAPI base URL.")
    parser.add_argument("--rounds", type=int, default=10, help="Default number of runs per case.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory.")
    args = parser.parse_args()

    cases_data = load_cases(args.cases)
    ensure_output_dir(args.output_dir)

    search_cases = [SearchCase(**case) for case in cases_data.get("search_cases", [])]
    hallucination_cases = [HallucinationCase(**case) for case in cases_data.get("hallucination_cases", [])]
    response_cases = cases_data.get("response_time_cases", [])

    try:
        with httpx.Client(follow_redirects=True) as client:
            response_results = run_response_time_tests(
                client=client,
                django_base_url=args.django_base_url,
                fastapi_base_url=args.fastapi_base_url,
                response_cases=response_cases,
                rounds=args.rounds,
            )
            search_results = run_search_recall_tests(
                client=client,
                django_base_url=args.django_base_url,
                search_cases=search_cases,
                rounds=args.rounds,
            )
            hallucination_results = run_hallucination_tests(
                client=client,
                fastapi_base_url=args.fastapi_base_url,
                hallucination_cases=hallucination_cases,
                rounds=args.rounds,
            )
    except httpx.HTTPError as exc:
        print(f"HTTP request failed: {exc}", file=sys.stderr)
        return 1

    response_summary = summarize_response_time(response_results)
    recall_summary = summarize_recall(search_results)
    hallucination_summary = summarize_hallucination(hallucination_results)

    raw_report = {
        "response_time_results": response_results,
        "response_time_summary": response_summary,
        "search_recall_results": search_results,
        "search_recall_summary": recall_summary,
        "hallucination_results": hallucination_results,
        "hallucination_summary": hallucination_summary,
    }

    json_path = args.output_dir / "metrics_report.json"
    write_json(json_path, raw_report)

    flat_rows = response_results + search_results + hallucination_results
    csv_path = args.output_dir / "metrics_runs.csv"
    write_csv(csv_path, flat_rows)

    response_labels = [item["case_name"] for item in response_summary]
    response_values = [item["avg_ms"] for item in response_summary]
    recall_labels = [item["case_name"] for item in recall_summary]
    recall_values = [item["avg_recall_at_10"] for item in recall_summary]
    hallucination_labels = [item["case_name"] for item in hallucination_summary]
    hallucination_values = [item["avg_hallucination_rate"] for item in hallucination_summary]

    response_svg_name = "response_time_chart.svg"
    recall_svg_name = "recall_at_10_chart.svg"
    hallucination_svg_name = "hallucination_rate_chart.svg"

    write_svg(
        args.output_dir / response_svg_name,
        svg_bar_chart("Average Response Time (ms)", response_labels, response_values, "#2563EB"),
    )
    write_svg(
        args.output_dir / recall_svg_name,
        svg_bar_chart("Average Recall@10", recall_labels, recall_values, "#059669", max_value=1.0),
    )
    write_svg(
        args.output_dir / hallucination_svg_name,
        svg_bar_chart("Average Hallucination Rate", hallucination_labels, hallucination_values, "#DC2626", max_value=1.0),
    )

    html_report_path = args.output_dir / "metrics_report.html"
    render_html_report(
        output_path=html_report_path,
        response_summary=response_summary,
        recall_summary=recall_summary,
        hallucination_summary=hallucination_summary,
        response_chart_file=response_svg_name,
        recall_chart_file=recall_svg_name,
        hallucination_chart_file=hallucination_svg_name,
    )

    print(f"Saved JSON report: {json_path}")
    print(f"Saved CSV runs: {csv_path}")
    print(f"Saved HTML report: {html_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
