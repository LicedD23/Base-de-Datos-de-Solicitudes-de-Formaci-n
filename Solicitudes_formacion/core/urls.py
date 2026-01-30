# core/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('registro-admin/', views.register_admin_view, name='register_admin'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('profile/change-password/', views.change_password, name='change_password'),
    path('manual-usuario/', views.manual_usuario, name='manual_usuario'),
    path('accesibilidad/', views.accessibility, name='accesibilidad'),
    
    # ============================================
    # RESTABLECIMIENTO DE CONTRASEÑA
    # ============================================
    
    # 1. Formulario para solicitar restablecimiento
    path(
        'recuperar-contrasena/',
        views.CustomPasswordResetView.as_view(
            template_name='core/password_reset_form.html',
            email_template_name='core/password_reset_email.html',
            subject_template_name='core/password_reset_subject.txt',
            success_url=reverse_lazy('core:password_reset_done')  # ✅ CORREGIDO
        ),
        name='password_reset'
    ),
    
    # 2. Confirmación de email enviado
    path(
        'recuperar-contrasena/enviado/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='core/password_reset_done.html'
        ),
        name='password_reset_done'
    ),
    
    # 3. Formulario para nueva contraseña
    path(
        'restablecer/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='core/password_reset_confirm.html',
            success_url=reverse_lazy('core:password_reset_complete')  # ✅ CORREGIDO
        ),
        name='password_reset_confirm'
    ),
    
    # 4. Contraseña restablecida exitosamente
    path(
        'restablecer/completado/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='core/password_reset_complete.html'
        ),
        name='password_reset_complete'
    ),
]