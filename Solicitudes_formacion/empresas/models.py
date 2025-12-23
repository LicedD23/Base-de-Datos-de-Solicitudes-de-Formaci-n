from django.db import models

class Empresa(models.Model):
    nombre = models.CharField(max_length=200)
    nit = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        unique=True,  
        verbose_name='NIT',
        help_text='Número de Identificación Tributaria (único)'
    )
    direccion = models.CharField(max_length=250, blank=True, default='')
    contacto = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    correo = models.EmailField()
    numero_trabajadores = models.IntegerField()
    municipio = models.CharField(max_length=100)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True, verbose_name='Activo')

    class Meta:
        verbose_name_plural = "Empresas"

    def __str__(self):
        return f"{self.nombre} - NIT: {self.nit or 'Sin NIT'}"