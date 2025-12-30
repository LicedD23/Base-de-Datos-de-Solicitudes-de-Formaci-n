from django.urls import path
from . import views

app_name = "programas"

urlpatterns = [
    path('', views.listar_programas, name='listar_programas'),
    path('crear/', views.crear_programa, name='crear_programa'),
    path('<int:programa_id>/', views.detalle_programa, name='detalle_programa'),
    path('<int:programa_id>/editar/', views.editar_programa, name='editar_programa'),
    path('<int:programa_id>/desactivar/', views.desactivar_programa, name='desactivar_programa'),
    path('<int:programa_id>/eliminar/', views.eliminar_programa, name='eliminar_programa')
]
