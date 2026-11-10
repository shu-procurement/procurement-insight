from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil

import pymysql

from reports.views import (
    _get_mysql_connection_kwargs,
    _norm_region,
    _normalize_keywords,
    _parse_date,
    _to_decimal,
)


REGION_FILTER_CHOICES = [
    ("all", "全部"),
    ("beijing", "北京"),
    ("tianjin", "天津"),
    ("hebei", "河北"),
    ("shanxi", "山西"),
    ("neimenggu", "内蒙古"),
    ("liaoning", "辽宁"),
    ("jilin", "吉林"),
    ("heilongjiang", "黑龙江"),
    ("shanghai", "上海"),
    ("jiangsu", "江苏"),
    ("zhejiang", "浙江"),
    ("anhui", "安徽"),
    ("fujian", "福建"),
    ("jiangxi", "江西"),
    ("shandong", "山东"),
    ("henan", "河南"),
    ("hubei", "湖北"),
    ("hunan", "湖南"),
    ("guangdong", "广东"),
    ("guangxi", "广西"),
    ("hainan", "海南"),
    ("chongqing", "重庆"),
    ("sichuan", "四川"),
    ("guizhou", "贵州"),
    ("yunnan", "云南"),
    ("xizang", "西藏"),
    ("shaanxi", "陕西"),
    ("gansu", "甘肃"),
    ("qinghai", "青海"),
    ("ningxia", "宁夏"),
    ("xinjiang", "新疆"),
    ("hongkong", "香港"),
    ("macau", "澳门"),
    ("taiwan", "台湾"),
]

REGION_CODE_TO_NAME = {
    code: name for code, name in REGION_FILTER_CHOICES if code != "all"
}

MYSQL_ANNOUNCEMENT_FROM_SQL = """
    FROM zc_wlsjcj_cjgg cjgg
    LEFT JOIN (
        SELECT
            GGWID AS link_wid,
            SUM(CJJE) AS total_amount,
            MIN(NULLIF(TRIM(region), '')) AS region_name
        FROM zc_wlsjcj_cjs
        WHERE GGWID IS NOT NULL AND GGWID <> ''
        GROUP BY GGWID
    ) cjs_by_ggwid ON cjs_by_ggwid.link_wid = cjgg.WID
    LEFT JOIN (
        SELECT
            WID AS link_wid,
            SUM(CJJE) AS total_amount,
            MIN(NULLIF(TRIM(region), '')) AS region_name
        FROM zc_wlsjcj_cjs
        WHERE WID IS NOT NULL AND WID <> ''
        GROUP BY WID
    ) cjs_by_wid ON cjs_by_wid.link_wid = cjgg.WID
"""

MYSQL_ANNOUNCEMENT_AMOUNT_SQL = (
    "COALESCE(cjs_by_ggwid.total_amount, cjs_by_wid.total_amount, 0)"
)
MYSQL_ANNOUNCEMENT_REGION_SQL = (
    "COALESCE(cjs_by_ggwid.region_name, cjs_by_wid.region_name, cjgg.CGRDZ, '')"
)


@dataclass
class MysqlPaginator:
    count: int
    per_page: int

    @property
    def num_pages(self):
        if self.count <= 0:
            return 1
        return ceil(self.count / self.per_page)

    @property
    def page_range(self):
        return range(1, self.num_pages + 1)


class MysqlPage:
    def __init__(self, object_list, number, paginator):
        self.object_list = object_list
        self.number = number
        self.paginator = paginator

    def __iter__(self):
        return iter(self.object_list)

    def __len__(self):
        return len(self.object_list)

    def has_previous(self):
        return self.number > 1

    def has_next(self):
        return self.number < self.paginator.num_pages

    def previous_page_number(self):
        return max(1, self.number - 1)

    def next_page_number(self):
        return min(self.paginator.num_pages, self.number + 1)

    def has_other_pages(self):
        return self.paginator.num_pages > 1


def _sanitize_page_number(raw_page):
    try:
        page_number = int(raw_page or 1)
    except (TypeError, ValueError):
        page_number = 1
    return max(page_number, 1)


def _format_amount(value):
    amount = _to_decimal(value)
    if amount is None:
        return ""
    return f"{amount:,.2f}"


def _map_mysql_announcement_card(row):
    amount_text = _format_amount(row.get("CJJE"))
    return {
        "wid": str(row.get("WID") or "").strip(),
        "title": str(row.get("GGBT") or row.get("XMMC") or "未命名公告").strip(),
        "url": str(row.get("GGURL") or "").strip(),
        "publish_date": _parse_date(row.get("GGFBRQ")),
        "buyer": str(row.get("CGRMC") or "").strip(),
        "region": _norm_region(row.get("region_name")),
        "budget_amount": amount_text,
        "transaction_amount": amount_text,
        "project_number": str(row.get("XMBH") or "").strip(),
    }


def _build_search_filter(search_query):
    keywords = _normalize_keywords(search_query)
    if not keywords:
        return "", []

    clauses = []
    params = []
    for keyword in keywords:
        like_value = f"%{keyword}%"
        clauses.append(
            "("
            "cjgg.GGBT LIKE %s OR "
            "cjgg.XMMC LIKE %s OR "
            "cjgg.BDXX LIKE %s OR "
            "cjgg.CGRMC LIKE %s OR "
            "cjgg.XMBH LIKE %s"
            ")"
        )
        params.extend([like_value, like_value, like_value, like_value, like_value])
    return "(" + " OR ".join(clauses) + ")", params


def _build_region_filter(region_code):
    if not region_code or region_code == "all":
        return "", []

    region_name = REGION_CODE_TO_NAME.get(region_code, "").strip()
    if not region_name:
        return "", []

    return f"{MYSQL_ANNOUNCEMENT_REGION_SQL} LIKE %s", [f"%{region_name}%"]


def _build_time_filter(time_filter):
    if not time_filter:
        return "", []

    today = date.today()
    thresholds = {
        "today": today,
        "month": today - timedelta(days=30),
        "three_months": today - timedelta(days=90),
        "six_months": today - timedelta(days=180),
        "year": today - timedelta(days=365),
    }
    threshold = thresholds.get(time_filter)
    if not threshold:
        return "", []

    return "cjgg.GGFBRQ >= %s", [threshold]


def _build_amount_filter(amount_range):
    ranges = {
        "below_1": (None, 10000),
        "1_10": (10000, 100000),
        "10_100": (100000, 1000000),
        "100_500": (1000000, 5000000),
        "above_500": (5000000, None),
    }
    lower_bound, upper_bound = ranges.get(amount_range, (None, None))
    clauses = []
    params = []

    if lower_bound is None and upper_bound is None:
        return "", []
    if lower_bound is not None:
        clauses.append(f"{MYSQL_ANNOUNCEMENT_AMOUNT_SQL} >= %s")
        params.append(lower_bound)
    if upper_bound is not None:
        clauses.append(f"{MYSQL_ANNOUNCEMENT_AMOUNT_SQL} < %s")
        params.append(upper_bound)
    return " AND ".join(clauses), params


def _build_mysql_filters(search_query="", region="", time_filter="", amount_range=""):
    clauses = []
    params = []

    for builder, value in (
        (_build_search_filter, search_query),
        (_build_region_filter, region),
        (_build_time_filter, time_filter),
        (_build_amount_filter, amount_range),
    ):
        clause, clause_params = builder(value)
        if clause:
            clauses.append(clause)
            params.extend(clause_params)

    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


def fetch_mysql_announcements_page(
    search_query="",
    region="",
    time_filter="",
    amount_range="",
    page=1,
    per_page=10,
):
    page_number = _sanitize_page_number(page)
    where_sql, params = _build_mysql_filters(
        search_query=search_query,
        region=region,
        time_filter=time_filter,
        amount_range=amount_range,
    )
    offset = (page_number - 1) * per_page

    count_sql = f"""
        SELECT COUNT(DISTINCT cjgg.WID) AS total_count
        {MYSQL_ANNOUNCEMENT_FROM_SQL}
        {where_sql}
    """
    data_sql = f"""
        SELECT
            cjgg.WID,
            cjgg.GGFBRQ,
            cjgg.GGBT,
            cjgg.GGURL,
            cjgg.XMBH,
            cjgg.CGRMC,
            {MYSQL_ANNOUNCEMENT_REGION_SQL} AS region_name,
            {MYSQL_ANNOUNCEMENT_AMOUNT_SQL} AS CJJE
        {MYSQL_ANNOUNCEMENT_FROM_SQL}
        {where_sql}
        ORDER BY cjgg.GGFBRQ DESC, cjgg.CJSJ DESC
        LIMIT %s OFFSET %s
    """

    connection = pymysql.connect(**_get_mysql_connection_kwargs())
    try:
        with connection.cursor() as cursor:
            cursor.execute(count_sql, params)
            total_count = int((cursor.fetchone() or {}).get("total_count") or 0)

            cursor.execute(data_sql, [*params, per_page, offset])
            rows = list(cursor.fetchall())
    finally:
        connection.close()

    paginator = MysqlPaginator(count=total_count, per_page=per_page)
    if page_number > paginator.num_pages:
        page_number = paginator.num_pages
    mapped_rows = [_map_mysql_announcement_card(row) for row in rows]
    return MysqlPage(mapped_rows, page_number, paginator), total_count


def fetch_mysql_title_suggestions(query, limit=10):
    keywords = _normalize_keywords(query)
    if not keywords:
        return []

    clauses = []
    params = []
    for keyword in keywords:
        like_value = f"%{keyword}%"
        clauses.append("(GGBT LIKE %s OR XMMC LIKE %s)")
        params.extend([like_value, like_value])

    sql = f"""
        SELECT GGBT
        FROM zc_wlsjcj_cjgg
        WHERE {' OR '.join(clauses)}
        GROUP BY GGBT
        ORDER BY MAX(GGFBRQ) DESC, MAX(CJSJ) DESC
        LIMIT %s
    """

    connection = pymysql.connect(**_get_mysql_connection_kwargs())
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, [*params, int(limit)])
            rows = cursor.fetchall()
    finally:
        connection.close()

    suggestions = []
    seen = set()
    for row in rows:
        title = str((row or {}).get("GGBT") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        suggestions.append(title)
    return suggestions[: int(limit)]
