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

    # ── NUEVO: rango real de la formación dictada por el instructor ──────
    fecha_fin_formacion = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha fin de formación",
        help_text="Fecha en que el instructor termina de dictar la formación. "
                  "Al cumplirse, la solicitud se finaliza automáticamente.",
    )

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
        return nuevo_estado in self.FLUJO_VALIDO.get(self.estado, [])

    def siguiente_estado(self):
        return self.SIGUIENTE_ESTADO.get(self.estado)

    def siguiente_accion(self):
        return self.SIGUIENTE_ACCION.get(self.estado)

    def get_siguiente_accion_display(self):
        return self.siguiente_accion()

    # ------------------------------------------------------------------
    # Helpers de estado para templates
    # ------------------------------------------------------------------

    def esta_finalizada(self):
        return self.estado == 'FINALIZADA'

    def requiere_instructor(self):
        return self.estado == 'RECIBIDA' and not self.instructor_asignado

    def puede_enviar_respuesta(self):
        return self.estado == 'ATENDIDA'

    def puede_finalizar(self):
        return self.estado == 'RESPONDIDA'

    # ------------------------------------------------------------------
    # Helpers de formación
    # ------------------------------------------------------------------

    def formacion_en_rango(self, fecha=None):
        """
        Retorna True si hoy (o la fecha dada) cae dentro del rango
        de formación del instructor asignado.
        """
        if not self.fecha_atencion:
            return False
        fecha = fecha or timezone.now().date()
        inicio = self.fecha_atencion.date()
        fin    = self.fecha_fin_formacion  # puede ser None
        if fin:
            return inicio <= fecha <= fin
        return inicio <= fecha

    def formacion_finalizada_por_fecha(self):
        """
        True cuando la fecha_fin_formacion ya se cumplió y la solicitud
        aún no está marcada como FINALIZADA.
        """
        if not self.fecha_fin_formacion:
            return False
        return (
            self.fecha_fin_formacion <= timezone.now().date()
            and self.estado != 'FINALIZADA'
        )


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