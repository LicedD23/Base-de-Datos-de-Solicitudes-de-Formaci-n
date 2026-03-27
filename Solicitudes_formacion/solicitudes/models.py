from django.db import models
from django.utils import timezone
from empresas.models import Empresa
from programas.models import Programa
from instructores.models import Instructor


class Solicitud(models.Model):
    # Orden refleja el flujo real del negocio
    ESTADO_CHOICES = [
        ('RECIBIDA',   'Recibida'),
        ('ATENDIDA',   'Atendida'),
        ('RESPONDIDA', 'Respondida'),
        ('FINALIZADA', 'Finalizada'),
    ]

    # Flujo válido de transiciones como constante de clase
    # Definido aquí para que sea la única fuente de verdad en todo el proyecto
    FLUJO_VALIDO = {
        'RECIBIDA':   ['ATENDIDA'],
        'ATENDIDA':   ['RESPONDIDA'],
        'RESPONDIDA': ['FINALIZADA'],
        'FINALIZADA': [],
    }

    SIGUIENTE_ESTADO = {
        'RECIBIDA':   'ATENDIDA',
        'ATENDIDA':   'RESPONDIDA',
        'RESPONDIDA': 'FINALIZADA',
        'FINALIZADA': None,
    }

    SIGUIENTE_ACCION = {
        'RECIBIDA':   'Asignar instructor',
        'ATENDIDA':   'Enviar respuesta a la empresa',
        'RESPONDIDA': 'Finalizar formación',
        'FINALIZADA': None,
    }

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    programa = models.ForeignKey(Programa, on_delete=models.CASCADE)
    fecha_recepcion = models.DateTimeField(default=timezone.now)
    instructor_asignado = models.ForeignKey(
        Instructor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    fecha_respuesta    = models.DateTimeField(null=True, blank=True)
    fecha_atencion     = models.DateTimeField(null=True, blank=True)
    fecha_finalizacion = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='RECIBIDA',
    )
    observaciones      = models.TextField(blank=True)
    numero_aprendices  = models.IntegerField(null=True, blank=True)

    correo_remitente = models.EmailField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Correo del Remitente",
        help_text="Email desde donde se envió la solicitud original",
    )

    documento_pdf = models.FileField(
        upload_to='solicitudes/documentos/%Y/%m/',
        blank=True,
        null=True,
        verbose_name="Documento PDF",
        help_text="Documento adjunto de la solicitud (solo PDF)",
    )

    class Meta:
        verbose_name_plural = "Solicitudes"
        ordering = ['-fecha_recepcion']

    def __str__(self):
        return f"{self.empresa.nombre} - {self.programa.nombre}"

    # ------------------------------------------------------------------
    # Lógica de flujo de estados
    # ------------------------------------------------------------------

    def puede_cambiar_a_estado(self, nuevo_estado):
        """
        Valida si la transición al nuevo_estado es permitida.

        Flujo único aceptado:
            RECIBIDA → ATENDIDA → RESPONDIDA → FINALIZADA

        - RECIBIDA  → ATENDIDA:   se asigna instructor, comienza la formación.
        - ATENDIDA  → RESPONDIDA: se envía correo a la empresa notificando.
        - RESPONDIDA→ FINALIZADA: la formación concluye exitosamente.
        """
        return nuevo_estado in self.FLUJO_VALIDO.get(self.estado, [])

    def siguiente_estado(self):
        """Retorna el código del siguiente estado esperado, o None si es terminal."""
        return self.SIGUIENTE_ESTADO.get(self.estado)

    def siguiente_accion(self):
        """
        Describe en lenguaje natural qué acción debe realizar el usuario
        para avanzar la solicitud al siguiente estado.
        Retorna None cuando la solicitud está finalizada.
        """
        return self.SIGUIENTE_ACCION.get(self.estado)

    def get_siguiente_accion_display(self):
        """Alias legible para usar directamente en templates."""
        return self.siguiente_accion()

    # ------------------------------------------------------------------
    # Helpers de estado para templates (evitan lógica en el HTML)
    # ------------------------------------------------------------------

    def esta_finalizada(self):
        return self.estado == 'FINALIZADA'

    def requiere_instructor(self):
        """True cuando aún no tiene instructor y está en RECIBIDA."""
        return self.estado == 'RECIBIDA' and not self.instructor_asignado

    def puede_enviar_respuesta(self):
        """True cuando la solicitud está ATENDIDA y puede recibir un correo de respuesta."""
        return self.estado == 'ATENDIDA'

    def puede_finalizar(self):
        """True cuando la empresa ya fue notificada y se puede cerrar la solicitud."""
        return self.estado == 'RESPONDIDA'


class DocumentoSolicitud(models.Model):
    """Modelo para almacenar múltiples documentos PDF por solicitud."""

    solicitud = models.ForeignKey(
        Solicitud,
        on_delete=models.CASCADE,
        related_name='documentos',
    )
    archivo = models.FileField(
        upload_to='solicitudes/documentos/%Y/%m/',
        verbose_name="Archivo PDF",
    )
    nombre_archivo = models.CharField(
        max_length=255,
        verbose_name="Nombre del archivo",
    )
    fecha_subida = models.DateTimeField(
        default=timezone.now,
        verbose_name="Fecha de subida",
    )

    class Meta:
        ordering = ['-fecha_subida']
        verbose_name = "Documento de Solicitud"
        verbose_name_plural = "Documentos de Solicitudes"

    def __str__(self):
        return f"{self.nombre_archivo} - Solicitud #{self.solicitud.id}"