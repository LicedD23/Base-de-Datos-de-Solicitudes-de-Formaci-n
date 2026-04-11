from django.urls import path
from . import views

app_name = "instructores"

# Archivo de rutas mínimo para el app instructores
urlpatterns = [
    path('',views.listar_instructores, name='listar_instructores'),
    path('crear/',views.crear_instructor, name='crear_instructor'),
    path('<int:instructor_id>/',views.detalle_instructor, name='detalle_instructor'),
    path('<int:instructor_id>/editar/',views.editar_instructor, name='editar_instructor'),
    path('<int:instructor_id>/desactivar/',views.desactivar_instructor, name='desactivar_instructor'),
    path('<int:instructor_id>/eliminar/', views.eliminar_instructor, name='eliminar_instructor'),
    path('calendario/',                   views.calendario_instructores, name='calendario_instructores'), 
]

