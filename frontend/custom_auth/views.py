import random
import string
from django.shortcuts import render, redirect
from django.core.mail import send_mail
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.conf import settings
from .forms import PasswordResetVerifyForm
from django.contrib import messages

User = get_user_model()

def generate_code(length=6):
    return ''.join(random.choices(string.digits, k=length))

def password_reset_request(request):
    """
    Renders the password reset page.
    """
    form = PasswordResetVerifyForm() 
    return render(request, 'custom_auth/password_reset.html', {'form': form})

@require_POST
def send_verification_code(request):
    """
    API to send verification code to email.
    """
    import json
    try:
        data = json.loads(request.body)
        email = data.get('email')
        send_type = data.get('type', 'reset') # 'reset' or 'register'
    except:
        email = request.POST.get('email')
        send_type = request.POST.get('type', 'reset')

    if not email:
        return JsonResponse({'success': False, 'message': '请输入邮箱地址'})
    
    user_exists = User.objects.filter(email=email).exists()

    if send_type == 'reset':
         if not user_exists:
            return JsonResponse({'success': False, 'message': '该邮箱未注册'})
    elif send_type == 'register':
        if user_exists:
            return JsonResponse({'success': False, 'message': '该邮箱已注册，请直接登录'})
    
    # Rate Limit Check
    cache_key_limit = f"{send_type}_limit_{email}"
    if cache.get(cache_key_limit):
        return JsonResponse({'success': False, 'message': '请求过于频繁，请60秒后再试'})

    # Generate Code
    code = generate_code()
    cache_key_code = f"{send_type}_code_{email}"
    
    # Save code for 5 minutes (300 seconds)
    cache.set(cache_key_code, code, timeout=300)
    
    # Set Rate Limit for 60 seconds
    cache.set(cache_key_limit, True, timeout=60)

    # Send Email
    subject = '【招投标平台】注册验证码' if send_type == 'register' else '【招投标平台】重置密码验证码'
    try:
        send_mail(
            subject,
            f'您的验证码是：{code}。该验证码5分钟内有效，请勿泄露给他人。',
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        return JsonResponse({'success': True, 'message': '验证码已发送'})
    except Exception as e:
        print(f"Error sending email: {e}")
        return JsonResponse({'success': False, 'message': '邮件发送失败，请联系管理员'})

@require_POST
def password_reset_verify(request):
    """
    Handles the actual password reset.
    """
    form = PasswordResetVerifyForm(request.POST)
    if form.is_valid():
        email = request.POST.get('email') # Form field is hidden, but also cleaner to get from validated data? 
        # Actually form.cleaned_data has it if we add it to form or just trust POST if validated.
        # But wait, PasswordResetVerifyForm has email as HiddenInput but no validation on it in form class?
        # Let's rely on the hidden field.
        email = form.cleaned_data.get('email')
        code = form.cleaned_data.get('code')
        new_password = form.cleaned_data.get('new_password')
        
        # Verify Code
        cache_key_code = f"reset_code_{email}"
        cached_code = cache.get(cache_key_code)
        
        if not cached_code or cached_code != code:
            messages.error(request, '验证码错误或已过期')
            return render(request, 'custom_auth/password_reset.html', {'form': form})

        # Reset Password
        try:
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
            
            # Clear Code
            cache.delete(cache_key_code)
            cache.delete(f"reset_limit_{email}")
            
            return redirect('custom_password_reset_complete')
            
        except User.DoesNotExist:
             messages.error(request, '用户不存在')
             return render(request, 'custom_auth/password_reset.html', {'form': form})
    else:
        return render(request, 'custom_auth/password_reset.html', {'form': form})

def password_reset_complete(request):
    return render(request, 'custom_auth/password_reset_complete.html')


# custom_auth/views.py
from django.http import JsonResponse
from .tokens import build_fastapi_access_token


def get_fastapi_token(request):
    if request.user.is_authenticated:
        token = build_fastapi_access_token(request.user)
        return JsonResponse({"access_token": token, "token_type": "bearer"})
    if not request.user.is_authenticated:
        return JsonResponse({"error": "未登录"}, status=401)
