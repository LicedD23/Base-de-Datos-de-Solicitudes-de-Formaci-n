from django.contrib import admin
from .models import Solicitud

@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ['empresa', 'programa', 'fecha_recepcion', 'instructor_asignado', 'estado']
    list_filter = ['estado', 'programa', 'fecha_recepcion']
    search_fields = ['empresa__nombre', 'observaciones']
    date_hierarchy = 'fecha_recepcion'
    
    fieldsets = (
        ('Informacion Basica', {
            'fields': ('empresa', 'programa', 'fecha_recepcion')
        }),
        ('Asignacion', {
            'fields': ('instructor_asignado', 'estado')
        }),
        ('Fechas de Seguimiento', {
            'fields': ('fecha_respuesta', 'fecha_atencion')
        }),
        ('Observaciones', {
            'fields': ('observaciones',)
        }),
    )
