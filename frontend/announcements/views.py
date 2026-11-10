# Views for announcements app
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from .models import SearchLog, UserSearchHistory
from .services import fetch_mysql_title_suggestions
import json


# ============ 【中期优化】搜索建议 API ============

@require_http_methods(["GET"])
def search_suggestions(request):
    """🔍 API: 获取搜索建议
    
    返回：
    1. 前缀匹配的历史搜索词
    2. 公告标题中的匹配词
    3. 最近30天的热词
    
    查询参数:
        q: 用户输入的搜索词（最少2个字符）
        limit: 返回建议数量（默认15）
    """
    query = request.GET.get('q', '').strip()
    limit = int(request.GET.get('limit', 15))
    
    if len(query) < 2:
        return JsonResponse({'suggestions': []})
    
    suggestions_set = set()
    
    try:
        # 1️⃣ 前缀匹配 - 从历史搜索词中获取
        prefix_matches = SearchLog.objects.filter(
            search_query__istartswith=query.lower()
        ).values_list('search_query', flat=True)[:10]
        suggestions_set.update(prefix_matches)
        
        # 2️⃣ 公告标题匹配 - 直接从公告中提取
        if len(suggestions_set) < limit:
            title_matches = fetch_mysql_title_suggestions(
                query,
                limit=max(limit - len(suggestions_set), 5),
            )
            suggestions_set.update(title_matches)
        
        # 3️⃣ 热词排序 - 最近30天搜索≥3次的词
        if len(suggestions_set) < limit:
            hot_searches = SearchLog.objects.filter(
                search_count__gte=3,
                last_searched__gte=timezone.now() - timedelta(days=30)
            ).order_by('-search_count').values_list('search_query', flat=True)[:10]
            suggestions_set.update(hot_searches)
        
        # 返回前 limit 个建议
        suggestions = list(suggestions_set)[:limit]
        
        return JsonResponse({
            'success': True,
            'suggestions': suggestions,
            'count': len(suggestions)
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ============ 【中期优化】搜索历史 API ============

@login_required
@require_http_methods(["GET"])
def get_search_history(request):
    """📋 API: 获取用户搜索历史
    
    返回用户最近的搜索历史（去重后）
    
    查询参数:
        limit: 返回记录数（默认10）
    """
    limit = int(request.GET.get('limit', 10))
    
    try:
        # 获取该用户的所有搜索历史，按时间倒序
        history = UserSearchHistory.objects.filter(
            user=request.user
        ).values(
            'search_query', 'search_time', 'result_count'
        ).order_by('-search_time')[:100]
        
        # 去重：保留每个搜索词的最新记录
        seen = set()
        unique_history = []
        for item in history:
            if item['search_query'] not in seen:
                seen.add(item['search_query'])
                unique_history.append({
                    'query': item['search_query'],
                    'time': item['search_time'].isoformat(),
                    'result_count': item['result_count']
                })
                if len(unique_history) >= limit:
                    break
        
        return JsonResponse({
            'success': True,
            'history': unique_history,
            'count': len(unique_history)
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def clear_search_history(request):
    """📋 API: 清空所有搜索历史"""
    try:
        deleted_count, _ = UserSearchHistory.objects.filter(
            user=request.user
        ).delete()
        
        return JsonResponse({
            'success': True,
            'deleted': deleted_count,
            'message': f'已清空 {deleted_count} 条搜索历史'
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["DELETE", "POST"])
def delete_search_history_item(request, query):
    """📋 API: 删除特定搜索历史项"""
    try:
        deleted_count, _ = UserSearchHistory.objects.filter(
            user=request.user,
            search_query__iexact=query
        ).delete()
        
        return JsonResponse({
            'success': True,
            'deleted': deleted_count,
            'message': f'已删除搜索记录: {query}'
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
