from django.db import models

# Create your models here.
class Empresa(models.Model):
    nombre = models.CharField(max_length=200)
    contacto = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    correo = models.EmailField()
    numero_trabajadores = models.IntegerField()
    municipio = models.CharField(max_length=100)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Empresas"

    def __str__(self):
        return self.nombre