import json
import re
import os
import sys
from io import BytesIO
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import pymysql
from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.paginator import Paginator
from django.core.files.storage import FileSystemStorage
from django.db import OperationalError
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import HistoricalProject, OngoingProject, ReportIndexPage, ReportPage


_PROCUREMENT_REGIONS = frozenset(
    [
        "全国",
        "北京",
        "天津",
        "河北",
        "山西",
        "内蒙古",
        "辽宁",
        "吉林",
        "黑龙江",
        "上海",
        "江苏",
        "浙江",
        "安徽",
        "福建",
        "江西",
        "山东",
        "河南",
        "湖北",
        "湖南",
        "广东",
        "广西",
        "海南",
        "重庆",
        "四川",
        "贵州",
        "云南",
        "西藏",
        "陕西",
        "甘肃",
        "青海",
        "宁夏",
        "新疆",
        "香港",
        "澳门",
        "台湾",
    ]
)

_PROVINCE_NAMES = (
    "\u5317\u4eac",
    "\u5929\u6d25",
    "\u6cb3\u5317",
    "\u5c71\u897f",
    "\u5185\u8499\u53e4",
    "\u8fbd\u5b81",
    "\u5409\u6797",
    "\u9ed1\u9f99\u6c5f",
    "\u4e0a\u6d77",
    "\u6c5f\u82cf",
    "\u6d59\u6c5f",
    "\u5b89\u5fbd",
    "\u798f\u5efa",
    "\u6c5f\u897f",
    "\u5c71\u4e1c",
    "\u6cb3\u5357",
    "\u6e56\u5317",
    "\u6e56\u5357",
    "\u5e7f\u4e1c",
    "\u5e7f\u897f",
    "\u6d77\u5357",
    "\u91cd\u5e86",
    "\u56db\u5ddd",
    "\u8d35\u5dde",
    "\u4e91\u5357",
    "\u897f\u85cf",
    "\u9655\u897f",
    "\u7518\u8083",
    "\u9752\u6d77",
    "\u5b81\u590f",
    "\u65b0\u7586",
    "\u9999\u6e2f",
    "\u6fb3\u95e8",
    "\u53f0\u6e7e",
)

_PROVINCE_ALIAS = {
    "\u5168\u56fd": "\u5168\u56fd",
    "\u4e2d\u56fd": "\u5168\u56fd",
    "\u5317\u4eac": "\u5317\u4eac",
    "\u5317\u4eac\u5e02": "\u5317\u4eac",
    "\u5929\u6d25": "\u5929\u6d25",
    "\u5929\u6d25\u5e02": "\u5929\u6d25",
    "\u4e0a\u6d77": "\u4e0a\u6d77",
    "\u4e0a\u6d77\u5e02": "\u4e0a\u6d77",
    "\u91cd\u5e86": "\u91cd\u5e86",
    "\u91cd\u5e86\u5e02": "\u91cd\u5e86",
    "\u6cb3\u5317": "\u6cb3\u5317",
    "\u6cb3\u5317\u7701": "\u6cb3\u5317",
    "\u5c71\u897f": "\u5c71\u897f",
    "\u5c71\u897f\u7701": "\u5c71\u897f",
    "\u5185\u8499\u53e4": "\u5185\u8499\u53e4",
    "\u5185\u8499\u53e4\u81ea\u6cbb\u533a": "\u5185\u8499\u53e4",
    "\u8fbd\u5b81": "\u8fbd\u5b81",
    "\u8fbd\u5b81\u7701": "\u8fbd\u5b81",
    "\u5409\u6797": "\u5409\u6797",
    "\u5409\u6797\u7701": "\u5409\u6797",
    "\u9ed1\u9f99\u6c5f": "\u9ed1\u9f99\u6c5f",
    "\u9ed1\u9f99\u6c5f\u7701": "\u9ed1\u9f99\u6c5f",
    "\u6c5f\u82cf": "\u6c5f\u82cf",
    "\u6c5f\u82cf\u7701": "\u6c5f\u82cf",
    "\u6d59\u6c5f": "\u6d59\u6c5f",
    "\u6d59\u6c5f\u7701": "\u6d59\u6c5f",
    "\u5b89\u5fbd": "\u5b89\u5fbd",
    "\u5b89\u5fbd\u7701": "\u5b89\u5fbd",
    "\u798f\u5efa": "\u798f\u5efa",
    "\u798f\u5efa\u7701": "\u798f\u5efa",
    "\u6c5f\u897f": "\u6c5f\u897f",
    "\u6c5f\u897f\u7701": "\u6c5f\u897f",
    "\u5c71\u4e1c": "\u5c71\u4e1c",
    "\u5c71\u4e1c\u7701": "\u5c71\u4e1c",
    "\u6cb3\u5357": "\u6cb3\u5357",
    "\u6cb3\u5357\u7701": "\u6cb3\u5357",
    "\u6e56\u5317": "\u6e56\u5317",
    "\u6e56\u5317\u7701": "\u6e56\u5317",
    "\u6e56\u5357": "\u6e56\u5357",
    "\u6e56\u5357\u7701": "\u6e56\u5357",
    "\u5e7f\u4e1c": "\u5e7f\u4e1c",
    "\u5e7f\u4e1c\u7701": "\u5e7f\u4e1c",
    "\u5e7f\u897f": "\u5e7f\u897f",
    "\u5e7f\u897f\u58ee\u65cf\u81ea\u6cbb\u533a": "\u5e7f\u897f",
    "\u6d77\u5357": "\u6d77\u5357",
    "\u6d77\u5357\u7701": "\u6d77\u5357",
    "\u56db\u5ddd": "\u56db\u5ddd",
    "\u56db\u5ddd\u7701": "\u56db\u5ddd",
    "\u8d35\u5dde": "\u8d35\u5dde",
    "\u8d35\u5dde\u7701": "\u8d35\u5dde",
    "\u4e91\u5357": "\u4e91\u5357",
    "\u4e91\u5357\u7701": "\u4e91\u5357",
    "\u897f\u85cf": "\u897f\u85cf",
    "\u897f\u85cf\u81ea\u6cbb\u533a": "\u897f\u85cf",
    "\u9655\u897f": "\u9655\u897f",
    "\u9655\u897f\u7701": "\u9655\u897f",
    "\u7518\u8083": "\u7518\u8083",
    "\u7518\u8083\u7701": "\u7518\u8083",
    "\u9752\u6d77": "\u9752\u6d77",
    "\u9752\u6d77\u7701": "\u9752\u6d77",
    "\u5b81\u590f": "\u5b81\u590f",
    "\u5b81\u590f\u56de\u65cf\u81ea\u6cbb\u533a": "\u5b81\u590f",
    "\u65b0\u7586": "\u65b0\u7586",
    "\u65b0\u7586\u7ef4\u543e\u5c14\u81ea\u6cbb\u533a": "\u65b0\u7586",
    "\u9999\u6e2f": "\u9999\u6e2f",
    "\u9999\u6e2f\u7279\u522b\u884c\u653f\u533a": "\u9999\u6e2f",
    "\u6fb3\u95e8": "\u6fb3\u95e8",
    "\u6fb3\u95e8\u7279\u522b\u884c\u653f\u533a": "\u6fb3\u95e8",
    "\u53f0\u6e7e": "\u53f0\u6e7e",
    "\u53f0\u6e7e\u7701": "\u53f0\u6e7e",
}


def _ensure_project_root_on_path():
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.append(str(project_root))
    return project_root


def _resolve_desktop_directory():
    home = Path.home()
    candidates = [
        home / "Desktop",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "桌面",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    fallback = home / "Desktop"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _sanitize_filename_component(value, fallback="report"):
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r'[\\/:*?"<>|]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:100] or fallback


def _build_unique_output_path(directory, file_name):
    candidate = directory / file_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        next_candidate = directory / f"{stem}-{counter}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        counter += 1


def _split_text_for_pdf(draw, text, font, max_width):
    lines = []
    for paragraph in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue

        current = ""
        for char in paragraph:
            candidate = f"{current}{char}"
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
                continue

            if current:
                lines.append(current)
                current = char
            else:
                lines.append(char)
                current = ""

        if current:
            lines.append(current)

    return lines or [""]


def _build_simple_pdf_bytes(title, content_text):
    from PIL import Image, ImageDraw, ImageFont

    page_width = 1240
    page_height = 1754
    margin_x = 100
    margin_top = 120
    margin_bottom = 100
    body_font_size = 32
    title_font_size = 48
    body_leading = body_font_size + 20
    title_gap = 40
    usable_width = page_width - (margin_x * 2)
    usable_height = page_height - margin_top - margin_bottom

    body_font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", body_font_size)
    title_font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", title_font_size)
    measure_image = Image.new("RGB", (page_width, page_height), "white")
    measure_draw = ImageDraw.Draw(measure_image)

    title_lines = _split_text_for_pdf(measure_draw, title, title_font, usable_width)
    body_lines = _split_text_for_pdf(measure_draw, content_text, body_font, usable_width)

    title_line_height = title_font_size + 18
    first_page_capacity = max(
        1,
        int((usable_height - len(title_lines) * title_line_height - title_gap) // body_leading),
    )
    later_page_capacity = max(1, int(usable_height // body_leading))

    pages = []
    first_page_lines = body_lines[:first_page_capacity]
    pages.append(("title", first_page_lines))
    remaining = body_lines[first_page_capacity:]
    while remaining:
        current_lines = remaining[:later_page_capacity]
        remaining = remaining[later_page_capacity:]
        pages.append(("body", current_lines))

    rendered_pages = []
    for page_type, lines in pages:
        image = Image.new("RGB", (page_width, page_height), "white")
        draw = ImageDraw.Draw(image)

        y = margin_top
        if page_type == "title":
            for title_line in title_lines:
                draw.text((margin_x, y), title_line, fill="#111111", font=title_font)
                y += title_line_height
            y += title_gap

        for line in lines:
            draw.text((margin_x, y), line or " ", fill="#333333", font=body_font)
            y += body_leading

        rendered_pages.append(image)

    output = BytesIO()
    first_page, *rest_pages = rendered_pages
    first_page.save(output, format="PDF", resolution=150.0, save_all=True, append_images=rest_pages)
    return output.getvalue()


def _keyword_filter_or_show_all(queryset, raw_q, keyword_q):
    raw_q = (raw_q or "").strip()
    if not raw_q:
        return queryset
    narrowed = queryset.filter(keyword_q)
    return narrowed if narrowed.exists() else queryset


def _apply_time_filter(queryset, field_name, raw_value):
    value = (raw_value or "all").strip().lower()
    offsets = {
        "1m": 30,
        "3m": 90,
        "6m": 180,
        "1y": 365,
        "3y": 365 * 3,
    }
    days = offsets.get(value)
    if not days:
        return queryset
    threshold = timezone.now().date() - timedelta(days=days)
    return queryset.filter(**{f"{field_name}__gte": threshold})


def _apply_amount_filter(queryset, field_name, raw_value):
    value = (raw_value or "all").strip().lower()
    if not value or value == "all":
        return queryset

    try:
        if value == "5000-inf":
            return queryset.filter(**{f"{field_name}__gte": 5000})

        min_value, max_value = map(float, value.split("-"))
        return queryset.filter(
            **{
                f"{field_name}__gte": min_value,
                f"{field_name}__lt": max_value,
            }
        )
    except ValueError:
        return queryset


def _paginate_queryset(queryset, raw_page, per_page=15):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(raw_page or 1)


def _first_present(row, *keys, default=None):
    for key in keys:
        if key in row:
            value = row.get(key)
            if value not in (None, "", []):
                return value
    return default


def _safe_console_log(message):
    text = str(message)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("unicode_escape", "backslashreplace").decode("ascii"))


def _report_page_schema_error_response(exc):
    error_text = str(exc)
    if "reports_reportpage" not in error_text or "has no column named" not in error_text:
        return None
    _safe_console_log(f"[reports schema mismatch] {error_text}")
    return JsonResponse(
        {
            "status": "error",
            "message": "报告数据表结构未更新，请先执行 python manage.py migrate reports",
        },
        status=500,
    )


def _normalize_keywords(raw_keywords, fallback_query=""):
    if isinstance(raw_keywords, str):
        raw_keywords = [raw_keywords]

    keywords = []
    seen = set()
    for item in raw_keywords or []:
        keyword = str(item or "").strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword[:100])

    fallback = str(fallback_query or "").strip()
    if not keywords and fallback:
        keywords.append(fallback[:100])

    return keywords[:50]


def _build_mysql_announcement_match_clause(keywords, alias="cjgg"):
    clauses = []
    params = []
    for keyword in keywords:
        like_value = f"%{keyword}%"
        clauses.append(
            f"({alias}.GGBT LIKE %s OR {alias}.XMMC LIKE %s OR {alias}.BDXX LIKE %s)"
        )
        params.extend([like_value, like_value, like_value])
    return " OR ".join(clauses), params


def _norm_region(value):
    region = _normalize_province_name(value)
    return region or "\u5168\u56fd"


def _normalize_province_name(value):
    text = (str(value) if value is not None else "").strip()
    if not text:
        return ""

    text = text.replace(" ", "")
    if text in _PROVINCE_ALIAS:
        return _PROVINCE_ALIAS[text]

    simplified = (
        text.replace("\u7701", "")
        .replace("\u5e02", "")
        .replace("\u81ea\u6cbb\u533a", "")
        .replace("\u7279\u522b\u884c\u653f\u533a", "")
        .replace("\u58ee\u65cf", "")
        .replace("\u56de\u65cf", "")
        .replace("\u7ef4\u543e\u5c14", "")
    )
    if simplified in _PROVINCE_ALIAS:
        return _PROVINCE_ALIAS[simplified]

    for province in _PROVINCE_NAMES:
        if text.startswith(province) or simplified.startswith(province):
            return province
    return ""


def _extract_province_from_text(value):
    province = _normalize_province_name(value)
    if province:
        return province

    text = str(value or "").strip().replace(" ", "")
    if not text:
        return ""

    for alias, province in sorted(
        _PROVINCE_ALIAS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if alias != "全国" and alias in text:
            return province

    for province in _PROVINCE_NAMES:
        if province in text:
            return province
    return ""


def _to_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    candidates = [text, text[:19], text[:10]]
    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    )
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def _build_unique_slug(parent_page, thread_id):
    base_slug = slugify(thread_id) or f"report-{int(timezone.now().timestamp())}"
    slug = base_slug
    suffix = 2
    siblings = parent_page.get_children()
    while siblings.filter(slug=slug).exists():
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    return slug


def _get_mysql_connection_kwargs():
    _ensure_project_root_on_path()

    mysql_config = {}
    try:
        from backend.app.config import get_settings as get_backend_settings

        mysql_config = getattr(get_backend_settings(), "mysql_config", {}) or {}
    except Exception as exc:
        _safe_console_log(f"[mysql] load backend config failed: {exc}")

    return {
        "host": mysql_config.get("host", "127.0.0.1"),
        "port": int(mysql_config.get("port", 3306)),
        "user": mysql_config.get("username", "root"),
        "password": mysql_config.get("password", ""),
        "database": mysql_config.get("database", "test"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": 10,
        "read_timeout": 20,
        "write_timeout": 20,
    }


@lru_cache(maxsize=512)
def _infer_buyer_region_with_llm(buyer_name):
    buyer_name = str(buyer_name or "").strip()
    if not buyer_name:
        return ""

    try:
        _ensure_project_root_on_path()
        from backend.app.config import get_settings as get_backend_settings
        from backend.app.graph_agent import invoke_llm

        backend_settings = get_backend_settings()
        if not backend_settings.validate_api_key():
            return ""

        prompt = f"请直接告诉我{buyer_name}的省份，然后请只输出省份信息。"
        reply, _ = async_to_sync(invoke_llm)(
            messages=[{"role": "user", "content": prompt}],
            settings=backend_settings,
            temperature=0,
            max_tokens=32,
        )
        return _extract_province_from_text(reply)
    except Exception as exc:
        _safe_console_log(
            f"[llm] infer buyer region failed: buyer={buyer_name}, error={exc}"
        )
        return ""


def _fill_top_buyer_regions_with_llm(top_buyer_rows, displayed_limit=10):
    normalized_rows = []
    for index, row in enumerate(top_buyer_rows or []):
        row_copy = dict(row)
        if index < displayed_limit and row_copy.get("region") == "-":
            inferred_region = _infer_buyer_region_with_llm(
                row_copy.get("buyer_name", "")
            )
            if inferred_region:
                row_copy["region"] = inferred_region
        normalized_rows.append(row_copy)
    return normalized_rows


def _query_mysql_announcements_by_keywords(raw_keywords, fallback_query="", limit=None):
    keywords = _normalize_keywords(raw_keywords, fallback_query=fallback_query)
    if not keywords:
        return []

    where_clause, params = _build_mysql_announcement_match_clause(
        keywords,
        alias="cjgg",
    )

    sql = f"""
        SELECT DISTINCT
            cjgg.WID,
            cjgg.GGFBRQ,
            cjgg.GGBT,
            cjgg.GGURL,
            cjgg.XMBH,
            cjgg.XMMC,
            cjgg.CGRMC,
            cjgg.CGRDZ,
            cjgg.BDXX,
            cjgg.CJSJ,
            COALESCE(cjs_by_ggwid.region_name, cjs_by_wid.region_name, cjgg.CGRDZ, '') AS region_name,
            COALESCE(cjs_by_ggwid.CJJE, cjs_by_wid.CJJE) AS CJJE
        FROM zc_wlsjcj_cjgg cjgg
        LEFT JOIN (
            SELECT
                GGWID AS link_wid,
                SUM(CJJE) AS CJJE,
                MIN(NULLIF(TRIM(region), '')) AS region_name
            FROM zc_wlsjcj_cjs
            WHERE GGWID IS NOT NULL AND GGWID <> ''
            GROUP BY GGWID
        ) cjs_by_ggwid ON cjs_by_ggwid.link_wid = cjgg.WID
        LEFT JOIN (
            SELECT
                WID AS link_wid,
                SUM(CJJE) AS CJJE,
                MIN(NULLIF(TRIM(region), '')) AS region_name
            FROM zc_wlsjcj_cjs
            WHERE WID IS NOT NULL AND WID <> ''
            GROUP BY WID
        ) cjs_by_wid ON cjs_by_wid.link_wid = cjgg.WID
        WHERE {where_clause}
        ORDER BY cjgg.GGFBRQ DESC, cjgg.CJSJ DESC
    """

    if limit is not None:
        sql += "\n        LIMIT %s"
        params.append(int(limit))

    connection = pymysql.connect(**_get_mysql_connection_kwargs())
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = list(cursor.fetchall())
            _safe_console_log(
                f"[mysql] announcement query finished: keywords={keywords}, row_count={len(rows)}"
            )
            return rows
    finally:
        connection.close()


def _format_stat_count(value, suffix=""):
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        number = 0
    return f"{number:,}{suffix}"


def _format_stat_amount(value, suffix=" 元"):
    amount = _to_decimal(value) or Decimal("0")
    text = f"{amount:,.2f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"


def _query_mysql_report_card_stats(raw_keywords, fallback_query=""):
    keywords = _normalize_keywords(raw_keywords, fallback_query=fallback_query)
    empty_stats = {
        "stat_buyer_count": _format_stat_count(0, " 家"),
        "stat_region_count": _format_stat_count(0, " 个"),
        "stat_budget_total": _format_stat_amount(0),
        "stat_transaction_total": _format_stat_amount(0),
        "stat_announcement_count": _format_stat_count(0, " 条"),
    }
    if not keywords:
        return empty_stats

    where_clause, params = _build_mysql_announcement_match_clause(
        keywords,
        alias="cjgg",
    )

    announcement_stats_sql = f"""
        SELECT
            COUNT(*) AS announcement_count,
            COUNT(DISTINCT NULLIF(TRIM(matched.CGRMC), '')) AS buyer_count
        FROM (
            SELECT DISTINCT cjgg.WID, cjgg.CGRMC
            FROM zc_wlsjcj_cjgg cjgg
            WHERE {where_clause}
        ) matched
    """

    cjs_stats_sql = f"""
        SELECT
            COUNT(DISTINCT NULLIF(TRIM(cjs.region), '')) AS region_count,
            COALESCE(SUM(cjs.CJJE), 0) AS total_amount
        FROM zc_wlsjcj_cjs cjs
        WHERE EXISTS (
            SELECT 1
            FROM (
                SELECT DISTINCT cjgg.WID
                FROM zc_wlsjcj_cjgg cjgg
                WHERE {where_clause}
            ) matched_gg
            WHERE matched_gg.WID = cjs.GGWID OR matched_gg.WID = cjs.WID
        )
    """

    connection = pymysql.connect(**_get_mysql_connection_kwargs())
    try:
        with connection.cursor() as cursor:
            cursor.execute(announcement_stats_sql, params)
            announcement_stats = cursor.fetchone() or {}

            cursor.execute(cjs_stats_sql, params)
            cjs_stats = cursor.fetchone() or {}
    finally:
        connection.close()

    total_amount = _to_decimal(cjs_stats.get("total_amount")) or Decimal("0")
    stats = {
        "stat_buyer_count": _format_stat_count(
            announcement_stats.get("buyer_count"),
            " 家",
        ),
        "stat_region_count": _format_stat_count(
            cjs_stats.get("region_count"),
            " 个",
        ),
        "stat_budget_total": _format_stat_amount(total_amount),
        "stat_transaction_total": _format_stat_amount(total_amount),
        "stat_announcement_count": _format_stat_count(
            announcement_stats.get("announcement_count"),
            " 条",
        ),
    }
    _safe_console_log(
        f"[mysql] card stats finished: keywords={keywords}, stats={stats}"
    )
    return stats


def _query_mysql_region_distribution(raw_keywords, fallback_query=""):
    keywords = _normalize_keywords(raw_keywords, fallback_query=fallback_query)
    if not keywords:
        return []

    where_clause, params = _build_mysql_announcement_match_clause(
        keywords,
        alias="cjgg",
    )

    sql = f"""
        SELECT
            matched.CGRMC AS buyer_name,
            COALESCE(cjs_by_wid.region_name, cjs_by_ggwid.region_name, '') AS region_name
        FROM (
            SELECT DISTINCT
                cjgg.WID,
                NULLIF(TRIM(cjgg.CGRMC), '') AS CGRMC
            FROM zc_wlsjcj_cjgg cjgg
            WHERE ({where_clause})
              AND NULLIF(TRIM(cjgg.CGRMC), '') IS NOT NULL
        ) matched
        LEFT JOIN (
            SELECT
                WID AS link_wid,
                MIN(NULLIF(TRIM(region), '')) AS region_name
            FROM zc_wlsjcj_cjs
            WHERE WID IS NOT NULL AND WID <> ''
            GROUP BY WID
        ) cjs_by_wid ON cjs_by_wid.link_wid = matched.WID
        LEFT JOIN (
            SELECT
                GGWID AS link_wid,
                MIN(NULLIF(TRIM(region), '')) AS region_name
            FROM zc_wlsjcj_cjs
            WHERE GGWID IS NOT NULL AND GGWID <> ''
            GROUP BY GGWID
        ) cjs_by_ggwid ON cjs_by_ggwid.link_wid = matched.WID
    """

    connection = pymysql.connect(**_get_mysql_connection_kwargs())
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = list(cursor.fetchall())
    finally:
        connection.close()

    province_buyers = defaultdict(set)
    for row in rows:
        province = _normalize_province_name(row.get("region_name"))
        if not province or province == "\u5168\u56fd":
            continue
        buyer_name = str(row.get("buyer_name") or "").strip()
        if not buyer_name:
            continue
        province_buyers[province].add(buyer_name)

    distribution = sorted(
        (
            {"name": name, "value": len(buyers)}
            for name, buyers in province_buyers.items()
            if buyers
        ),
        key=lambda item: (-item["value"], item["name"]),
    )
    _safe_console_log(
        f"[mysql] region distribution finished: keywords={keywords}, rows={len(distribution)}"
    )
    return distribution


def _query_mysql_region_amounts(raw_keywords, fallback_query=""):
    keywords = _normalize_keywords(raw_keywords, fallback_query=fallback_query)
    if not keywords:
        return []

    where_clause, params = _build_mysql_announcement_match_clause(
        keywords,
        alias="cjgg",
    )

    sql = f"""
        SELECT
            cjs.region AS region_name,
            COALESCE(
                SUM(
                    CAST(
                        NULLIF(
                            REPLACE(REPLACE(TRIM(cjs.CJJE), ',', ''), '，', ''),
                            ''
                        ) AS DECIMAL(18, 2)
                    )
                ),
                0
            ) AS total_amount
        FROM zc_wlsjcj_cjs cjs
        WHERE EXISTS (
            SELECT 1
            FROM (
                SELECT DISTINCT cjgg.WID
                FROM zc_wlsjcj_cjgg cjgg
                WHERE {where_clause}
            ) matched_gg
            WHERE matched_gg.WID = cjs.GGWID OR matched_gg.WID = cjs.WID
        )
        GROUP BY cjs.region
    """

    connection = pymysql.connect(**_get_mysql_connection_kwargs())
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = list(cursor.fetchall())
    finally:
        connection.close()

    province_amounts = {
        province: Decimal("0")
        for province in _PROVINCE_NAMES
    }
    province_amounts.update({
        "棣欐腐": Decimal("0"),
        "婢抽棬": Decimal("0"),
        "鍙版咕": Decimal("0"),
    })

    for row in rows:
        province = _normalize_province_name(row.get("region_name"))
        if not province or province == "鍏ㄥ浗":
            continue
        amount = _to_decimal(row.get("total_amount")) or Decimal("0")
        if province not in province_amounts:
            province_amounts[province] = Decimal("0")
        province_amounts[province] += amount

    result = sorted(
        (
            {"name": name, "value": float(amount)}
            for name, amount in province_amounts.items()
        ),
        key=lambda item: (-item["value"], item["name"]),
    )
    _safe_console_log(
        f"[mysql] region amount finished: keywords={keywords}, rows={len(result)}"
    )
    return result


def _query_mysql_announcements_by_keywords_and_buyer(
    raw_keywords,
    buyer_name,
    fallback_query="",
    limit=None,
):
    keywords = _normalize_keywords(raw_keywords, fallback_query=fallback_query)
    buyer_text = str(buyer_name or "").strip()
    if not keywords or not buyer_text:
        return []

    where_clause, params = _build_mysql_announcement_match_clause(
        keywords,
        alias="cjgg",
    )
    params.append(f"%{buyer_text}%")

    sql = f"""
        SELECT DISTINCT
            cjgg.WID,
            cjgg.GGFBRQ,
            cjgg.GGBT,
            cjgg.GGURL,
            cjgg.XMBH,
            cjgg.XMMC,
            cjgg.CGRMC,
            cjgg.CGRDZ,
            cjgg.BDXX,
            cjgg.CJSJ,
            COALESCE(cjs_by_ggwid.region_name, cjs_by_wid.region_name, cjgg.CGRDZ, '') AS region_name,
            COALESCE(cjs_by_ggwid.CJJE, cjs_by_wid.CJJE) AS CJJE
        FROM zc_wlsjcj_cjgg cjgg
        LEFT JOIN (
            SELECT
                GGWID AS link_wid,
                SUM(CJJE) AS CJJE,
                MIN(NULLIF(TRIM(region), '')) AS region_name
            FROM zc_wlsjcj_cjs
            WHERE GGWID IS NOT NULL AND GGWID <> ''
            GROUP BY GGWID
        ) cjs_by_ggwid ON cjs_by_ggwid.link_wid = cjgg.WID
        LEFT JOIN (
            SELECT
                WID AS link_wid,
                SUM(CJJE) AS CJJE,
                MIN(NULLIF(TRIM(region), '')) AS region_name
            FROM zc_wlsjcj_cjs
            WHERE WID IS NOT NULL AND WID <> ''
            GROUP BY WID
        ) cjs_by_wid ON cjs_by_wid.link_wid = cjgg.WID
        WHERE ({where_clause})
          AND NULLIF(TRIM(cjgg.CGRMC), '') IS NOT NULL
          AND TRIM(cjgg.CGRMC) LIKE %s
        ORDER BY cjgg.GGFBRQ DESC, cjgg.CJSJ DESC
    """

    if limit is not None:
        sql += "\n        LIMIT %s"
        params.append(int(limit))

    connection = pymysql.connect(**_get_mysql_connection_kwargs())
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = list(cursor.fetchall())
            _safe_console_log(
                f"[mysql] buyer announcement query finished: keywords={keywords}, buyer={buyer_text}, row_count={len(rows)}"
            )
            return rows
    finally:
        connection.close()

    province_amounts = {
        province: Decimal("0")
        for province in _PROVINCE_NAMES
    }
    province_amounts.update({
        "香港": Decimal("0"),
        "澳门": Decimal("0"),
        "台湾": Decimal("0"),
    })

    for row in rows:
        province = _normalize_province_name(row.get("region_name"))
        if not province or province == "全国":
            continue
        amount = _to_decimal(row.get("total_amount")) or Decimal("0")
        if province not in province_amounts:
            province_amounts[province] = Decimal("0")
        province_amounts[province] += amount

    result = sorted(
        (
            {"name": name, "value": float(amount)}
            for name, amount in province_amounts.items()
        ),
        key=lambda item: (-item["value"], item["name"]),
    )
    _safe_console_log(
        f"[mysql] region amount finished: keywords={keywords}, rows={len(result)}"
    )
    return result


def _query_mysql_top_buyers(raw_keywords, fallback_query="", limit=10):
    keywords = _normalize_keywords(raw_keywords, fallback_query=fallback_query)
    if not keywords:
        return []

    try:
        limit_value = max(int(limit or 10), 1)
    except (TypeError, ValueError):
        limit_value = 10

    where_clause, params = _build_mysql_announcement_match_clause(
        keywords,
        alias="cjgg",
    )

    sql = f"""
        SELECT
            matched.WID,
            matched.CGRMC AS buyer_name,
            COALESCE(cjs_by_wid.region_name, cjs_by_ggwid.region_name, '') AS region_name,
            COALESCE(cjs_by_wid.total_amount, cjs_by_ggwid.total_amount, 0) AS transaction_amount
        FROM (
            SELECT DISTINCT
                cjgg.WID,
                NULLIF(TRIM(cjgg.CGRMC), '') AS CGRMC
            FROM zc_wlsjcj_cjgg cjgg
            WHERE ({where_clause})
              AND NULLIF(TRIM(cjgg.CGRMC), '') IS NOT NULL
        ) matched
        LEFT JOIN (
            SELECT
                WID AS link_wid,
                COALESCE(
                    SUM(
                        CAST(
                            NULLIF(
                                REPLACE(REPLACE(TRIM(CJJE), ',', ''), '，', ''),
                                ''
                            ) AS DECIMAL(18, 2)
                        )
                    ),
                    0
                ) AS total_amount,
                MIN(NULLIF(TRIM(region), '')) AS region_name
            FROM zc_wlsjcj_cjs
            WHERE WID IS NOT NULL AND WID <> ''
            GROUP BY WID
        ) cjs_by_wid ON cjs_by_wid.link_wid = matched.WID
        LEFT JOIN (
            SELECT
                GGWID AS link_wid,
                COALESCE(
                    SUM(
                        CAST(
                            NULLIF(
                                REPLACE(REPLACE(TRIM(CJJE), ',', ''), '，', ''),
                                ''
                            ) AS DECIMAL(18, 2)
                        )
                    ),
                    0
                ) AS total_amount,
                MIN(NULLIF(TRIM(region), '')) AS region_name
            FROM zc_wlsjcj_cjs
            WHERE GGWID IS NOT NULL AND GGWID <> ''
            GROUP BY GGWID
        ) cjs_by_ggwid ON cjs_by_ggwid.link_wid = matched.WID
    """

    connection = pymysql.connect(**_get_mysql_connection_kwargs())
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = list(cursor.fetchall())
    finally:
        connection.close()

    buyer_totals = {}
    for row in rows:
        buyer_name = str(row.get("buyer_name") or "").strip()
        if not buyer_name:
            continue

        transaction_amount = _to_decimal(row.get("transaction_amount")) or Decimal("0")
        raw_region = str(row.get("region_name") or "").strip()
        normalized_region = _normalize_province_name(raw_region) or raw_region

        buyer_entry = buyer_totals.setdefault(
            buyer_name,
            {
                "buyer_name": buyer_name[:255],
                "project_count": 0,
                "transaction_amount_value": Decimal("0"),
                "regions": set(),
            },
        )
        buyer_entry["project_count"] += 1
        buyer_entry["transaction_amount_value"] += transaction_amount
        if normalized_region:
            buyer_entry["regions"].add(normalized_region)

    top_buyers = sorted(
        buyer_totals.values(),
        key=lambda item: (
            -item["project_count"],
            -item["transaction_amount_value"],
            item["buyer_name"],
        ),
    )[:limit_value]

    normalized_rows = []
    for item in top_buyers:
        regions = item.pop("regions", set())
        item["region"] = next(iter(regions)) if len(regions) == 1 else "-"
        item["transaction_amount"] = f"{item['transaction_amount_value']:,.2f}"
        normalized_rows.append(item)

    _safe_console_log(
        f"[mysql] top buyers finished: keywords={keywords}, rows={len(normalized_rows)}"
    )
    return normalized_rows


def _map_mysql_announcement(row):
    title = _first_present(
        row,
        "GGBT",
        "announcement_title",
        "TITLE",
        "title",
        "项目名称",
        "PROJECT_NAME",
        "project_name",
        "标的信息",
        default="未命名公告",
    )
    buyer = _first_present(
        row,
        "CGRMC",
        "采购人名称",
        "supplier_name",
        "BUYER",
        "buyer",
        "PROCUREMENT_UNIT",
        "procurement_unit",
        default="",
    )
    target_url = _first_present(
        row,
        "GGURL",
        "公告链接",
        "url",
        "URL",
        "detail_url",
        "LINK",
        default="",
    )
    budget_value = _first_present(
        row,
        "budget_amount",
        "预算金额",
        "AMOUNT",
        "price",
        "BUDGET",
        "CJJE",
        "成交金额",
        default=None,
    )

    return {
        "title": str(title)[:255],
        "buyer": str(buyer)[:255],
        "region": _norm_region(
            _first_present(
                row,
                "region_name",
                "CGRDZ",
                "region",
                "REGION",
                "PROVINCE",
                "province",
                "CITY",
                "city",
                "地区",
                "省份",
                default="",
            )
        ),
        "publish_date": _parse_date(
            _first_present(
                row,
                "GGFBRQ",
                "公告发布日期",
                "announcement_time",
                "publish_date",
                "PUBLISH_DATE",
                "publish_time",
                "create_time",
            )
        ),
        "budget_amount": _to_decimal(budget_value),
        "transaction_amount": _to_decimal(
            _first_present(
                row,
                "transaction_amount",
                "deal_amount",
                "CJJE",
                "成交金额",
                default=None,
            )
        ),
        "url": str(target_url)[:200] if target_url else "",
        "project_number": str(
            _first_present(row, "XMBH", "project_number", default="")
        )[:100]
        or None,
    }


def _build_report_body(content, created_count):
    content_text = (content or "").strip()
    if created_count:
        prefix = f"本次分析已纳入 {created_count} 条采购公告数据。"
        if content_text:
            return f"{prefix}\n\n{content_text}"
        return f"{prefix} 请在侧栏查看“采购公告”分类明细。"
    if content_text:
        return content_text
    return (
        "本次分析未检索到匹配的采购公告；请确认扩充关键词有效，且 MySQL 公告表 "
        "zc_wlsjcj_cjgg 中存在与这些关键词模糊匹配的数据。"
    )


def ai_analysis(request):
    """AI 分析中间页面。"""
    keyword = (request.GET.get("query") or request.GET.get("search") or "").strip()
    if not keyword:
        keyword = "未指定关键词"
    return render(request, "reports/ai_analysis.html", {"keyword": keyword})


def _user_can_access_report(report, user):
    if getattr(report, "is_public", False):
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(
        getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
        or report.owner_id == user.id
    )


@csrf_exempt
@require_POST
def export_ai_summary_pdf(request, report_id):
    report = get_object_or_404(ReportPage, id=report_id)
    if not _user_can_access_report(report, request.user):
        return JsonResponse(
            {"success": False, "error": "You do not have permission to export this report."},
            status=403,
        )

    content_text = (report.ai_summary_analysis or "").strip() or "暂无分析内容"
    safe_name = _sanitize_filename_component(
        report.procurement_name or report.title or f"report-{report.id}",
        fallback=f"report-{report.id}",
    )
    file_name = f"{safe_name}-AI总结分析.pdf"
    desktop_dir = _resolve_desktop_directory()
    target_path = _build_unique_output_path(desktop_dir, file_name)

    try:
        pdf_bytes = _build_simple_pdf_bytes("AI总结分析", content_text)
        target_path.write_bytes(pdf_bytes)
    except Exception as exc:
        _safe_console_log(
            f"[export_ai_summary_pdf] failed: report_id={report_id}, path={target_path}, error={exc}"
        )
        return JsonResponse(
            {"success": False, "error": "PDF 生成失败，请稍后重试。"},
            status=500,
        )

    return JsonResponse(
        {
            "success": True,
            "message": "PDF 已保存到桌面",
            "file_name": file_name,
            "file_path": str(target_path),
        }
    )


@csrf_exempt
@require_POST
def update_report_content(request, report_id):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    field = data.get("field")
    content = data.get("content", "")
    allowed_fields = {
        "market_supply_analysis",
        "market_trend_analysis",
        "ai_summary_analysis",
    }
    if field not in allowed_fields:
        return JsonResponse({"success": False, "error": "Invalid field"}, status=400)

    try:
        report = ReportPage.objects.get(id=report_id)
    except ReportPage.DoesNotExist:
        return JsonResponse({"success": False, "error": "Report not found"}, status=404)

    setattr(report, field, content)
    report.save_revision().publish()
    return JsonResponse({"success": True, "message": "Saved successfully"})


def filter_historical_projects(request, report_id):
    report = get_object_or_404(ReportPage, id=report_id)
    projects = HistoricalProject.objects.filter(page=report)

    q = request.GET.get("q", "").strip()
    if q:
        projects = _keyword_filter_or_show_all(
            projects,
            q,
            Q(project_name__icontains=q)
            | Q(procurement_unit__icontains=q)
            | Q(supplier_name__icontains=q),
        )

    projects = _apply_time_filter(projects, "procurement_time", request.GET.get("time"))
    projects = _apply_amount_filter(
        projects, "transaction_amount", request.GET.get("amount")
    )
    projects = projects.order_by("-procurement_time", "-id")

    return render(
        request,
        "reports/partials/project_table.html",
        {"projects": projects},
    )


def filter_ongoing_projects(request, report_id):
    report = get_object_or_404(ReportPage, id=report_id)
    projects = OngoingProject.objects.filter(page=report)

    q = request.GET.get("q", "").strip()
    if q:
        projects = _keyword_filter_or_show_all(
            projects,
            q,
            Q(project_name__icontains=q) | Q(procurement_unit__icontains=q),
        )

    projects = _apply_time_filter(projects, "bid_opening_time", request.GET.get("time"))
    projects = _apply_amount_filter(projects, "budget_amount", request.GET.get("amount"))
    projects = projects.order_by("-bid_opening_time", "-id")

    return render(
        request,
        "reports/partials/ongoing_project_table.html",
        {"projects": projects},
    )


def filter_purchase_intentions(request, report_id):
    report = get_object_or_404(ReportPage, id=report_id)
    intentions = report.purchase_intentions.all()

    q = request.GET.get("q", "").strip()
    if q:
        intentions = _keyword_filter_or_show_all(
            intentions,
            q,
            Q(project_name__icontains=q)
            | Q(procurement_unit__icontains=q)
            | Q(content__icontains=q),
        )

    intentions = _apply_amount_filter(intentions, "budget_amount", request.GET.get("amount"))

    region = (request.GET.get("region") or "All").strip()
    if region and region not in {"All", "全国"}:
        intentions = intentions.filter(province__icontains=region)

    intentions = intentions.order_by("-publish_time", "-id")
    return render(
        request,
        "reports/partials/intention_list.html",
        {"intentions": intentions},
    )


def filter_announcements(request, report_id):
    report = get_object_or_404(ReportPage, id=report_id)
    announcements = report.report_announcements.all()

    q = request.GET.get("q", "").strip()
    if q:
        announcements = _keyword_filter_or_show_all(
            announcements,
            q,
            Q(title__icontains=q) | Q(buyer__icontains=q),
        )

    announcements = _apply_time_filter(
        announcements, "publish_date", request.GET.get("time")
    )
    announcements = _apply_amount_filter(
        announcements, "budget_amount", request.GET.get("amount")
    )
    region_value = (request.GET.get("region") or "all").strip()
    if region_value and region_value.lower() != "all":
        try:
            from announcements.services import REGION_CODE_TO_NAME
        except Exception:
            REGION_CODE_TO_NAME = {}

        region_name = REGION_CODE_TO_NAME.get(region_value) or _norm_region(region_value)
        if region_name and region_name != "全国":
            announcements = announcements.filter(region__icontains=region_name)

    announcements = announcements.order_by("-publish_date", "-id")
    announcements = _paginate_queryset(announcements, request.GET.get("page"), per_page=15)

    return render(
        request,
        "reports/partials/announcement_table.html",
        {"announcements": announcements},
    )


def buyer_project_detail(request, report_id):
    report = get_object_or_404(ReportPage, id=report_id)
    buyer_name = (request.GET.get("buyer") or "").strip()
    if not buyer_name:
        return redirect(report.url)

    search_query = request.GET.get("search", "").strip()
    region_value = (request.GET.get("region") or "all").strip()
    time_value = (request.GET.get("time") or "all").strip()
    amount_value = (request.GET.get("amount") or "all").strip()

    announcements = report.report_announcements.filter(buyer__icontains=buyer_name)
    if search_query:
        announcements = announcements.filter(
            Q(title__icontains=search_query)
            | Q(buyer__icontains=search_query)
            | Q(project_number__icontains=search_query)
        )

    announcements = _apply_time_filter(announcements, "publish_date", time_value)
    announcements = _apply_amount_filter(announcements, "budget_amount", amount_value)
    if region_value and region_value.lower() != "all":
        try:
            from announcements.services import REGION_CODE_TO_NAME
        except Exception:
            REGION_CODE_TO_NAME = {}

        region_name = REGION_CODE_TO_NAME.get(region_value) or _norm_region(region_value)
        if region_name and region_name != "全国":
            announcements = announcements.filter(region__icontains=region_name)

    announcements = announcements.order_by("-publish_date", "-id")
    page_obj = _paginate_queryset(announcements, request.GET.get("page"), per_page=10)

    total_count = announcements.count()
    has_local_results = total_count > 0

    if not has_local_results:
        report_keywords = []
        for token in re.split("[、，,;；\\n\\r\\t]+", str(report.analysis_keywords or "")):
            keyword = token.strip()
            if keyword:
                report_keywords.append(keyword)

        keyword_fallback = (report.procurement_name or report.title or "").strip()
        try:
            mysql_rows = _query_mysql_announcements_by_keywords_and_buyer(
                report_keywords,
                buyer_name,
                fallback_query=keyword_fallback,
            )
        except Exception:
            mysql_rows = []

        fallback_announcements = []
        for row in mysql_rows:
            mapped = _map_mysql_announcement(row)
            if search_query:
                haystack = " ".join(
                    [
                        str(mapped.get("title") or ""),
                        str(mapped.get("buyer") or ""),
                        str(mapped.get("project_number") or ""),
                    ]
                ).lower()
                if search_query.lower() not in haystack:
                    continue

            region_name = str(mapped.get("region") or "").strip()
            if region_value and region_value.lower() != "all":
                try:
                    from announcements.services import REGION_CODE_TO_NAME
                except Exception:
                    REGION_CODE_TO_NAME = {}

                normalized_region = (
                    REGION_CODE_TO_NAME.get(region_value) or _norm_region(region_value)
                )
                if (
                    normalized_region
                    and normalized_region != "全国"
                    and normalized_region not in region_name
                ):
                    continue

            publish_date = mapped.get("publish_date")
            if time_value and time_value.lower() != "all":
                threshold_map = {
                    "1m": 30,
                    "3m": 90,
                    "6m": 180,
                    "1y": 365,
                    "3y": 365 * 3,
                }
                threshold_days = threshold_map.get(time_value.lower())
                if threshold_days and publish_date:
                    threshold_date = timezone.now().date() - timedelta(days=threshold_days)
                    if publish_date < threshold_date:
                        continue
                elif threshold_days and not publish_date:
                    continue

            amount_number = mapped.get("budget_amount")
            if amount_value and amount_value.lower() != "all":
                try:
                    if amount_value == "5000-inf":
                        if amount_number is None or amount_number < 5000:
                            continue
                    else:
                        min_value, max_value = map(float, amount_value.split("-"))
                        if amount_number is None:
                            continue
                        if not (Decimal(str(min_value)) <= amount_number < Decimal(str(max_value))):
                            continue
                except ValueError:
                    pass

            fallback_announcements.append(mapped)

        paginator = Paginator(fallback_announcements, 10)
        page_obj = paginator.get_page(request.GET.get("page") or 1)
        total_count = len(fallback_announcements)

    try:
        from announcements.services import REGION_FILTER_CHOICES

        region_choices = REGION_FILTER_CHOICES
    except Exception:
        region_choices = [("all", "全部")]

    context = {
        "report": report,
        "buyer_name": buyer_name,
        "announcements": page_obj,
        "total_count": total_count,
        "search_query": search_query,
        "search_active": bool(search_query),
        "page_size": 10,
        "region_choices": region_choices,
        "has_local_results": has_local_results,
    }
    return render(
        request,
        "reports/buyer_project_detail.html",
        context,
    )


def filter_contracts(request, report_id):
    report = get_object_or_404(ReportPage, id=report_id)
    contracts = report.report_contracts.all()

    q = request.GET.get("q", "").strip()
    if q:
        contracts = _keyword_filter_or_show_all(
            contracts,
            q,
            Q(title__icontains=q) | Q(buyer__icontains=q),
        )

    contracts = _apply_time_filter(contracts, "publish_date", request.GET.get("time"))
    contracts = _apply_amount_filter(
        contracts, "budget_amount", request.GET.get("amount")
    )

    region = (request.GET.get("region") or "All").strip()
    if region and region not in {"All", "全国"}:
        contracts = contracts.filter(region__icontains=region)

    contracts = contracts.order_by("-publish_date", "-id")
    return render(
        request,
        "reports/partials/contract_table.html",
        {"contracts": contracts},
    )


def filter_documents(request, report_id):
    report = get_object_or_404(ReportPage, id=report_id)
    documents = report.report_documents.all()

    q = request.GET.get("q", "").strip()
    if q:
        documents = _keyword_filter_or_show_all(
            documents,
            q,
            Q(title__icontains=q) | Q(source__icontains=q),
        )

    doc_type = (request.GET.get("type") or "all").strip()
    if doc_type not in {"all", "All"}:
        documents = documents.filter(doc_type=doc_type)

    file_format = (request.GET.get("format") or "all").strip().lower()
    if file_format and file_format != "all":
        documents = documents.filter(file__iendswith=f".{file_format}")

    documents = documents.order_by("-upload_time", "-id")
    return render(
        request,
        "reports/partials/document_table.html",
        {"documents": documents},
    )


def chat_home(request):
    return render(request, "reports/chat_home.html")


@require_POST
def delete_report(request, report_id):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        login_url = f"/accounts/login/?next=/reports/"
        return redirect(login_url)

    report = get_object_or_404(ReportPage, id=report_id)
    can_delete = request.user.is_superuser or report.owner_id == request.user.id
    if not can_delete:
        return HttpResponseForbidden("You do not have permission to delete this report.")

    parent_url = "/reports/"
    parent_page = report.get_parent()
    if parent_page and getattr(parent_page, "url", None):
        parent_url = parent_page.url

    report.delete()
    return redirect(parent_url)


@csrf_exempt
@require_POST
def upload_temp_file(request):
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return JsonResponse({"success": False, "error": "未接收到文件"}, status=400)

    storage = FileSystemStorage(
        location=os.path.join(settings.MEDIA_ROOT, "temp_rag_docs")
    )
    filename = storage.save(uploaded_file.name, uploaded_file)
    return JsonResponse({"success": True, "file_id": filename})


@require_POST
def create_report_from_ai(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

    title = data.get("title", "AI 需求调查报告")
    content = data.get("content", "")
    thread_id = (data.get("thread_id") or "").strip()
    expanded_keywords = data.get("expanded_keywords", [])
    if isinstance(expanded_keywords, str):
        try:
            expanded_keywords = json.loads(expanded_keywords)
        except json.JSONDecodeError:
            expanded_keywords = [expanded_keywords]
    if not isinstance(expanded_keywords, list):
        expanded_keywords = []

    if not thread_id:
        return JsonResponse({"status": "error", "message": "缺少 thread_id"}, status=400)

    parent_page = ReportIndexPage.objects.first()
    if not parent_page:
        return JsonResponse(
            {"status": "error", "message": "未找到报告目录父节点"},
            status=500,
        )

    keywords = _normalize_keywords(expanded_keywords, fallback_query=title)
    new_report = ReportPage(
        title=f"{title} 需求调查报告",
        slug=_build_unique_slug(parent_page, thread_id),
        content=content,
        ai_summary_analysis=content,
        procurement_name=title,
        analysis_keywords="、".join(keywords),
        owner=request.user if getattr(request, "user", None) and request.user.is_authenticated else None,
    )
    try:
        parent_page.add_child(instance=new_report)
        new_report.save_revision().publish()
    except OperationalError as exc:
        response = _report_page_schema_error_response(exc)
        if response is not None:
            return response
        raise

    try:
        mysql_rows = _query_mysql_announcements_by_keywords(
            keywords,
            fallback_query=title,
        )
        card_stats = _query_mysql_report_card_stats(
            keywords,
            fallback_query=title,
        )
    except Exception as exc:
        _safe_console_log(f"[create_report_from_ai] direct mysql query failed: {exc}")
        mysql_rows = []
        card_stats = {}

    _safe_console_log(
        f"[create_report_from_ai] start processing {len(mysql_rows)} rows, keywords={keywords}"
    )

    created_count = 0
    failed_count = 0
    for index, row in enumerate(mysql_rows, start=1):
        try:
            mapped = _map_mysql_announcement(row)
            new_report.report_announcements.create(**mapped)
            created_count += 1
            _safe_console_log(
                f"[create_report_from_ai] processing row {index}/{len(mysql_rows)} title={mapped['title'][:50]}"
            )
        except Exception as exc:
            failed_count += 1
            _safe_console_log(
                f"[create_report_from_ai] row {index} write failed: {exc}; row_keys={list(row.keys())}"
            )

    new_report.serial_number = thread_id[:50] or f"RPT-{new_report.id}"
    for field_name, field_value in card_stats.items():
        setattr(new_report, field_name, field_value)
    report_body = _build_report_body(content, created_count)
    new_report.market_supply_analysis = ""
    new_report.market_trend_analysis = report_body[:20000]
    try:
        new_report.save_revision().publish()
    except OperationalError as exc:
        response = _report_page_schema_error_response(exc)
        if response is not None:
            return response
        raise

    _safe_console_log(
        f"[create_report_from_ai] done: created={created_count}, failed={failed_count}, total={len(mysql_rows)}"
    )
    _safe_console_log(f"[create_report_from_ai] report_url={new_report.url}")

    return JsonResponse(
        {
            "status": "success",
            "redirect_url": new_report.url,
            "created_count": created_count,
            "failed_count": failed_count,
        }
    )
