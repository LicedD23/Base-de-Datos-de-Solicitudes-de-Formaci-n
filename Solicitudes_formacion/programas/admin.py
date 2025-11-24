from django.contrib import admin
from .models import Programa

@admin.register(Programa)
class ProgramaAdmin(admin.ModelAdmin):
    list_display = ['area', 'nombre','codigo', 'duracion_horas', 'activo']
    search_fields = ['nombre','codigo', 'area__nombre']
    list_filter = ['area', 'activo']
    raw_id_fields = ('area',)
