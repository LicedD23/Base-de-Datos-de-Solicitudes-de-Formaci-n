from django.urls import path
from .import views
app_name = "area_formacion"

# Archivo de rutas mínimo para evitar errores al importar con include()
urlpatterns = [
    path('areas/', views.listar_areas, name='listar_areas'),
    path('areas/crear/', views.crear_area, name='crear_area'),
    path('areas/<int:area_id>/', views.detalle_area, name='detalle_area'),
    path('areas/<int:area_id>/editar/', views.editar_area, name='editar_area'),
    path('areas/<int:area_id>/desactivar/', views.desactivar_area, name='desactivar_area'),
    
]
