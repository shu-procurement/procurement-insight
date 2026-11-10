from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from wagtail.models import Page, Site
from home.models import HomePage
from announcements.models import AnnouncementIndexPage, AnnouncementPage
from reports.models import ReportIndexPage, ReportPage
from datetime import datetime, timedelta


class Command(BaseCommand):
    help = '创建示例页面和数据'

    def handle(self, *args, **options):
        self.stdout.write('开始创建页面结构...')
        
        # Delete existing home page if it exists
        Page.objects.filter(slug='home', depth=2).delete()
        
        # Get root page
        root = Page.objects.get(depth=1)
        
        # Create HomePage
        self.stdout.write('创建首页...')
        home_page = HomePage(
            title="首页",
            slug='home',
            banner_title='招投标大数据',
            banner_subtitle='让采购更简单',
            search_placeholder='请输入关键字搜索...',
        )
        root.add_child(instance=home_page)
        revision = home_page.save_revision()
        revision.publish()
        
        # Update or create site
        try:
            site = Site.objects.get(is_default_site=True)
            site.root_page = home_page
            site.save()
        except Site.DoesNotExist:
            Site.objects.create(
                hostname='localhost',
                port=8000,
                root_page=home_page,
                is_default_site=True,
                site_name='招投标信息平台'
            )
        
        # Create AnnouncementIndexPage
        self.stdout.write('创建公告检索页面...')
        announcement_index = AnnouncementIndexPage(
            title="公告检索",
            slug='announcements',
            intro='<p>查询招标公告、中标公告等各类采购信息</p>',
        )
        home_page.add_child(instance=announcement_index)
        revision = announcement_index.save_revision()
        revision.publish()
        
        # Create sample announcements
        self.stdout.write('创建示例公告...')
        announcements_data = [
            {
                'title': '某大学图书馆设备采购招标公告',
                'announcement_type': 'bidding',
                'region': 'beijing',
                'city': '北京市',
                'category': 'university',
                'project_amount': '100_500',
                'procurement_category': 'goods',
                'industry': 'it',
                'publisher': '某大学采购中心',
                'content': '<p>根据《中华人民共和国政府采购法》等有关规定，现对某大学图书馆设备采购进行公开招标，欢迎合格的供应商前来投标。</p><p><strong>项目概况：</strong></p><ul><li>项目名称：图书馆设备采购</li><li>预算金额：300万元</li><li>采购需求：计算机、打印机、扫描仪等办公设备</li></ul>',
            },
            {
                'title': '市人民医院医疗设备采购中标公告',
                'announcement_type': 'result',
                'region': 'shanghai',
                'city': '上海市',
                'category': 'hospital',
                'project_amount': '500_1000',
                'procurement_category': 'goods',
                'industry': 'medical',
                'publisher': '上海市人民医院',
                'content': '<p>经过公开招标，现将中标结果公布如下：</p><p><strong>中标单位：</strong>某医疗设备有限公司</p><p><strong>中标金额：</strong>800万元</p>',
            },
            {
                'title': '城市道路改造工程招标公告',
                'announcement_type': 'bidding',
                'region': 'guangdong',
                'city': '广州市',
                'category': 'other',
                'project_amount': 'above_1000',
                'procurement_category': 'engineering',
                'industry': 'transportation',
                'publisher': '广州市交通局',
                'content': '<p>现对城市主干道改造工程进行公开招标。</p><p><strong>工程概况：</strong></p><ul><li>工程地点：广州市天河区</li><li>工程内容：道路拓宽、路面翻新</li><li>工期：6个月</li></ul>',
            },
            {
                'title': '政府办公楼物业服务采购招标公告',
                'announcement_type': 'bidding',
                'region': 'zhejiang',
                'city': '杭州市',
                'category': 'other',
                'project_amount': '50_100',
                'procurement_category': 'service',
                'industry': 'service',
                'publisher': '杭州市政府采购中心',
                'content': '<p>现对政府办公楼物业服务进行公开招标。</p><p><strong>服务期限：</strong>3年</p><p><strong>服务内容：</strong>保洁、保安、绿化养护等</p>',
            },
            {
                'title': '某项目采购变更公告',
                'announcement_type': 'change',
                'region': 'jiangsu',
                'city': '南京市',
                'category': 'university',
                'project_amount': '10_50',
                'procurement_category': 'goods',
                'industry': 'office',
                'publisher': '某高校',
                'content': '<p>原招标文件部分内容进行如下变更：</p><ul><li>投标截止时间延期至2026年3月1日</li><li>技术参数调整详见附件</li></ul>',
            },
        ]
        
        for i, data in enumerate(announcements_data):
            announcement = AnnouncementPage(
                title=data['title'],
                slug=f'announcement-{i+1}',
                announcement_type=data['announcement_type'],
                region=data['region'],
                city=data.get('city', ''),
                category=data['category'],
                project_amount=data['project_amount'],
                procurement_category=data['procurement_category'],
                industry=data['industry'],
                publisher=data['publisher'],
                content=data['content'],
            )
            announcement_index.add_child(instance=announcement)
            revision = announcement.save_revision()
            revision.publish()
        
        # Create ReportIndexPage
        self.stdout.write('创建需求调查报告页面...')
        report_index = ReportIndexPage(
            title="需求调查报告",
            slug='reports',
            intro='<p>查看和分析各类采购需求调查报告</p>',
        )
        home_page.add_child(instance=report_index)
        revision = report_index.save_revision()
        revision.publish()
        
        # Create sample reports
        self.stdout.write('创建示例报告...')
        reports_data = [
            {
                'title': '2026年高校信息化设备需求分析报告',
                'procurement_name': '计算机/服务器/网络设备/多媒体教学设备/实验室仪器/图书馆自动化系统/校园一卡通系统/安防监控设备',
                'analysis_type': '分析',
                'category': 'ai',
                'summary': '<p>本报告对2026年度高校信息化设备采购需求进行了全面分析。</p>',
                'content': '<p><strong>主要发现：</strong></p><ul><li>计算机设备需求量最大，占比45%</li><li>网络设备升级需求显著</li><li>多媒体教学设备更新换代加速</li></ul>',
            },
            {
                'title': '医疗设备采购市场调研报告',
                'procurement_name': 'CT机/核磁共振/超声设备/X光机/手术器械/监护仪/呼吸机/血液分析仪',
                'analysis_type': '分析',
                'category': 'bigdata',
                'summary': '<p>针对医疗设备采购市场进行深度调研分析。</p>',
                'content': '<p><strong>市场趋势：</strong></p><ul><li>高端医疗设备国产化率提升</li><li>智能化、数字化成为主流</li><li>采购预算整体增长</li></ul>',
            },
            {
                'title': '政府办公设备需求调查',
                'procurement_name': '办公桌椅/文件柜/保险柜/会议桌/投影仪/打印机/复印机/碎纸机/空调/饮水机',
                'analysis_type': '分析',
                'category': 'analysis',
                'summary': '<p>对政府机关办公设备采购需求进行统计分析。</p>',
                'content': '<p><strong>采购特点：</strong></p><ul><li>注重环保节能</li><li>倾向国产品牌</li><li>批量采购为主</li></ul>',
            },
        ]
        
        for i, data in enumerate(reports_data):
            report = ReportPage(
                title=data['title'],
                slug=f'report-{i+1}',
                procurement_name=data['procurement_name'],
                analysis_type=data['analysis_type'],
                category=data['category'],
                summary=data['summary'],
                content=data['content'],
            )
            report_index.add_child(instance=report)
            revision = report.save_revision()
            revision.publish()
        
        self.stdout.write(self.style.SUCCESS('✅ 成功创建所有页面和示例数据！'))
        self.stdout.write(f'  - 首页: http://127.0.0.1:8000/')
        self.stdout.write(f'  - 公告检索: http://127.0.0.1:8000/announcements/')
        self.stdout.write(f'  - 需求调查报告: http://127.0.0.1:8000/reports/')
        self.stdout.write(f'  - 创建了 {len(announcements_data)} 条示例公告')
        self.stdout.write(f'  - 创建了 {len(reports_data)} 份示例报告')
