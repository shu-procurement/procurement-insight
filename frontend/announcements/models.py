from django.db import models
import datetime
from wagtail.models import Page
from wagtail.fields import RichTextField
from wagtail.admin.panels import FieldPanel
from wagtail.search import index
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from django.utils.html import mark_safe
import re

from .services import REGION_FILTER_CHOICES, fetch_mysql_announcements_page


# 公告类型选择
ANNOUNCEMENT_TYPE_CHOICES = [
    ('winning_bid', '中标公告'),
    ('public_bidding', '公开招标公告'),
    ('competitive_negotiation', '竞争性谈判公告'),
    ('correction', '更正公告'),
    ('competitive_consultation', '竞争性磋商公告'),
    ('transaction', '成交公告'),
    ('other', '其他公告'),
    ('termination', '终止公告'),
    ('qualification', '资格预审公告'),
    ('inquiry', '询价公告'),
]

# 地区选择（省级）
REGION_CHOICES = [
    ('all', '全部'),
    ('beijing', '北京'),
    ('tianjin', '天津'),
    ('hebei', '河北'),
    ('shanxi', '山西'),
    ('neimenggu', '内蒙古'),
    ('liaoning', '辽宁'),
    ('jilin', '吉林'),
    ('heilongjiang', '黑龙江'),
    ('shanghai', '上海'),
    ('jiangsu', '江苏'),
    ('zhejiang', '浙江'),
    ('anhui', '安徽'),
    ('fujian', '福建'),
    ('jiangxi', '江西'),
    ('shandong', '山东'),
    ('henan', '河南'),
    ('hubei', '湖北'),
    ('hunan', '湖南'),
    ('guangdong', '广东'),
    ('guangxi', '广西'),
    ('hainan', '海南'),
    ('chongqing', '重庆'),
    ('sichuan', '四川'),
    ('guizhou', '贵州'),
    ('yunnan', '云南'),
    ('xizang', '西藏'),
    ('shaanxi', '陕西'),
    ('gansu', '甘肃'),
    ('qinghai', '青海'),
    ('ningxia', '宁夏'),
    ('xinjiang', '新疆'),
    ('hongkong', '香港'),
    ('macau', '澳门'),
    ('taiwan', '台湾'),
]


# 采购品目选择
PROCUREMENT_CATEGORY_CHOICES = [
    ('goods', '货物类'),
    ('engineering', '工程类'),
    ('service', '服务类'),
]

# 所属行业选择
INDUSTRY_CHOICES = [
    ('construction', '建筑工程'),
    ('water', '水利水电'),
    ('energy', '能源化工'),
    ('security', '弱电安防'),
    ('it', '信息技术'),
    ('office', '行政办公'),
    ('machinery', '机械设备'),
    ('transportation', '交通工程'),
    ('medical', '医疗卫生'),
    ('municipal', '市政设施'),
    ('service', '服务采购'),
    ('agriculture', '农林牧渔'),
    ('other', '其他'),
]


class AnnouncementIndexPage(Page):
    """公告列表页"""
    intro = RichTextField(blank=True, verbose_name='介绍')

    content_panels = Page.content_panels + [
        FieldPanel('intro'),
    ]

    class Meta:
        verbose_name = '公告列表页'
    
    @staticmethod
    def highlight_search_term(text, search_query):
        """✨ 搜索词高亮显示
        
        将搜索词用 <mark> 标签包装，支持 case-insensitive
        
        Args:
            text: 要高亮的文本
            search_query: 搜索关键词
            
        Returns:
            高亮后的 HTML 字符串
        """
        if not text or not search_query:
            return text
        
        try:
            # 使用正则表达式实现 case-insensitive 替换
            pattern = re.compile(re.escape(search_query), re.IGNORECASE)
            highlighted = pattern.sub(
                lambda m: f'<mark class="search-highlight">{m.group()}</mark>',
                str(text)
            )
            return mark_safe(highlighted)
        except Exception as e:
            # 如果高亮失败，返回原文本
            return text

    def get_context(self, request):
        context = super().get_context(request)
        
        # 传递地区选项给模板
        search_query = request.GET.get('search', '').strip()
        region = request.GET.get('region', '').strip()
        time_filter = request.GET.get('time', '').strip()
        amount_range = request.GET.get('amount', '').strip()
        page_number = request.GET.get('page', 1)
        search_active = bool(search_query)

        announcements_page, total_count = fetch_mysql_announcements_page(
            search_query=search_query,
            region=region,
            time_filter=time_filter,
            amount_range=amount_range,
            page=page_number,
            per_page=10,
        )
        
        # 记录搜索日志 - 用于搜索建议功能
        if search_active:
            search_log, created = SearchLog.objects.get_or_create(
                search_query=search_query.lower()
            )
            if created:
                search_log.result_count = total_count
                search_log.save(update_fields=['result_count', 'last_searched'])
            else:
                search_log.increment(total_count)
            
            # 记录用户搜索历史
            if request.user.is_authenticated:
                UserSearchHistory.objects.create(
                    user=request.user,
                    search_query=search_query,
                    result_count=total_count
                )
        
        # 传递搜索状态给模板
        context['search_active'] = search_active
        context['search_query'] = search_query
        
        # 筛选逻辑 - 在搜索结果之上应用筛选条件
        # 地区筛选
        region = request.GET.get('region')
        if region and region != 'all':
            announcements = announcements.filter(region=region)
        
        # 公告类型筛选
        announcement_type = request.GET.get('type')
        if announcement_type:
            announcements = announcements.filter(announcement_type=announcement_type)
        

        
        # 采购品目筛选
        procurement = request.GET.get('procurement')
        if procurement:
            announcements = announcements.filter(procurement_category=procurement)
        
        # 行业筛选
        industry = request.GET.get('industry')
        if industry:
            announcements = announcements.filter(industry=industry)
        
        # 附件状态筛选
        has_attachment = request.GET.get('has_attachment')
        if has_attachment == 'yes':
            announcements = announcements.exclude(attachment='')
        elif has_attachment == 'no':
            announcements = announcements.filter(attachment='')
        
        # 时间筛选
        from datetime import date, timedelta
        time_filter = request.GET.get('time')
        if time_filter:
            today = date.today()
            if time_filter == 'today':
                announcements = announcements.filter(date=today)
            elif time_filter == 'month':
                announcements = announcements.filter(date__gte=today - timedelta(days=30))
            elif time_filter == 'three_months':
                announcements = announcements.filter(date__gte=today - timedelta(days=90))
            elif time_filter == 'six_months':
                announcements = announcements.filter(date__gte=today - timedelta(days=180))
            elif time_filter == 'year':
                announcements = announcements.filter(date__gte=today - timedelta(days=365))
        
        # 金额筛选（基于采购金额，单位：元）
        amount_range = request.GET.get('amount')
        if amount_range:
            if amount_range == 'below_1':
                # 1万以下
                announcements = announcements.filter(purchase_amount_value__lt=10000)
            elif amount_range == '1_10':
                # 1万到10万
                announcements = announcements.filter(purchase_amount_value__gte=10000, purchase_amount_value__lt=100000)
            elif amount_range == '10_100':
                # 10万到100万
                announcements = announcements.filter(purchase_amount_value__gte=100000, purchase_amount_value__lt=1000000)
            elif amount_range == '100_500':
                # 100万到500万
                announcements = announcements.filter(purchase_amount_value__gte=1000000, purchase_amount_value__lt=5000000)
            elif amount_range == 'above_500':
                # 500万以上
                announcements = announcements.filter(purchase_amount_value__gte=5000000)
        
        # 排序
        announcements = announcements.order_by('-date')
        
        # 分页
        paginator = Paginator(announcements, 20)  # 每页20条
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        # ✨ 【优化1】搜索结果高亮显示 - 为搜索结果中的关键词添加高亮标签
        if search_active:
            for announcement in page_obj:
                # 对标题进行高亮
                announcement.highlighted_title = self.highlight_search_term(
                    announcement.title, search_query
                )
                # 对内容进行高亮（仅显示前 200 字）
                content_preview = str(announcement.content)[:200] if announcement.content else ''
                announcement.highlighted_content = self.highlight_search_term(
                    content_preview, search_query
                )
        
        context['announcements'] = page_obj
        context['total_count'] = announcements.count()
        
        return context


class AnnouncementPage(Page):
    """公告详情页"""
    date = models.DateField(
        verbose_name="发布日期",
        default=datetime.date.today
    )
    announcement_type = models.CharField(
        max_length=30,
        choices=ANNOUNCEMENT_TYPE_CHOICES,
        default='public_bidding',
        verbose_name='公告类型'
    )
    region = models.CharField(
        max_length=20,
        choices=REGION_CHOICES,
        default='all',
        verbose_name='地区'
    )
    city = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='城市'
    )

    procurement_category = models.CharField(
        max_length=20,
        choices=PROCUREMENT_CATEGORY_CHOICES,
        blank=True,
        verbose_name='采购品目'
    )
    industry = models.CharField(
        max_length=20,
        choices=INDUSTRY_CHOICES,
        default='other',
        verbose_name='所属行业'
    )
    project_number = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='项目编号'
    )
    publisher = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='采购单位'
    )
    agency = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='代理机构'
    )
    purchase_amount_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='采购金额（元）'
    )

    @property
    def purchase_amount_wan(self):
        if self.purchase_amount_value:
            return self.purchase_amount_value / 10000
        return None
    content = RichTextField(verbose_name='公告内容')
    attachment = models.FileField(
        upload_to='announcements/attachments/',
        blank=True,
        verbose_name='附件'
    )
    external_link = models.URLField(
        max_length=500,
        blank=True,
        verbose_name='公告原文链接'
    )
    
    # 搜索配置
    search_fields = Page.search_fields + [
        index.SearchField('content'),
        index.SearchField('publisher'),
        index.SearchField('agency'),
        index.FilterField('announcement_type'),
        index.FilterField('region'),
        index.FilterField('industry'),
        index.FilterField('date'),
    ]

    content_panels = Page.content_panels + [
        FieldPanel('date'),
        FieldPanel('announcement_type'),
        FieldPanel('region'),
        FieldPanel('city'),
        FieldPanel('procurement_category'),
        FieldPanel('industry'),
        FieldPanel('project_number'),
        FieldPanel('publisher'),
        FieldPanel('agency'),
        FieldPanel('purchase_amount_value'),
        FieldPanel('content'),
        FieldPanel('attachment'),
        FieldPanel('external_link'),
    ]

    class Meta:
        verbose_name = '公告'

    parent_page_types = ['announcements.AnnouncementIndexPage']


class FavoriteAnnouncement(models.Model):
    """收藏的公告"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户')
    announcement = models.ForeignKey(AnnouncementPage, on_delete=models.CASCADE, verbose_name='公告')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='收藏时间')

    class Meta:
        verbose_name = '收藏的公告'
        verbose_name_plural = '收藏的公告'
        unique_together = ['user', 'announcement']


# ============ 【中期优化】搜索功能增强模型 ============

class SearchLog(models.Model):
    """🔍 搜索日志 - 记录全平台搜索词热度
    
    用于:
    - 生成搜索建议 (热词排序)
    - 数据分析 (用户搜索行为)
    """
    search_query = models.CharField(
        max_length=255, 
        db_index=True,
        verbose_name='搜索关键词'
    )
    search_count = models.IntegerField(
        default=1,
        verbose_name='搜索次数'
    )
    result_count = models.IntegerField(
        default=0,
        verbose_name='结果数量'
    )
    last_searched = models.DateTimeField(
        auto_now=True,
        verbose_name='最后搜索时间'
    )
    
    class Meta:
        verbose_name = '搜索日志'
        verbose_name_plural = '搜索日志'
        unique_together = ('search_query',)
        ordering = ['-last_searched']
        indexes = [
            models.Index(fields=['-last_searched']),
            models.Index(fields=['-search_count']),
        ]
    
    def __str__(self):
        return f"{self.search_query} ({self.search_count}次)"
    
    def increment(self, result_count=0):
        """增加搜索计数"""
        self.search_count += 1
        self.result_count = result_count
        self.save(update_fields=['search_count', 'result_count', 'last_searched'])


class UserSearchHistory(models.Model):
    """📋 用户搜索历史 - 记录用户个人搜索历史
    
    用于:
    - 提供用户个人搜索历史查询
    - 支持快速重复搜索
    - 个性化推荐基础数据
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='search_history',
        verbose_name='用户'
    )
    search_query = models.CharField(
        max_length=255,
        verbose_name='搜索关键词'
    )
    search_time = models.DateTimeField(
        auto_now_add=True,
        verbose_name='搜索时间'
    )
    result_count = models.IntegerField(
        default=0,
        verbose_name='结果数量'
    )
    
    class Meta:
        verbose_name = '用户搜索历史'
        verbose_name_plural = '用户搜索历史'
        ordering = ['-search_time']
        indexes = [
            models.Index(fields=['user', '-search_time']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.search_query}"


def _announcement_index_page_get_context(self, request):
    context = super(AnnouncementIndexPage, self).get_context(request)

    search_query = request.GET.get('search', '').strip()
    region = request.GET.get('region', '').strip()
    time_filter = request.GET.get('time', '').strip()
    amount_range = request.GET.get('amount', '').strip()
    page_number = request.GET.get('page', 1)

    announcements_page, total_count = fetch_mysql_announcements_page(
        search_query=search_query,
        region=region,
        time_filter=time_filter,
        amount_range=amount_range,
        page=page_number,
        per_page=10,
    )

    search_active = bool(search_query)
    if search_active:
        search_log, created = SearchLog.objects.get_or_create(
            search_query=search_query.lower()
        )
        if created:
            search_log.result_count = total_count
            search_log.save(update_fields=['result_count', 'last_searched'])
        else:
            search_log.increment(total_count)

        if request.user.is_authenticated:
            UserSearchHistory.objects.create(
                user=request.user,
                search_query=search_query,
                result_count=total_count,
            )

    context['announcements'] = announcements_page
    context['page_size'] = 10
    context['region_choices'] = REGION_FILTER_CHOICES
    context['search_active'] = search_active
    context['search_query'] = search_query
    context['total_count'] = total_count
    context['showing_latest_default'] = not any(
        [search_query, region, time_filter, amount_range]
    )
    return context


AnnouncementIndexPage.get_context = _announcement_index_page_get_context
