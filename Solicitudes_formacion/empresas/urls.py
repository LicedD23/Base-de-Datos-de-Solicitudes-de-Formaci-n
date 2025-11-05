from django.urls import path
from . import views

app_name = "empresas"

# Archivo de rutas mínimo para el app empresas
urlpatterns = [
    path('empresas/', views.listar_empresas, name='listar_empresas'),
    path('empresas/crear/', views.crear_empresa, name='crear_empresa'),
    path('empresas/<int:empresa_id>/', views.detalle_empresa, name='detalle_empresa'),
    path('empresas/<int:empresa_id>/editar/', views.editar_empresa, name='editar_empresa'),
    path('empresas/<int:empresa_id>/desactivar/', views.desactivar_empresa, name='desactivar_empresa'),
]

