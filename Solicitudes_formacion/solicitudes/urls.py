from django.urls import path
from . import views

app_name = "solicitudes"

# Archivo de rutas mínimo para el app solicitudes
urlpatterns = [
    path('',views.listar_solicitudes, name='listar_solicitudes'),
    path('panel-correos/', views.panel_correos, name='panel_correos'),
    path('probar-email/', views.probar_conexion_email, name='probar_conexion_email'),
    path('<int:solicitud_id>/', views.detalle_solicitud, name='detalle_solicitud'),
    path('procesar-ajax/', views.procesar_correos_ajax, name='procesar_correos_ajax'),
    path('procesar-correos-ajax/', views.procesar_correos_ajax, name='procesar_correos_ajax'),
    #path('crear/',views.crear_solicitud, name='crear_solicitud'),
    #path('<int:solicitud_id>/',views.detalle_solicitud, bame='detalle_solicitud'),
    #path('<int:solicitud_id>/editar/', views.editar_solicitud, name='editar-solicitud'),
    
]

