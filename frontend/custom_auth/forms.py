from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import MinLengthValidator

User = get_user_model()

class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(label="电子邮箱", widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': '请输入您的注册邮箱'}))

    def clean_email(self):
        email = self.cleaned_data['email']
        if not User.objects.filter(email=email).exists():
            raise forms.ValidationError("该邮箱未注册")
        return email

class PasswordResetVerifyForm(forms.Form):
    email = forms.EmailField(widget=forms.HiddenInput())
    code = forms.CharField(label="验证码", max_length=6, min_length=6, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '6位验证码'}))
    new_password = forms.CharField(label="新密码", widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '请输入新密码'}), validators=[MinLengthValidator(8)])
    confirm_password = forms.CharField(label="确认密码", widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '请再次输入新密码'}))

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password and confirm_password and new_password != confirm_password:
            self.add_error('confirm_password', "两次输入的密码不一致")
        return cleaned_data

from allauth.account.forms import SignupForm
from django.core.cache import cache

class CustomSignupForm(SignupForm):
    code = forms.CharField(label="验证码", max_length=6, min_length=6, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '6位验证码'}))

    def clean_code(self):
        code = self.cleaned_data['code']
        # We need email to check cache. Allauth cleans email before this if field order is right, 
        # or we get it from cleaned_data if available.
        email = self.cleaned_data.get('email')
        if not email:
            # If email is invalid, we can't check code, but email error will be raised anyway.
            return code
        
        cache_key_code = f"register_code_{email}"
        cached_code = cache.get(cache_key_code)
        
        if not cached_code or cached_code != code:
            raise forms.ValidationError("验证码错误或已过期")
        
        # Clear code after successful validation? 
        # Better to clear on save(), but validation is good enough to block.
        # If we clear here, re-submission on other errors (like password mismatch) might fail.
        # So don't clear here.
        return code

    def save(self, request):
        user = super(CustomSignupForm, self).save(request)
        # Clear code after successful signup
        email = self.cleaned_data.get('email')
        cache.delete(f"register_code_{email}")
        cache.delete(f"register_limit_{email}")
        return user
