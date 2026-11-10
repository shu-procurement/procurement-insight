from django.db import models
from django import forms
from wagtail.models import Page, Orderable
from wagtail.fields import RichTextField
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtail.search import index
from django.core.paginator import Paginator
from django.db.models import Q
from modelcluster.fields import ParentalKey
from django.utils import timezone
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import os
import datetime
import re


# 报告分类选项
REPORT_CATEGORY_CHOICES = [
    ('default', '默认'),
    ('analysis', '调查分析'),
    ('ai', '人工智能'),
    ('bigdata', '大数据'),
    ('scope', '中成氏范围'),
    ('opinion', '舆论研究'),
    ('iot', '物联'),
    ('life', '生活'),
]

PROVINCE_CHOICES = [
    ('全国', '全国'),
    ('北京', '北京'),
    ('天津', '天津'),
    ('河北', '河北'),
    ('山西', '山西'),
    ('内蒙古', '内蒙古'),
    ('辽宁', '辽宁'),
    ('吉林', '吉林'),
    ('黑龙江', '黑龙江'),
    ('上海', '上海'),
    ('江苏', '江苏'),
    ('浙江', '浙江'),
    ('安徽', '安徽'),
    ('福建', '福建'),
    ('江西', '江西'),
    ('山东', '山东'),
    ('河南', '河南'),
    ('湖北', '湖北'),
    ('湖南', '湖南'),
    ('广东', '广东'),
    ('广西', '广西'),
    ('海南', '海南'),
    ('重庆', '重庆'),
    ('四川', '四川'),
    ('贵州', '贵州'),
    ('云南', '云南'),
    ('西藏', '西藏'),
    ('陕西', '陕西'),
    ('甘肃', '甘肃'),
    ('青海', '青海'),
    ('宁夏', '宁夏'),
    ('新疆', '新疆'),
    ('香港', '香港'),
    ('澳门', '澳门'),
    ('台湾', '台湾'),
]


class ReportIndexPage(Page):
    """闇€姹傝皟鏌ユ姤鍛婂垪琛ㄩ〉"""
    intro = RichTextField(blank=True, verbose_name='浠嬬粛')

    content_panels = Page.content_panels + [
        FieldPanel('intro'),
    ]

    class Meta:
        verbose_name = '闇€姹傝皟鏌ユ姤鍛婂垪琛ㄩ〉'

    def get_context(self, request):
        context = super().get_context(request)
        
        # 鑾峰彇鎵€鏈夋姤鍛?
        reports = ReportPage.objects.live().child_of(self)

        # Filter by owner (User-specific visibility)
        if request.user.is_authenticated:
            if request.user.is_superuser:
                pass  # 瓒呯骇绠＄悊鍛樼湅鍒版墍鏈夋姤鍛?
            else:
                # 鏅€氱敤鎴风湅鍒帮細鑷繁鐨勬姤鍛?+ 鍏叡鎶ュ憡
                from django.db.models import Q
                reports = reports.filter(
                    Q(owner=request.user) | Q(is_public=True)
                )
        else:
            # 鏈櫥褰曠敤鎴风湅涓嶅埌鎶ュ憡
            reports = ReportPage.objects.none()
        
        # 鍒嗙被绛涢€?
        category = request.GET.get('category')
        if category and category != 'default':
            reports = reports.filter(category=category)
        
        # 鎼滅储
        search_query = (request.GET.get('search') or '').strip()
        if search_query:
            reports = reports.filter(
                Q(procurement_name__icontains=search_query)
                | Q(title__icontains=search_query)
                | Q(analysis_keywords__icontains=search_query)
                | Q(summary__icontains=search_query)
                | Q(content__icontains=search_query)
            ).order_by('-analysis_time')
        else:
            # 浠呭湪闈炴悳绱㈡ā寮忎笅鎺掑簭锛堟悳绱㈢粨鏋滄寜鐩稿叧鎬ф帓鍒楋級
            reports = reports.order_by('-analysis_time')
        
        # 鍒嗛〉
        paginator = Paginator(reports, 20)  # 姣忛〉20鏉?
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        context['reports'] = page_obj
        try:
            context['total_count'] = reports.count()
        except (AttributeError, TypeError):
            context['total_count'] = len(reports)
        context['search_query'] = search_query
        
        return context


class HistoricalProject(Orderable):
    page = ParentalKey('ReportPage', on_delete=models.CASCADE, related_name='historical_projects')
    project_name = models.CharField(max_length=255, verbose_name='椤圭洰鍚嶇О', blank=True, null=True)
    procurement_method = models.CharField(max_length=100, verbose_name='閲囪喘鏂瑰紡', blank=True, null=True)
    procurement_time = models.DateField(verbose_name='閲囪喘鏃堕棿', blank=True, null=True)
    procurement_unit = models.CharField(max_length=255, verbose_name='閲囪喘鍗曚綅', blank=True, null=True)
    budget_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='棰勭畻(涓囧厓)', blank=True, null=True)

    transaction_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='鎴愪氦(涓囧厓)', blank=True, null=True)
    detail_link = models.URLField(verbose_name='璇︽儏閾炬帴', blank=True, null=True)

    panels = [
        FieldPanel('project_name'),
        FieldPanel('procurement_method'),
        FieldPanel('procurement_time'),
        FieldPanel('procurement_unit'),
        FieldPanel('budget_amount'),
        FieldPanel('transaction_amount'),
        FieldPanel('detail_link'),
    ]


class ReportAnnouncement(Orderable):
    page = ParentalKey('ReportPage', on_delete=models.CASCADE, related_name='report_announcements')
    title = models.CharField(max_length=255, verbose_name='鍏憡鏍囬')
    url = models.URLField(verbose_name='鍏憡閾炬帴', blank=True, null=True)
    publish_date = models.DateField(verbose_name='鍙戝竷鏃堕棿', blank=True, null=True)
    
    ANNOUNCEMENT_TYPES = [
        ('bidding', '鎷涙爣鍏憡'),
        ('result', '缁撴灉鍏憡'),
        ('change', '鍙樻洿鍏憡'),
        ('termination', '缁堟/搴熸爣鍏憡'),
        ('contract', '鍚堝悓鍏ず'),
        ('acceptance', '楠屾敹鍏ず'),
        ('other', '鍏朵粬鍏憡'),
    ]
    announcement_type = models.CharField(max_length=50, choices=ANNOUNCEMENT_TYPES, default='bidding', verbose_name='鍏憡绫诲瀷')
    
    region = models.CharField(max_length=50, choices=PROVINCE_CHOICES, default='全国', verbose_name='地区')
    
    budget_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='棰勭畻閲戦(涓囧厓)', blank=True, null=True)
    transaction_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='鎴愪氦閲戦(涓囧厓)', blank=True, null=True)
    buyer = models.CharField(max_length=255, verbose_name='閲囪喘鍗曚綅', blank=True, null=True)
    project_number = models.CharField(max_length=100, verbose_name='椤圭洰缂栧彿', blank=True, null=True)

    panels = [
        FieldPanel('title'),
        FieldPanel('url'),
        FieldPanel('publish_date'),
        FieldPanel('announcement_type'),
        FieldPanel('region'),
        FieldPanel('budget_amount'),
        FieldPanel('transaction_amount'),
        FieldPanel('buyer'),
        FieldPanel('project_number'),
    ]



class ReportContract(Orderable):
    page = ParentalKey('ReportPage', on_delete=models.CASCADE, related_name='report_contracts')
    title = models.CharField(max_length=255, verbose_name='鍚堝悓鍚嶇О')
    url = models.URLField(verbose_name='璇︽儏閾炬帴', blank=True, null=True)
    publish_date = models.DateField(verbose_name='鍙戝竷鏃堕棿', blank=True, null=True)
    
    region = models.CharField(max_length=50, choices=PROVINCE_CHOICES, default='全国', verbose_name='地区')
    city = models.CharField(max_length=50, verbose_name='鍩庡競', blank=True, null=True)
    
    budget_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='棰勭畻閲戦(涓囧厓)', blank=True, null=True)
    transaction_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='鎴愪氦閲戦(涓囧厓)', blank=True, null=True)
    buyer = models.CharField(max_length=255, verbose_name='閲囪喘鍗曚綅', blank=True, null=True)

    panels = [
        FieldPanel('title'),
        FieldPanel('url'),
        FieldPanel('publish_date'),
        FieldPanel('region'),
        FieldPanel('city'),
        FieldPanel('budget_amount'),
        FieldPanel('transaction_amount'),
        FieldPanel('buyer'),
    ]


class ReportBiddingDocument(Orderable):
    page = ParentalKey('ReportPage', on_delete=models.CASCADE, related_name='report_documents')
    title = models.CharField(max_length=255, verbose_name='鏂囦欢鏍囬', blank=True, default='')
    source = models.CharField(max_length=100, verbose_name='来源', default='山东政府采购网', blank=True)
    upload_time = models.DateField(verbose_name='涓婁紶鏃堕棿', default=datetime.date.today)
    file = models.FileField(upload_to='reports/documents/', verbose_name='鏂囦欢', blank=True)
    
    DOC_TYPES = [
        ('procurement', '閲囪喘鏂囦欢'),
        ('contract', '鍚堝悓鏂囦欢'),
        ('acceptance', '楠屾敹鏂囦欢'),
        ('other', '鍏朵粬鏂囦欢'),
    ]
    doc_type = models.CharField(max_length=50, choices=DOC_TYPES, default='procurement', verbose_name='鏂囦欢绫诲瀷')

    def clean(self):
        print(f"DEBUG: ReportBiddingDocument clean() called. Title: {self.title}, File: {self.file}")
        super().clean()

    def save(self, *args, **kwargs):
        # Auto-fill title from filename if empty
        if not self.title and self.file:
            try:
                # Get the filename
                filename = os.path.basename(self.file.name)
                # Ensure it's not too long for the field
                if len(filename) > 255:
                    filename = filename[:255]
                self.title = filename
            except Exception:
                pass
        super().save(*args, **kwargs)

    @property
    def filename(self):
        import os
        return os.path.basename(self.file.name)

    panels = [
        FieldPanel('title'),
        FieldPanel('source'),
        FieldPanel('upload_time'),
        FieldPanel('file'),
        FieldPanel('doc_type'),
    ]


class OngoingProject(Orderable):
    page = ParentalKey('ReportPage', on_delete=models.CASCADE, related_name='ongoing_projects')
    project_name = models.CharField(max_length=255, verbose_name='椤圭洰鍚嶇О', blank=True, null=True)
    bid_opening_time = models.DateField(verbose_name='开标时间', blank=True, null=True)
    procurement_unit = models.CharField(max_length=255, verbose_name='閲囪喘鍗曚綅', blank=True, null=True)
    budget_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='棰勭畻(涓囧厓)', blank=True, null=True)
    detail_link = models.URLField(verbose_name='璇︽儏閾炬帴', blank=True, null=True)

    panels = [
        FieldPanel('project_name'),
        FieldPanel('bid_opening_time'),
        FieldPanel('procurement_unit'),
        FieldPanel('budget_amount'),
        FieldPanel('detail_link'),
    ]


class PurchaseIntention(Orderable):
    page = ParentalKey('ReportPage', on_delete=models.CASCADE, related_name='purchase_intentions')
    project_name = models.CharField(max_length=255, verbose_name='椤圭洰鍚嶇О')
    budget_amount = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='棰勭畻(涓囧厓)', blank=True, null=True)
    
    province = models.CharField(max_length=50, choices=PROVINCE_CHOICES, default='全国', verbose_name='地区（省份）')
    city = models.CharField(max_length=50, verbose_name='鍩庡競', blank=True, null=True)
    
    procurement_category = models.CharField(max_length=100, verbose_name='閲囪喘鍝佺洰', blank=True, null=True)
    procurement_unit = models.CharField(max_length=255, verbose_name='閲囪喘鍗曚綅', blank=True, null=True)
    publish_time = models.DateField(verbose_name='鍙戝竷鏃堕棿', blank=True, null=True)
    content = models.TextField(verbose_name='閲囪喘鍐呭', blank=True, null=True)
    detail_url = models.URLField(verbose_name='璇︽儏閾炬帴', blank=True, null=True)

    panels = [
        FieldPanel('project_name'),
        FieldPanel('budget_amount'),
        FieldPanel('province'),
        FieldPanel('city'),
        FieldPanel('procurement_category'),
        FieldPanel('procurement_unit'),
        FieldPanel('publish_time'),
        FieldPanel('content'),
        FieldPanel('detail_url'),
    ]

def _parse_stat_count_value(raw_value):
    digits = "".join(ch for ch in str(raw_value or "") if ch.isdigit())
    try:
        return int(digits) if digits else 0
    except ValueError:
        return 0


def _split_analysis_keywords(raw_keywords):
    if isinstance(raw_keywords, (list, tuple, set)):
        raw_items = raw_keywords
    else:
        raw_items = [raw_keywords]

    keywords = []
    seen = set()
    for item in raw_items:
        text = str(item or "").strip()
        if not text:
            continue
        for token in re.split("[\u3001,\uff0c;\uff1b\\n\\r\\t]+", text):
            keyword = token.strip()
            if not keyword or keyword in seen:
                continue
            seen.add(keyword)
            keywords.append(keyword[:100])
    return keywords[:50]


def _format_decimal_amount(value):
    try:
        amount = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        amount = Decimal("0")
    return f"{amount:,.2f}", amount


class TopBuyerAnalysis(Orderable):
    """各单位采购情况分析 (Top 5)"""
    page = ParentalKey('ReportPage', related_name='top_buyers')
    buyer_name = models.CharField(max_length=255, verbose_name="采购单位")
    region = models.CharField(max_length=100, verbose_name="所属地区", blank=True, default="-")
    project_count = models.IntegerField(verbose_name="项目数(项)", default=0)
    budget_amount = models.CharField(max_length=50, verbose_name="预算金额(万元)", blank=True, default="-")
    transaction_amount = models.CharField(max_length=50, verbose_name="成交金额(万元)", blank=True, default="-")

    panels = [
        FieldPanel('buyer_name'),
        FieldPanel('region'),
        FieldPanel('project_count'),
        FieldPanel('budget_amount'),
        FieldPanel('transaction_amount'),
    ]


class RegionPurchaseData(Orderable):
    """各地区采购项目数据（用于图表展示）"""
    page = ParentalKey('ReportPage', related_name='region_purchase_data')
    region_name = models.CharField(max_length=50, verbose_name="地区名称", help_text="例如：浙江、湖南、四川")
    purchase_amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="采购金额(万元)", default=0)
    project_count = models.IntegerField(verbose_name="项目数量(个)", default=0)

    panels = [
        FieldPanel('region_name'),
        FieldPanel('purchase_amount'),
        FieldPanel('project_count'),
    ]

    class Meta(Orderable.Meta):
        verbose_name = "地区采购数据"


class TopSupplierShare(Orderable):
    """成交前5名供应商市场份额占比"""
    page = ParentalKey('ReportPage', related_name='top_suppliers')
    supplier_name = models.CharField(max_length=255, verbose_name="供应商名称")
    project_count_percent = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="项目数量占比(%)", default=0)
    transaction_amount_percent = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="成交金额占比(%)", default=0)

    panels = [
        FieldPanel('supplier_name'),
        FieldPanel('project_count_percent'),
        FieldPanel('transaction_amount_percent'),
    ]

    class Meta(Orderable.Meta):
        verbose_name = "供应商市场份额"


class ProcurementMethodShare(Orderable):
    """各采购方式项目数量占比"""
    page = ParentalKey('ReportPage', related_name='procurement_methods')
    method_name = models.CharField(max_length=100, verbose_name="采购方式", help_text="例如：公开招标、竞争性磋商、单一来源")
    project_count_percent = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="项目数量占比(%)", default=0)

    panels = [
        FieldPanel('method_name'),
        FieldPanel('project_count_percent'),
    ]

    class Meta(Orderable.Meta):
        verbose_name = "采购方式占比"


class ReportPage(Page):
    template = "reports/report_page.html"
    
    # Reports fields
    """闇€姹傝皟鏌ユ姤鍛婅鎯呴〉"""

    """闇€姹傝皟鏌ユ姤鍛婅鎯呴〉"""
    serial_number = models.CharField(max_length=50, blank=True, null=True, verbose_name='搴忓彿')
    procurement_name = models.TextField(verbose_name='拟采购名称')
    analysis_keywords = models.TextField(blank=True, default='', verbose_name='分析关键词')
    
    ANALYSIS_CHOICES = [
        ('分析', '分析'),
    ]
    analysis_type = models.CharField(
        max_length=50,
        choices=ANALYSIS_CHOICES,
        default='分析',
        verbose_name='分析'
    )
    analysis_time = models.DateTimeField(auto_now_add=True, verbose_name='鍒嗘瀽鏃堕棿')
    category = models.CharField(
        max_length=20,
        choices=REPORT_CATEGORY_CHOICES,
        default='default',
        verbose_name='鍒嗙被'
    )
    
    # New analysis text fields
    market_supply_analysis = models.TextField(blank=True, verbose_name='市场供给分析')
    market_trend_analysis = models.TextField(blank=True, verbose_name='市场交易趋势')
    ai_summary_analysis = models.TextField(blank=True, verbose_name='AI总结分析')

    # 市场供给分析 - 统计卡片字段
    stat_buyer_count = models.CharField(max_length=50, blank=True, default='', verbose_name='采购单位数量', help_text='例如：268 家')
    stat_region_count = models.CharField(max_length=50, blank=True, default='', verbose_name='采购地区数量', help_text='例如：31 个地区')
    stat_budget_total = models.CharField(max_length=50, blank=True, default='', verbose_name='预算金额', help_text='例如：153,674 万元')
    stat_transaction_total = models.CharField(max_length=50, blank=True, default='', verbose_name='成交总额', help_text='例如：125,809 万元')
    stat_announcement_count = models.CharField(max_length=50, blank=True, default='', verbose_name='采购公告数量', help_text='例如：4235 条')

    summary = RichTextField(blank=True, verbose_name='报告摘要')
    content = RichTextField(blank=True, verbose_name='报告内容')
    is_public = models.BooleanField(
        default=False,
        verbose_name='鍏叡鎶ュ憡',
        help_text='勾选后所有用户都能看到此报告（管理员修改后所有人同步更新）'
    )

    pdf_file = models.FileField(
        upload_to='reports/pdfs/',
        blank=True,
        verbose_name='PDF鏂囦欢'
    )
    
    # 鎼滅储閰嶇疆
    search_fields = Page.search_fields + [
        index.SearchField('procurement_name'),
        index.SearchField('summary'),
        index.SearchField('content'),
        index.FilterField('category'),
    ]

    content_panels = Page.content_panels + [
        FieldPanel('is_public'),
        FieldPanel('serial_number'),
        FieldPanel('procurement_name'),
        FieldPanel('pdf_file'),
        FieldPanel('content'),
        InlinePanel('report_announcements', label="采购公告"),
        InlinePanel('report_contracts', label="采购合同"),
        InlinePanel('report_documents', label="招标文件"),
        InlinePanel('purchase_intentions', label="采购意向"),
        InlinePanel('historical_projects', label="历史成交项目"),
        InlinePanel('ongoing_projects', label="进行中项目"),
        InlinePanel('top_buyers', label="各单位采购情况分析 (前5名)"),
        InlinePanel('region_purchase_data', label="各地区采购数据 (图表)"),
        InlinePanel('top_suppliers', label="供应商市场份额占比 (前5名)"),
        InlinePanel('procurement_methods', label="采购方式占比"),
        FieldPanel('market_supply_analysis'),
        FieldPanel('market_trend_analysis'),
        FieldPanel('ai_summary_analysis'),
        FieldPanel('stat_buyer_count'),
        FieldPanel('stat_region_count'),
        FieldPanel('stat_budget_total'),
        FieldPanel('stat_transaction_total'),
        FieldPanel('stat_announcement_count'),
    ]

    def get_context(self, request):
        context = super().get_context(request)
        announcements = self.report_announcements.all().order_by('-publish_date', '-id')
        all_announcements = list(self.report_announcements.all())
        context['announcements_page'] = Paginator(announcements, 15).get_page(
            request.GET.get('ann_page', 1)
        )
        try:
            from announcements.services import REGION_FILTER_CHOICES

            context['region_choices'] = REGION_FILTER_CHOICES
        except Exception:
            context['region_choices'] = [('all', '全部')] + [
                (value, label)
                for value, label in PROVINCE_CHOICES
                if value != '全国'
            ]
        keyword_fallback = (self.procurement_name or self.title or '').strip()
        report_keywords = _split_analysis_keywords(self.analysis_keywords)
        if not report_keywords and keyword_fallback:
            report_keywords = [keyword_fallback]

        stat_fields = (
            'stat_buyer_count',
            'stat_region_count',
            'stat_budget_total',
            'stat_transaction_total',
            'stat_announcement_count',
        )
        if not all(getattr(self, field_name, '') for field_name in stat_fields):
            try:
                from .views import _query_mysql_report_card_stats

                card_stats = _query_mysql_report_card_stats(
                    report_keywords,
                    fallback_query=keyword_fallback,
                )
                for field_name, field_value in card_stats.items():
                    if not getattr(self, field_name, ''):
                        setattr(self, field_name, field_value)
            except Exception:
                pass

        top_buyer_rows = []
        try:
            from .views import _query_mysql_top_buyers

            top_buyer_rows = _query_mysql_top_buyers(
                report_keywords,
                fallback_query=keyword_fallback,
                limit=10,
            )
        except Exception:
            top_buyer_rows = []

        if not top_buyer_rows:
            buyer_totals = {}
            for announcement in all_announcements:
                buyer_name = (announcement.buyer or '').strip()
                if not buyer_name:
                    continue

                buyer_entry = buyer_totals.setdefault(
                    buyer_name,
                    {
                        'buyer_name': buyer_name,
                        'regions': set(),
                        'project_count': 0,
                        'transaction_amount_value': Decimal('0'),
                    },
                )
                buyer_entry['project_count'] += 1

                region_name = (announcement.region or '').strip()
                if region_name and region_name != '全国':
                    buyer_entry['regions'].add(region_name)

                _, amount_value = _format_decimal_amount(announcement.transaction_amount)
                buyer_entry['transaction_amount_value'] += amount_value

            top_buyer_rows = sorted(
                buyer_totals.values(),
                key=lambda item: (
                    -item['project_count'],
                    -item['transaction_amount_value'],
                    item['buyer_name'],
                ),
            )[:10]

            normalized_rows = []
            for item in top_buyer_rows:
                amount_display, amount_value = _format_decimal_amount(
                    item['transaction_amount_value']
                )
                regions = sorted(item['regions'])
                normalized_rows.append(
                    {
                        'buyer_name': item['buyer_name'],
                        'region': regions[0] if len(regions) == 1 else '-',
                        'project_count': item['project_count'],
                        'transaction_amount_value': amount_value,
                        'transaction_amount': amount_display,
                    }
                )
            top_buyer_rows = normalized_rows

        try:
            from .views import _fill_top_buyer_regions_with_llm

            top_buyer_rows = _fill_top_buyer_regions_with_llm(
                top_buyer_rows,
                displayed_limit=10,
            )
        except Exception:
            pass

        context['top_buyer_rows'] = top_buyer_rows

        buyer_region_distribution = []
        buyer_region_total_count = 0
        buyer_region_unit = '\u5bb6'
        try:
            from .views import _query_mysql_region_distribution

            buyer_region_distribution = _query_mysql_region_distribution(
                report_keywords,
                fallback_query=keyword_fallback,
            )
        except Exception:
            buyer_region_distribution = []

        if buyer_region_distribution:
            buyer_region_total_count = sum(
                int(item.get('value') or 0) for item in buyer_region_distribution
            )
        else:
            unique_buyers = set()
            buyer_region_map = defaultdict(set)
            for announcement in all_announcements:
                buyer_name = (announcement.buyer or '').strip()
                if not buyer_name:
                    continue

                unique_buyers.add(buyer_name)
                region_name = (announcement.region or '').strip()
                if region_name and region_name != '\u5168\u56fd':
                    buyer_region_map[region_name].add(buyer_name)

            buyer_region_distribution = sorted(
                [
                    {
                        'name': region_name,
                        'value': len(region_buyers),
                    }
                    for region_name, region_buyers in buyer_region_map.items()
                    if region_buyers
                ],
                key=lambda item: (-item['value'], item['name']),
            )
            buyer_region_total_count = len(unique_buyers) or _parse_stat_count_value(
                self.stat_buyer_count
            )
            buyer_region_unit = '\u5bb6'

        buyer_region_top_five = buyer_region_distribution[:5]
        buyer_region_keyword_display = (
            '\u3001'.join(report_keywords)
            or keyword_fallback
            or '\u76f8\u5173\u5173\u952e\u8bcd'
        )

        if buyer_region_top_five:
            buyer_region_top_five_text = '\u3001'.join(
                f"{item['name']}\uff08{item['value']}{buyer_region_unit}\uff09"
                for item in buyer_region_top_five
            )
            buyer_region_summary_text = (
                f"\u5173\u4e8e{buyer_region_keyword_display}\u7684\u5206\u6790\u62a5\u544a\uff0c"
                f"\u57fa\u4e8e\u6269\u5145\u5173\u952e\u8bcd\u5339\u914d\u5230\u7684\u62db\u6807\u6570\u636e\uff0c"
                f"\u5404\u7701\u4efd\u5171\u7edf\u8ba1{buyer_region_total_count}{buyer_region_unit}\uff0c"
                f"\u524d\u4e94\u4e2a\u5730\u533a\u5206\u522b\u4e3a{buyer_region_top_five_text}\u3002"
            )
        else:
            buyer_region_top_five_text = '\u6682\u65e0\u660e\u786e\u7701\u4efd\u6570\u636e'
            buyer_region_summary_text = (
                f"\u5173\u4e8e{buyer_region_keyword_display}\u7684\u5206\u6790\u62a5\u544a\uff0c"
                "\u5f53\u524d\u6570\u636e\u6682\u672a\u5f62\u6210\u660e\u663e\u7684\u7701\u4efd\u5206\u5e03\u3002"
            )

        context['buyer_region_keyword_display'] = buyer_region_keyword_display
        context['buyer_region_total_count'] = buyer_region_total_count
        context['buyer_region_map_data'] = buyer_region_distribution
        context['buyer_region_map_max'] = max(
            [item['value'] for item in buyer_region_distribution],
            default=1,
        )
        context['buyer_region_top_five'] = buyer_region_top_five
        context['buyer_region_top_five_text'] = buyer_region_top_five_text
        context['buyer_region_summary_text'] = buyer_region_summary_text

        region_amount_chart_data = []
        try:
            from .views import _query_mysql_region_amounts

            region_amount_chart_data = _query_mysql_region_amounts(
                report_keywords,
                fallback_query=keyword_fallback,
            )
        except Exception:
            region_amount_chart_data = []

        if not region_amount_chart_data:
            fallback_amounts = defaultdict(Decimal)
            for item in self.region_purchase_data.all():
                region_name = (item.region_name or '').strip()
                if not region_name or region_name == '全国':
                    continue
                fallback_amounts[region_name] += (
                    getattr(item, 'purchase_amount', None) or Decimal('0')
                )

            region_amount_chart_data = sorted(
                [
                    {
                        'name': name,
                        'value': float(amount),
                    }
                    for name, amount in fallback_amounts.items()
                ],
                key=lambda item: (-item['value'], item['name']),
            )

        context['region_amount_chart_data'] = region_amount_chart_data
        return context


    class Meta:
        verbose_name = '需求调查报告'

    parent_page_types = ['reports.ReportIndexPage']

