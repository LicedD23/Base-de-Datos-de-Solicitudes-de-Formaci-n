from django.urls import path
from . import views

app_name = 'backups'

urlpatterns = [
    #Rutas de backend
    path('backups/', views.panel_backups, name='panel_backups'),
    path('backups/crear/', views.crear_backup, name='crear_backup'),
    path('backups/descargar/<str:filename>/', views.descargar_backup, name='descargar_backup'),
    path('backups/eliminar/<str:filename>/', views.eliminar_backup, name='eliminar_backup'),
    path('backups/restaurar/<str:filename>/', views.restaurar_backup, name='restaurar_backup'),
    path('backups/limpiar/', views.limpiar_backups_antiguos, name='limpiar_backups'),
    
    ]
    