"""
自定义中间件：限制非管理员用户访问后台。
"""
from django.http import HttpResponse


class AdminAccessMiddleware:
    """
    拦截非 staff 用户对 /admin/ 的访问请求。
    弹出提示"您没有获得权限，请联系管理员"，然后返回上一页。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 检查是否是 /admin/ 路径（排除 /admin/login/ 以避免循环）
        if request.path.startswith('/admin/') and not request.path.startswith('/admin/login/'):
            if not request.user.is_authenticated or not request.user.is_staff:
                html = """
                <!DOCTYPE html>
                <html>
                <head><meta charset="utf-8"><title>无权限</title></head>
                <body>
                <script>
                    alert('您没有获得权限，请联系管理员');
                    if (document.referrer) {
                        window.location.href = document.referrer;
                    } else {
                        window.location.href = '/';
                    }
                </script>
                </body>
                </html>
                """
                return HttpResponse(html, status=403)

        return self.get_response(request)
