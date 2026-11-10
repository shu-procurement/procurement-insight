# Generated migration for SearchLog and UserSearchHistory models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('announcements', '0009_announcementpage_date'),  # Adjust based on last migration
    ]

    operations = [
        # SearchLog 模型
        migrations.CreateModel(
            name='SearchLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('search_query', models.CharField(db_index=True, max_length=255, verbose_name='搜索关键词')),
                ('search_count', models.IntegerField(default=1, verbose_name='搜索次数')),
                ('result_count', models.IntegerField(default=0, verbose_name='结果数量')),
                ('last_searched', models.DateTimeField(auto_now=True, verbose_name='最后搜索时间')),
            ],
            options={
                'verbose_name': '搜索日志',
                'verbose_name_plural': '搜索日志',
                'ordering': ['-last_searched'],
                'unique_together': {('search_query',)},
            },
        ),
        # 为 SearchLog 添加索引
        migrations.AddIndex(
            model_name='searchlog',
            index=models.Index(fields=['-last_searched'], name='announcements_searchlog_last_search_idx'),
        ),
        migrations.AddIndex(
            model_name='searchlog',
            index=models.Index(fields=['-search_count'], name='announcements_searchlog_count_idx'),
        ),
        
        # UserSearchHistory 模型
        migrations.CreateModel(
            name='UserSearchHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('search_query', models.CharField(max_length=255, verbose_name='搜索关键词')),
                ('search_time', models.DateTimeField(auto_now_add=True, verbose_name='搜索时间')),
                ('result_count', models.IntegerField(default=0, verbose_name='结果数量')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='search_history', to=settings.AUTH_USER_MODEL, verbose_name='用户')),
            ],
            options={
                'verbose_name': '用户搜索历史',
                'verbose_name_plural': '用户搜索历史',
                'ordering': ['-search_time'],
            },
        ),
        # 为 UserSearchHistory 添加索引
        migrations.AddIndex(
            model_name='usersearchhistory',
            index=models.Index(fields=['user', '-search_time'], name='announcements_usersearch_user_time_idx'),
        ),
    ]
