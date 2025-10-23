from django.db import models 
from django.utils import timezone


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


class Programa(models.Model):
    """Programas de formación dentro de cada área"""
    area = models.ForeignKey(Area, on_delete=models.CASCADE, related_name='programas',null=True, blank=True)
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    duracion_horas = models.IntegerField(null=True, blank=True, help_text="Duración en horas")
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True,null=True, blank=True)

    class Meta:
        verbose_name_plural = "Programas"
        ordering = ['area', 'nombre']
        unique_together = ['area', 'nombre']  # No repetir programas en la misma área

    def __str__(self):
        return f"{self.area.nombre} - {self.nombre}"


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
    instructor_asignado = models.ForeignKey(
        Instructor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    fecha_respuesta = models.DateTimeField(null=True, blank=True)
    fecha_atencion = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='RECIBIDA'
    )
    observaciones = models.TextField(blank=True)
    
    class Meta:
        verbose_name_plural = "Solicitudes"
        ordering = ['-fecha_recepcion']
    
    def __str__(self):
        return f"{self.empresa.nombre} - {self.programa.nombre}"