# Generated manually to create initial page structure

from django.db import migrations


def create_initial_pages(apps, schema_editor):
    # Get models
    ContentType = apps.get_model('contenttypes.ContentType')
    Page = apps.get_model('wagtailcore.Page')
    Site = apps.get_model('wagtailcore.Site')
    HomePage = apps.get_model('home.HomePage')
    AnnouncementIndexPage = apps.get_model('announcements.AnnouncementIndexPage')
    ReportIndexPage = apps.get_model('reports.ReportIndexPage')
    
    # Delete the default homepage if it exists
    Page.objects.filter(slug='home', depth=2).delete()
    
    # Get root page
    root_page = Page.objects.get(depth=1)
    
    # Get content types
    home_content_type = ContentType.objects.get_for_model(HomePage)
    announcement_content_type = ContentType.objects.get_for_model(AnnouncementIndexPage)
    report_content_type = ContentType.objects.get_for_model(ReportIndexPage)
    
    # Create HomePage
    home_page = HomePage(
        title="首页",
        slug='home',
        banner_title='招投标大数据',
        banner_subtitle='让采购更简单',
        search_placeholder='请输入关键字搜索...',
        content_type=home_content_type,
        path='00010001',
        depth=2,
        numchild=0,
        url_path='/home/',
    )
    home_page.save()
    
    # Update site root page
    site = Site.objects.get(is_default_site=True)
    site.root_page = home_page
    site.save()
    
    # Create AnnouncementIndexPage
    announcement_index = AnnouncementIndexPage(
        title="公告检索",
        slug='announcements',
        intro='<p>查询招标公告、中标公告等各类采购信息</p>',
        content_type=announcement_content_type,
        path='000100010001',
        depth=3,
        numchild=0,
        url_path='/home/announcements/',
    )
    announcement_index.save()
    
    # Create ReportIndexPage
    report_index = ReportIndexPage(
        title="需求调查报告",
        slug='reports',
        intro='<p>查看和分析各类采购需求调查报告</p>',
        content_type=report_content_type,
        path='000100010002',
        depth=3,
        numchild=0,
        url_path='/home/reports/',
    )
    report_index.save()
    
    # Update home page numchild
    home_page.numchild = 2
    home_page.save()


def remove_initial_pages(apps, schema_editor):
    # This is a reverse migration - we don't need to do anything
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0003_alter_homepage_options_homepage_banner_subtitle_and_more'),
        ('announcements', '0001_initial'),
        ('reports', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_initial_pages, remove_initial_pages),
    ]

