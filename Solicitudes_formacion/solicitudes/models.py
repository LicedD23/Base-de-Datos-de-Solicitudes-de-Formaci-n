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
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='RECIBIDA')
    observaciones = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "Solicitudes"
        ordering = ['-fecha_recepcion']

    def __str__(self):
        return f"{self.empresa.nombre} - {self.programa.nombre}"
