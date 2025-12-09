from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
	path('', views.home, name='home'),
	path('dashboard/', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('registro-admin/', views.register_admin_view, name='register_admin'),
    path('logout/',views.logout_view, name='logout'),

    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('profile/change-password/', views.change_password, name='change_password'),
    path('accesibilidad/', views.accessibility, name='accesibilidad'),
]

