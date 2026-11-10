from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase

from . import views


class MysqlAnnouncementQueryTests(SimpleTestCase):
    @mock.patch("reports.views._get_mysql_connection_kwargs", return_value={})
    @mock.patch("reports.views.pymysql.connect")
    def test_query_brings_in_cjje_from_cjs(self, mock_connect, _mock_kwargs):
        fake_cursor = mock.MagicMock()
        fake_cursor.__enter__.return_value = fake_cursor
        fake_cursor.fetchall.return_value = [{"WID": "GG-1", "CJJE": Decimal("88.80"), "region_name": "北京"}]

        fake_connection = mock.MagicMock()
        fake_connection.cursor.return_value = fake_cursor
        mock_connect.return_value = fake_connection

        rows = views._query_mysql_announcements_by_keywords(["测试"], limit=5)

        sql, params = fake_cursor.execute.call_args.args
        self.assertIn("FROM zc_wlsjcj_cjgg cjgg", sql)
        self.assertIn("FROM zc_wlsjcj_cjs", sql)
        self.assertIn("GGWID AS link_wid", sql)
        self.assertIn("WID AS link_wid", sql)
        self.assertIn("MIN(NULLIF(TRIM(region), '')) AS region_name", sql)
        self.assertIn(
            "COALESCE(cjs_by_ggwid.region_name, cjs_by_wid.region_name, cjgg.CGRDZ, '') AS region_name",
            sql,
        )
        self.assertIn(
            "COALESCE(cjs_by_ggwid.CJJE, cjs_by_wid.CJJE) AS CJJE",
            sql,
        )
        self.assertEqual(params[-1], 5)
        self.assertEqual(rows, [{"WID": "GG-1", "CJJE": Decimal("88.80"), "region_name": "北京"}])


class MysqlAnnouncementMappingTests(SimpleTestCase):
    def test_map_mysql_announcement_uses_cjje_as_amount(self):
        mapped = views._map_mysql_announcement(
            {
                "GGBT": "测试公告",
                "CGRMC": "测试采购人",
                "GGURL": "https://example.com/a",
                "GGFBRQ": "2025-08-22",
                "XMBH": "XM-001",
                "region_name": "北京市",
                "CJJE": "12345.67",
            }
        )

        self.assertEqual(mapped["region"], "北京")
        self.assertEqual(mapped["budget_amount"], Decimal("12345.67"))
        self.assertEqual(mapped["transaction_amount"], Decimal("12345.67"))


class MysqlReportCardStatsTests(SimpleTestCase):
    @mock.patch("reports.views._get_mysql_connection_kwargs", return_value={})
    @mock.patch("reports.views.pymysql.connect")
    def test_query_report_card_stats_uses_count_and_sum(self, mock_connect, _mock_kwargs):
        fake_cursor = mock.MagicMock()
        fake_cursor.__enter__.return_value = fake_cursor
        fake_cursor.fetchone.side_effect = [
            {"announcement_count": 12, "buyer_count": 5},
            {"region_count": 3, "total_amount": Decimal("987654.32")},
        ]

        fake_connection = mock.MagicMock()
        fake_connection.cursor.return_value = fake_cursor
        mock_connect.return_value = fake_connection

        stats = views._query_mysql_report_card_stats(["测试"])

        first_sql = fake_cursor.execute.call_args_list[0].args[0]
        second_sql = fake_cursor.execute.call_args_list[1].args[0]

        self.assertIn("COUNT(*) AS announcement_count", first_sql)
        self.assertIn("COUNT(DISTINCT NULLIF(TRIM(matched.CGRMC), '')) AS buyer_count", first_sql)
        self.assertIn("COUNT(DISTINCT NULLIF(TRIM(cjs.region), '')) AS region_count", second_sql)
        self.assertIn("COALESCE(SUM(cjs.CJJE), 0) AS total_amount", second_sql)
        self.assertEqual(stats["stat_buyer_count"], "5 家")
        self.assertEqual(stats["stat_region_count"], "3 个")
        self.assertEqual(stats["stat_budget_total"], "987,654.32 元")
        self.assertEqual(stats["stat_transaction_total"], "987,654.32 元")
        self.assertEqual(stats["stat_announcement_count"], "12 条")

class MysqlRegionDistributionTests(SimpleTestCase):
    @mock.patch("reports.views._get_mysql_connection_kwargs", return_value={})
    @mock.patch("reports.views.pymysql.connect")
    def test_query_region_distribution_aggregates_by_province(self, mock_connect, _mock_kwargs):
        fake_cursor = mock.MagicMock()
        fake_cursor.__enter__.return_value = fake_cursor
        fake_cursor.fetchall.return_value = [
            {"buyer_name": "\u91c7\u8d2d\u5355\u4f4dA", "region_name": "\u5317\u4eac\u5e02"},
            {"buyer_name": "\u91c7\u8d2d\u5355\u4f4dA", "region_name": "\u5317\u4eac"},
            {"buyer_name": "\u91c7\u8d2d\u5355\u4f4dB", "region_name": "\u5317\u4eac"},
            {"buyer_name": "\u91c7\u8d2d\u5355\u4f4dC", "region_name": "\u4e0a\u6d77\u5e02"},
            {"buyer_name": "\u91c7\u8d2d\u5355\u4f4dD", "region_name": "\u5168\u56fd"},
        ]

        fake_connection = mock.MagicMock()
        fake_connection.cursor.return_value = fake_cursor
        mock_connect.return_value = fake_connection

        distribution = views._query_mysql_region_distribution(["\u6d4b\u8bd5"])

        sql = fake_cursor.execute.call_args.args[0]
        self.assertIn("matched.CGRMC AS buyer_name", sql)
        self.assertIn("WID AS link_wid", sql)
        self.assertIn("GGWID AS link_wid", sql)
        self.assertEqual(
            distribution,
            [
                {"name": "\u5317\u4eac", "value": 2},
                {"name": "\u4e0a\u6d77", "value": 1},
            ],
        )


class MysqlTopBuyersTests(SimpleTestCase):
    @mock.patch("reports.views._get_mysql_connection_kwargs", return_value={})
    @mock.patch("reports.views.pymysql.connect")
    def test_query_top_buyers_uses_requested_aggregation(self, mock_connect, _mock_kwargs):
        fake_cursor = mock.MagicMock()
        fake_cursor.__enter__.return_value = fake_cursor
        fake_cursor.fetchall.return_value = [
            {
                "buyer_name": "\u6d4b\u8bd5\u91c7\u8d2d\u4ebaA",
                "region_name": "\u5317\u4eac\u5e02",
                "transaction_amount": Decimal("2345.60"),
            },
            {
                "buyer_name": "\u6d4b\u8bd5\u91c7\u8d2d\u4ebaA",
                "region_name": "\u5317\u4eac",
                "transaction_amount": "100.00",
            },
            {
                "buyer_name": "\u6d4b\u8bd5\u91c7\u8d2d\u4ebaB",
                "region_name": "\u4e0a\u6d77\u5e02",
                "transaction_amount": "100.00",
            },
            {
                "buyer_name": "\u6d4b\u8bd5\u91c7\u8d2d\u4ebaB",
                "region_name": "\u6d59\u6c5f\u7701",
                "transaction_amount": "90.00",
            },
        ]

        fake_connection = mock.MagicMock()
        fake_connection.cursor.return_value = fake_cursor
        mock_connect.return_value = fake_connection

        rows = views._query_mysql_top_buyers(["\u6d4b\u8bd5"], limit=10)

        sql, params = fake_cursor.execute.call_args.args
        self.assertIn("FROM zc_wlsjcj_cjgg cjgg", sql)
        self.assertIn("WID AS link_wid", sql)
        self.assertIn("GGWID AS link_wid", sql)
        self.assertIn(
            "COALESCE(cjs_by_wid.total_amount, cjs_by_ggwid.total_amount, 0) AS transaction_amount",
            sql,
        )
        self.assertEqual(len(params), 3)
        self.assertEqual(rows[0]["region"], "\u5317\u4eac")
        self.assertEqual(rows[0]["project_count"], 2)
        self.assertEqual(rows[0]["transaction_amount"], "2,445.60")
        self.assertEqual(rows[1]["region"], "-")
        self.assertEqual(rows[1]["project_count"], 2)


class ProvinceExtractionTests(SimpleTestCase):
    def test_extract_province_from_text_handles_extra_words(self):
        self.assertEqual(
            views._extract_province_from_text("该采购单位位于北京市"),
            "\u5317\u4eac",
        )


class TopBuyerRegionFillTests(SimpleTestCase):
    @mock.patch("reports.views._infer_buyer_region_with_llm")
    def test_fill_top_buyer_regions_only_updates_displayed_missing_rows(self, mock_infer):
        mock_infer.side_effect = lambda buyer_name: {
            "采购单位A": "\u5317\u4eac",
            "采购单位B": "",
        }.get(buyer_name, "")

        rows = [
            {"buyer_name": "采购单位A", "region": "-", "project_count": 5, "transaction_amount": "1.00"},
            {"buyer_name": "采购单位B", "region": "-", "project_count": 4, "transaction_amount": "2.00"},
            {"buyer_name": "采购单位C", "region": "\u4e0a\u6d77", "project_count": 3, "transaction_amount": "3.00"},
        ] + [
            {"buyer_name": f"采购单位{i}", "region": "\u6c5f\u82cf", "project_count": 1, "transaction_amount": "0.00"}
            for i in range(4, 11)
        ] + [
            {"buyer_name": "采购单位11", "region": "-", "project_count": 1, "transaction_amount": "0.00"}
        ]

        filled_rows = views._fill_top_buyer_regions_with_llm(rows, displayed_limit=10)

        self.assertEqual(filled_rows[0]["region"], "\u5317\u4eac")
        self.assertEqual(filled_rows[1]["region"], "-")
        self.assertEqual(filled_rows[2]["region"], "\u4e0a\u6d77")
        self.assertEqual(filled_rows[10]["region"], "-")
        mock_infer.assert_any_call("采购单位A")
        mock_infer.assert_any_call("采购单位B")
        self.assertNotIn(mock.call("采购单位11"), mock_infer.call_args_list)
