from django.db import models
from django.utils import timezone
from empresas.models import Empresa
from programas.models import Programa
from instructores.models import Instructor

class Solicitud(models.Model):
    ESTADO_CHOICES = [
        ('RECIBIDA', 'Recibida'),
        ('RESPONDIDA', 'Respondida'),
        ('ATENDIDA', 'Atendida'),
        ('FINALIZADA', 'Finalizada'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    programa = models.ForeignKey(Programa, on_delete=models.CASCADE)
    fecha_recepcion = models.DateTimeField(default=timezone.now)
    instructor_asignado = models.ForeignKey(Instructor, on_delete=models.SET_NULL, null=True, blank=True)
    fecha_respuesta = models.DateTimeField(null=True, blank=True)
    fecha_atencion = models.DateTimeField(null=True, blank=True)
    fecha_finalizacion  = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='RECIBIDA')
    observaciones = models.TextField(blank=True)
    numero_aprendices = models.IntegerField(null=True, blank=True)
    
    correo_remitente = models.EmailField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Correo del Remitente",
        help_text="Email desde donde se envió la solicitud original"
    )
    
    # Campo para documentos PDF
    documento_pdf = models.FileField(
        upload_to='solicitudes/documentos/%Y/%m/',
        blank=True,
        null=True,
        verbose_name="Documento PDF",
        help_text="Documento adjunto de la solicitud (solo PDF)"
    )
    
    class Meta:
        verbose_name_plural = "Solicitudes"
        ordering = ['-fecha_recepcion']

    def __str__(self):
        return f"{self.empresa.nombre} - {self.programa.nombre}"
    
    def puede_cambiar_a_estado(self, nuevo_estado):
        """Valida si es posible cambiar al nuevo estado segun el  flujo logico"""
        flujo_valido = {
            'RECIBIDA': ['RESPONDIDA'],
            'RESPONDIDA': ['ATENDIDA', 'FINALIZADA'],
            'ATENDIDA': ['FINALIZADA', 'RESPONDIDA'],
            'FINALIZADA': []
        }
        estados_permitidos = flujo_valido.get(self.estado,[])
        return nuevo_estado in estados_permitidos

class DocumentoSolicitud(models.Model):
    """Modelo para almacenar múltiples documentos PDF por solicitud"""
    solicitud = models.ForeignKey(
        Solicitud, 
        on_delete=models.CASCADE, 
        related_name='documentos'
    )
    archivo = models.FileField(
        upload_to='solicitudes/documentos/%Y/%m/',
        verbose_name="Archivo PDF"
    )
    nombre_archivo = models.CharField(
        max_length=255,
        verbose_name="Nombre del archivo"
    )
    fecha_subida = models.DateTimeField(
        default=timezone.now,
        verbose_name="Fecha de subida"
    )
    
    class Meta:
        ordering = ['-fecha_subida']
        verbose_name = "Documento de Solicitud"
        verbose_name_plural = "Documentos de Solicitudes"
    
    def __str__(self):
        return f"{self.nombre_archivo} - Solicitud #{self.solicitud.id}"
