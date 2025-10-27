from django.urls import path
from . import views

app_name = "programas"

# Archivo de rutas mínimo para el app programas
urlpatterns = [
    path('programas/', views.listar_programas, name='listar_programas'),
    path('programas/crear/', views.crear_programa, name='crear_programa'),
    path('programas/<int:programa_id>/', views.detalle_programa, name='detalle_programa'),
    path('programas/<int:programa_id>/editar/', views.editar_programa, name='editar_programa'),
    path('programas/<int:programa_id>/eliminar/', views.eliminar_programa, name='eliminar_programa'),
]
