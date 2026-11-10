from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase

from . import services


class MysqlAnnouncementPageTests(SimpleTestCase):
    @mock.patch("announcements.services._get_mysql_connection_kwargs", return_value={})
    @mock.patch("announcements.services.pymysql.connect")
    def test_fetch_mysql_announcements_page_uses_joined_tables_and_default_page_shape(
        self,
        mock_connect,
        _mock_kwargs,
    ):
        fake_cursor = mock.MagicMock()
        fake_cursor.__enter__.return_value = fake_cursor
        fake_cursor.fetchone.return_value = {"total_count": 23}
        fake_cursor.fetchall.return_value = [
            {
                "WID": "GG-001",
                "GGFBRQ": "2026-01-09",
                "GGBT": "测试公告",
                "GGURL": "https://example.com/a",
                "XMBH": "XM-001",
                "CGRMC": "测试采购人",
                "region_name": "北京市",
                "CJJE": Decimal("12345.67"),
            }
        ]

        fake_connection = mock.MagicMock()
        fake_connection.cursor.return_value = fake_cursor
        mock_connect.return_value = fake_connection

        page, total_count = services.fetch_mysql_announcements_page(
            search_query="测试",
            page=1,
            per_page=10,
        )

        count_sql = fake_cursor.execute.call_args_list[0].args[0]
        data_sql = fake_cursor.execute.call_args_list[1].args[0]
        data_params = fake_cursor.execute.call_args_list[1].args[1]

        self.assertIn("FROM zc_wlsjcj_cjgg cjgg", count_sql)
        self.assertIn("FROM zc_wlsjcj_cjs", count_sql)
        self.assertIn("GGWID AS link_wid", data_sql)
        self.assertIn("WID AS link_wid", data_sql)
        self.assertEqual(data_params[-2:], [10, 0])
        self.assertEqual(total_count, 23)
        self.assertEqual(page.paginator.count, 23)
        self.assertEqual(page.paginator.num_pages, 3)
        self.assertTrue(page.has_next())

        first_item = list(page)[0]
        self.assertEqual(first_item["title"], "测试公告")
        self.assertEqual(first_item["buyer"], "测试采购人")
        self.assertEqual(first_item["region"], "北京")
        self.assertEqual(first_item["budget_amount"], "12,345.67")


class MysqlAnnouncementSuggestionTests(SimpleTestCase):
    @mock.patch("announcements.services._get_mysql_connection_kwargs", return_value={})
    @mock.patch("announcements.services.pymysql.connect")
    def test_fetch_mysql_title_suggestions_returns_distinct_titles(
        self,
        mock_connect,
        _mock_kwargs,
    ):
        fake_cursor = mock.MagicMock()
        fake_cursor.__enter__.return_value = fake_cursor
        fake_cursor.fetchall.return_value = [
            {"GGBT": "测试公告A"},
            {"GGBT": "测试公告A"},
            {"GGBT": "测试公告B"},
        ]

        fake_connection = mock.MagicMock()
        fake_connection.cursor.return_value = fake_cursor
        mock_connect.return_value = fake_connection

        suggestions = services.fetch_mysql_title_suggestions("测试", limit=5)

        sql, params = fake_cursor.execute.call_args.args
        self.assertIn("FROM zc_wlsjcj_cjgg", sql)
        self.assertIn("LIMIT %s", sql)
        self.assertEqual(params[-1], 5)
        self.assertEqual(suggestions, ["测试公告A", "测试公告B"])
