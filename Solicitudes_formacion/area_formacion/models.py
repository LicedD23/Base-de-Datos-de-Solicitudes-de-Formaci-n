from django.db import models 



class Area(models.Model):
    """Áreas de formación (Maquinaria, Construcción, Seguridad, etc.)"""
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Áreas"
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


