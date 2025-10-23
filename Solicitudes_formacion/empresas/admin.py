from django.contrib import admin
from .models import Empresa

@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'contacto', 'telefono', 'municipio', 'numero_trabajadores']
    search_fields = ['nombre', 'contacto', 'municipio']
    list_filter = ['municipio']
