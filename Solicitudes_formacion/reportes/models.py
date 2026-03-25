"""
Modelo de Reporte para auditoría y trazabilidad
Sistema de Gestión de Solicitudes SENA
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Reporte(models.Model):
    """
    Registro de reportes generados para auditoría y trazabilidad.
    NO guarda el archivo, solo metadata para cumplir con requisitos de auditoría.
    """
    
    TIPO_CHOICES = [
        ('solicitudes', 'Solicitudes de Formación'),
        ('empresas', 'Directorio de Empresas'),
        ('programas', 'Catálogo de Programas'),
        ('instructores', 'Directorio de Instructores'),
        ('consolidado', 'Reporte Consolidado'),
    ]
    
    FORMATO_CHOICES = [
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
    ]
    
    # Información básica del reporte
    tipo = models.CharField(
        max_length=20, 
        choices=TIPO_CHOICES,
        verbose_name="Tipo de Reporte",
        db_index=True
    )
    
    formato = models.CharField(
        max_length=10, 
        choices=FORMATO_CHOICES,
        verbose_name="Formato"
    )
    
    # Auditoría (quién y cuándo)
    generado_por = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        verbose_name="Generado por",
        related_name='reportes_generados'
    )
    
    fecha_generacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de Generación",
        db_index=True
    )
    
    # Filtros aplicados (para saber qué datos se consultaron)
    filtros_aplicados = models.JSONField(
        blank=True, 
        null=True,
        verbose_name="Filtros Aplicados",
        help_text="Filtros usados en la generación del reporte"
    )
    
    # Metadata adicional
    total_registros = models.IntegerField(
        default=0,
        verbose_name="Total de Registros",
        help_text="Cantidad de registros incluidos en el reporte"
    )
    
    tiempo_generacion = models.FloatField(
        default=0,
        verbose_name="Tiempo de Generación (seg)",
        help_text="Tiempo que tomó generar el reporte en segundos"
    )
    
    # Información adicional
    ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        verbose_name="Dirección IP",
        help_text="IP desde donde se generó el reporte"
    )
    
    class Meta:
        verbose_name = 'Reporte'
        verbose_name_plural = 'Reportes'
        ordering = ['-fecha_generacion']
        indexes = [
            models.Index(fields=['-fecha_generacion']),
            models.Index(fields=['generado_por', '-fecha_generacion']),
            models.Index(fields=['tipo', '-fecha_generacion']),
        ]
    
    def __str__(self):
        return f"{self.get_tipo_display()} ({self.formato.upper()}) - {self.generado_por.username} - {self.fecha_generacion.strftime('%d/%m/%Y %H:%M')}"
    
    @classmethod
    def limpiar_reportes_antiguos(cls, dias=90):
        """
        Elimina registros de reportes más antiguos de X días.
        Útil para mantenimiento automático.
        """
        fecha_limite = timezone.now() - timezone.timedelta(days=dias)
        cantidad, _ = cls.objects.filter(fecha_generacion__lt=fecha_limite).delete()
        return cantidad
    
    @classmethod
    def reportes_por_usuario(cls, usuario):
        """Retorna estadísticas de reportes generados por un usuario"""
        return cls.objects.filter(generado_por=usuario).values('tipo', 'formato').annotate(
            total=models.Count('id')
        ).order_by('-total')
    
    @classmethod
    def reportes_del_dia(cls):
        """Retorna reportes generados hoy"""
        hoy = timezone.now().date()
        return cls.objects.filter(fecha_generacion__date=hoy)
    
    @classmethod
    def reportes_del_mes(cls):
        """Retorna reportes generados este mes"""
        hoy = timezone.now()
        inicio_mes = hoy.replace(day=1)
        return cls.objects.filter(fecha_generacion__gte=inicio_mes)
    
    def get_filtros_legibles(self):
        """Retorna los filtros en formato legible"""
        if not self.filtros_aplicados:
            return "Sin filtros"
        
        filtros = []
        for key, value in self.filtros_aplicados.items():
            if value:
                filtros.append(f"{key}: {value}")
        
        return " | ".join(filtros) if filtros else "Sin filtros"