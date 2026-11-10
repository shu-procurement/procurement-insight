from django.urls import path
from . import views

urlpatterns = [
    path('password/reset/', views.password_reset_request, name='custom_password_reset'),
    path('password/reset/send_code/', views.send_verification_code, name='send_verification_code'),
    path('password/reset/verify/', views.password_reset_verify, name='password_reset_verify'),
    path('password/reset/done/', views.password_reset_complete, name='custom_password_reset_complete'),
]
