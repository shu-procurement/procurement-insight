from django.db import models
from wagtail.models import Page
from wagtail.fields import RichTextField
from wagtail.admin.panels import FieldPanel


class HomePage(Page):
    """首页"""
    banner_title = models.CharField(
        max_length=200,
        default='招投标大数据',
        verbose_name='横幅标题'
    )
    banner_subtitle = models.CharField(
        max_length=200,
        default='让采购更简单',
        blank=True,
        verbose_name='横幅副标题'
    )
    search_placeholder = models.CharField(
        max_length=100,
        default='请输入关键字搜索...',
        verbose_name='搜索框提示文字'
    )

    content_panels = Page.content_panels + [
        FieldPanel('banner_title'),
        FieldPanel('banner_subtitle'),
        FieldPanel('search_placeholder'),
    ]

    class Meta:
        verbose_name = '首页'

