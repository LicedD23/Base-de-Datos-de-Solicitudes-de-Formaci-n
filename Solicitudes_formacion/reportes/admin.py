"""
Configuración del admin para el módulo de reportes
Sistema de Gestión de Solicitudes SENA
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import Reporte


@admin.register(Reporte)
class ReporteAdmin(admin.ModelAdmin):
    """
    Administración de registros de reportes generados
    """
    
    list_display = [
        'id',
        'tipo_badge',
        'formato_badge',
        'generado_por',
        'fecha_generacion_formateada',
        'total_registros',
        'tiempo_generacion_formateado',
        'ip_address'
    ]
    
    list_filter = [
        'tipo',
        'formato',
        'fecha_generacion',
        'generado_por'
    ]
    
    search_fields = [
        'generado_por__username',
        'generado_por__first_name',
        'generado_por__last_name',
        'ip_address'
    ]
    
    readonly_fields = [
        'tipo',
        'formato',
        'generado_por',
        'fecha_generacion',
        'filtros_aplicados',
        'total_registros',
        'tiempo_generacion',
        'ip_address',
        'filtros_legibles'
    ]
    
    #date_hierarchy = 'fecha_generacion'
    
    ordering = ['-fecha_generacion']
    
    list_per_page = 50
    
    fieldsets = (
        ('Información del Reporte', {
            'fields': ('tipo', 'formato', 'total_registros')
        }),
        ('Auditoría', {
            'fields': ('generado_por', 'fecha_generacion', 'ip_address')
        }),
        ('Filtros Aplicados', {
            'fields': ('filtros_legibles', 'filtros_aplicados'),
            'classes': ('collapse',)
        }),
        ('Rendimiento', {
            'fields': ('tiempo_generacion',),
            'classes': ('collapse',)
        }),
    )
    
    def tipo_badge(self, obj):
        """Muestra el tipo con un badge de color"""
        colores = {
            'solicitudes': '#2e7d32',
            'empresas': '#1976d2',
            'programas': '#f57c00',
            'instructores': '#7b1fa2',
            'consolidado': '#c62828',
        }
        color = colores.get(obj.tipo, '#757575')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">{}</span>',
            color,
            obj.get_tipo_display()
        )
    tipo_badge.short_description = 'Tipo'
    
    def formato_badge(self, obj):
        """Muestra el formato con icono"""
        iconos = {
            'pdf': '📄',
            'excel': '📊'
        }
        icono = iconos.get(obj.formato, '📁')
        return format_html(
            '{} <strong>{}</strong>',
            icono,
            obj.formato.upper()
        )
    formato_badge.short_description = 'Formato'
    
    def fecha_generacion_formateada(self, obj):
        """Muestra la fecha en formato legible"""
        return obj.fecha_generacion.strftime('%d/%m/%Y %H:%M:%S')
    fecha_generacion_formateada.short_description = 'Fecha/Hora'
    fecha_generacion_formateada.admin_order_field = 'fecha_generacion'
    
    def tiempo_generacion_formateado(self, obj):
        """Muestra el tiempo de generación de forma legible"""
        if obj.tiempo_generacion < 1:
            return f"{obj.tiempo_generacion * 1000:.0f} ms"
        return f"{obj.tiempo_generacion:.2f} seg"
    tiempo_generacion_formateado.short_description = 'Tiempo'
    tiempo_generacion_formateado.admin_order_field = 'tiempo_generacion'
    
    def filtros_legibles(self, obj):
        """Muestra los filtros en formato legible"""
        return obj.get_filtros_legibles()
    filtros_legibles.short_description = 'Filtros Aplicados'
    
    def has_add_permission(self, request):
        """No se pueden crear reportes manualmente desde el admin"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """No se pueden editar reportes"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Solo superusuarios pueden eliminar reportes"""
        return request.user.is_superuser
    
    actions = ['eliminar_seleccionados']
    
    def eliminar_seleccionados(self, request, queryset):
        """Acción personalizada para eliminar reportes seleccionados"""
        if not request.user.is_superuser:
            self.message_user(request, "Solo superusuarios pueden eliminar reportes.", level='error')
            return
        
        cantidad = queryset.count()
        queryset.delete()
        self.message_user(request, f"{cantidad} reporte(s) eliminado(s) exitosamente.")
    eliminar_seleccionados.short_description = "Eliminar reportes seleccionados"