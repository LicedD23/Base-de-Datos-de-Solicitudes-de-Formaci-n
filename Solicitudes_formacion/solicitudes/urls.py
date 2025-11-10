from django.urls import path
from . import views

app_name = "solicitudes"

# Archivo de rutas mínimo para el app solicitudes
urlpatterns = [
    path('',views.listar_solicitudes, name='listar_solicitudes'),
    #path('crear/',views.crear_solicitud, name='crear_solicitud'),
    #path('<int:solicitud_id>/',views.detalle_solicitud, bame='detalle_solicitud'),
    #path('<int:solicitud_id>/editar/', views.editar_solicitud, name='editar-solicitud'),
    
]

