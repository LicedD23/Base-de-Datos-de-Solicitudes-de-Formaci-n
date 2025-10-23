from django.db import models
from area_formacion.models import Area


class Programa(models.Model):
    """Programas de formación dentro de cada área"""
    area = models.ForeignKey(
        Area, 
        on_delete=models.CASCADE, 
        related_name='programas'
    )
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    duracion_horas = models.IntegerField(
        null=True, 
        blank=True, 
        help_text="Duración en horas"
    )
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Programas"
        ordering = ['area', 'nombre']
        unique_together = ['area', 'nombre']

    def __str__(self):
        return f"{self.area.nombre} - {self.nombre}"