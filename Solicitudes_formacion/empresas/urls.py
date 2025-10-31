from django.urls import path
from . import views

app_name = "empresas"

# Archivo de rutas mínimo para el app empresas
urlpatterns = [
    path('empresas/', views.listar_empresas, name='listar_empresas'),
    path('empresas/<int:empresas_id>/', views.detalle_empresa, name='detalle_empresas'),

    
]

