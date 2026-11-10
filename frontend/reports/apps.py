from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reports'
    verbose_name = '需求调查报告'

    def ready(self):
        import reports.signals  # noqa: F401

