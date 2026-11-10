from django.contrib.auth import get_user_model
from django.test import TestCase
from wagtail.models import Page, Site

from .models import ReportIndexPage, ReportPage


class ReportIndexPageBehaviorTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="testpass123",
        )
        self.other_user = user_model.objects.create_user(
            username="other",
            email="other@example.com",
            password="testpass123",
        )

        root_page = Page.get_first_root_node()
        Site.objects.get_or_create(
            hostname="localhost",
            defaults={"root_page": root_page, "is_default_site": True},
        )

        self.index_page = ReportIndexPage(title="历史报告", slug="reports-test-index")
        root_page.add_child(instance=self.index_page)

        self.owner_report = ReportPage(
            title="人工智能报告",
            slug="owner-report",
            procurement_name="人工智能采购项目",
            content="这是属于 owner 的历史报告",
            owner=self.owner,
        )
        self.index_page.add_child(instance=self.owner_report)
        self.owner_report.save_revision().publish()

        self.public_report = ReportPage(
            title="公开大数据报告",
            slug="public-report",
            procurement_name="大数据治理项目",
            content="这是公开报告",
            is_public=True,
            owner=self.other_user,
        )
        self.index_page.add_child(instance=self.public_report)
        self.public_report.save_revision().publish()

    def test_search_filters_reports_within_history_page(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.index_page.url, {"search": "人工智能"})

        self.assertEqual(response.status_code, 200)
        reports = response.context["reports"].object_list
        self.assertEqual(list(reports), [self.owner_report])

    def test_owner_can_delete_own_report(self):
        self.client.force_login(self.owner)

        response = self.client.post(f"/reports/{self.owner_report.id}/delete/")

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ReportPage.objects.filter(id=self.owner_report.id).exists())

    def test_non_owner_cannot_delete_other_users_report(self):
        self.client.force_login(self.owner)

        response = self.client.post(f"/reports/{self.public_report.id}/delete/")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(ReportPage.objects.filter(id=self.public_report.id).exists())
