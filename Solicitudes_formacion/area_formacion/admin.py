from django.contrib import admin
from .models import Area
from programas.models import Programa

class ProgramaInline(admin.TabularInline):
    model = Programa
    extra = 1
    show_change_link = True

@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'activo', 'fecha_creacion']
    search_fields = ['nombre']
    list_filter = ['activo']
    inlines = [ProgramaInline]