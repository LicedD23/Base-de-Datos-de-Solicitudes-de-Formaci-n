from django.db import models
from programas.models import Programa

class Instructor(models.Model):
    nombre = models.CharField(max_length=100)
    especialidad = models.ManyToManyField(Programa, related_name='instructores')
    telefono = models.CharField(max_length=20)
    correo = models.EmailField()
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Instructores"

    def __str__(self):
        return self.nombre
