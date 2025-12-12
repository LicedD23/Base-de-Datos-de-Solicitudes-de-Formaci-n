"""
URLs del módulo de reportes
"""

from django.urls import path
from . import views

app_name = 'reportes'

urlpatterns = [
    # Panel principal
    path('', views.panel_reportes, name='panel_reportes'),
    
    # Reportes de Solicitudes
    path('solicitudes/pdf/', views.generar_reporte_solicitudes_pdf, name='reporte_solicitudes_pdf'),
    path('solicitudes/excel/', views.generar_reporte_solicitudes_excel, name='reporte_solicitudes_excel'),
    
    # Reportes de Empresas
    path('empresas/pdf/', views.generar_reporte_empresas_pdf, name='reporte_empresas_pdf'),
    path('empresas/excel/', views.generar_reporte_empresas_excel, name='reporte_empresas_excel'),
    #Reportes de Programas 
    path('programas/pdf/', views.generar_reporte_programas_pdf, name='reporte_programas_pdf'),
    path('programas/excel/', views.generar_reporte_programas_excel, name='reporte_programas_excel'),
    # Reportes de Instructores
    path('instructores/pdf/', views.generar_reporte_instructores_pdf, name='reporte_instructores_pdf'),
    path('instructores/excel/', views.generar_reporte_instructores_excel, name='reporte_instructores_excel'),
    
    # Reportes Consolidados
    path('consolidado/pdf/', views.generar_reporte_consolidado_pdf, name='reporte_consolidado_pdf'),
    path('consolidado/excel/', views.generar_reporte_consolidado_excel, name='reporte_consolidado_excel'),
]