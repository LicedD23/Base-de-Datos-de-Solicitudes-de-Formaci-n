"""
Módulo de generación de reportes en PDF y Excel
Sistema de Gestión de Solicitudes SENA
"""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, PageBreak
)

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from django.db.models import Count
from django.utils import timezone


# =============================================================================
# COLORES GLOBALES
# Definidos aquí para cambiarlos en un solo lugar si el diseño cambia.
# =============================================================================

# Colores PDF (formato ReportLab)
COLOR_VERDE        = colors.HexColor('#2e7d32')  # verde principal SENA
COLOR_VERDE_OSCURO = colors.HexColor('#1b5e20')  # verde oscuro para subtítulos
COLOR_VERDE_CLARO  = colors.HexColor('#f5f5f5')  # gris muy claro para filas alternas
COLOR_ROJO         = colors.HexColor('#b71c1c')  # rojo para instructores ocupados

# Colores Excel (formato hex sin #, requerido por openpyxl)
HEX_VERDE        = '2e7d32'  # verde principal SENA
HEX_VERDE_OSCURO = '1b5e20'  # verde para texto "Disponible"
HEX_ROJO         = 'b71c1c'  # rojo para texto "Ocupado"
HEX_VERDE_CLARO  = 'C8E6C9'  # fondo verde claro (disponible)
HEX_ROJO_CLARO   = 'FFCDD2'  # fondo rojo claro (ocupado)
HEX_VERDE_FILL   = 'E8F5E9'  # fondo muy claro para celdas de resumen
HEX_VERDE_ITALIC = '558b2f'  # verde para textos secundarios en cursiva


# =============================================================================
# FUNCIONES AUXILIARES GLOBALES
# Usadas tanto por PDFReportGenerator como por ExcelReportGenerator.
# =============================================================================

def _fmt_fecha(fecha, fmt='%d/%m/%Y'):
    """
    Formatea una fecha al estilo colombiano dd/mm/aaaa.
    Si la fecha es None retorna '—' en lugar de lanzar un error.

    Ejemplo:
        _fmt_fecha(sol.fecha_recepcion)  →  '15/03/2025'
        _fmt_fecha(None)                 →  '—'
    """
    return fecha.strftime(fmt) if fecha else '—'


def _fmt_fecha_hora(fecha, fmt='%d/%m/%Y %H:%M'):
    """
    Igual que _fmt_fecha pero incluye la hora.

    Ejemplo:
        _fmt_fecha_hora(sol.fecha_recepcion)  →  '15/03/2025 09:30'
        _fmt_fecha_hora(None)                 →  '—'
    """
    return fecha.strftime(fmt) if fecha else '—'


def get_disponibilidad_instructor(instructor):
    """
    Revisa si un instructor tiene alguna formación activa HOY.

    Lógica:
        - Busca solicitudes con fecha de atención registrada y no finalizadas
        - Recorre cada solicitud y verifica si hoy cae dentro del rango
          fecha_atencion → fecha_fin_formacion
        - Si encuentra una → el instructor está OCUPADO
        - Si no encuentra ninguna → está DISPONIBLE

    Retorna un diccionario:
        { 'ocupado': True/False, 'etiqueta': 'Ocupado'/'Disponible' }
    """
    hoy     = timezone.now().date()
    ocupado = False

    # Traemos solo las solicitudes activas y los campos que necesitamos
    solicitudes_activas = instructor.solicitud_set.filter(
        fecha_atencion__isnull=False,
    ).exclude(estado='FINALIZADA').only(
        'fecha_atencion', 'fecha_fin_formacion', 'estado'
    )

    for sol in solicitudes_activas:
        fecha_inicio = sol.fecha_atencion.date()
        fecha_fin    = sol.fecha_fin_formacion  # puede ser None si no tiene fecha fin

        # El instructor está ocupado si hoy cae dentro del rango de la formación.
        # Si no tiene fecha_fin se asume que sigue activa.
        if fecha_inicio <= hoy and (fecha_fin is None or fecha_fin >= hoy):
            ocupado = True
            break  # con una formación activa es suficiente

    return {
        'ocupado':  ocupado,
        'etiqueta': 'Ocupado' if ocupado else 'Disponible',
    }


# =============================================================================
# GENERADOR DE REPORTES PDF
# Usa la librería ReportLab para construir archivos PDF.
# Cada método público genera un tipo de reporte distinto y retorna un buffer
# (archivo en memoria) listo para ser descargado desde la vista.
# =============================================================================

class PDFReportGenerator:
    """
    Genera reportes PDF con el estilo visual del SENA.

    Uso básico desde una vista Django:
        generator = PDFReportGenerator()
        buffer    = generator.generate_solicitudes_report(solicitudes)
        # buffer contiene el PDF en memoria listo para enviar al navegador
    """

    def __init__(self):
        # Cargamos los estilos base de ReportLab y agregamos los nuestros
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()

    def setup_custom_styles(self):
        """
        Registra los estilos de texto personalizados del SENA.
        Se llama automáticamente desde __init__ al crear el generador.

        Estilos registrados:
            CustomTitle   → título principal grande y centrado
            CustomSubtitle→ subtítulo de sección
            SectionHeader → encabezado de subsección
            TableCell     → texto estándar dentro de celdas de tabla
            Disponible    → texto verde para instructores disponibles
            Ocupado       → texto rojo para instructores ocupados
        """
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=COLOR_VERDE,
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold',
        ))
        self.styles.add(ParagraphStyle(
            name='CustomSubtitle',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=COLOR_VERDE_OSCURO,
            spaceAfter=20,
            fontName='Helvetica-Bold',
        ))
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading3'],
            fontSize=12,
            textColor=COLOR_VERDE,
            spaceAfter=10,
            spaceBefore=15,
            fontName='Helvetica-Bold',
        ))
        self.styles.add(ParagraphStyle(
            name='TableCell',
            parent=self.styles['Normal'],
            fontSize=8,
            leading=11,
            alignment=TA_CENTER,
            wordWrap='CJK',
            fontName='Helvetica',
        ))
        self.styles.add(ParagraphStyle(
            name='Disponible',
            parent=self.styles['Normal'],
            fontSize=8,
            leading=11,
            alignment=TA_CENTER,
            textColor=COLOR_VERDE_OSCURO,
            fontName='Helvetica-Bold',
        ))
        self.styles.add(ParagraphStyle(
            name='Ocupado',
            parent=self.styles['Normal'],
            fontSize=8,
            leading=11,
            alignment=TA_CENTER,
            textColor=COLOR_ROJO,
            fontName='Helvetica-Bold',
        ))

    def _disponibilidad_paragraph(self, instructor):
        """
        Crea un Paragraph coloreado según la disponibilidad del instructor.
        Verde si está disponible, rojo si está ocupado.
        Usado en las columnas 'Disponibilidad' de tablas PDF.
        """
        info          = get_disponibilidad_instructor(instructor)
        # El nombre del estilo coincide con la etiqueta: 'Disponible' o 'Ocupado'
        nombre_estilo = 'Ocupado' if info['ocupado'] else 'Disponible'
        return Paragraph(info['etiqueta'], self.styles[nombre_estilo])

    def _get_estilo_tabla(self, font_header=9, font_datos=8,
                          pad_v=6, pad_h=4):
        """
        Retorna el TableStyle estándar para todas las tablas del SENA.

        Centralizar el estilo aquí evita repetirlo en cada reporte.
        Solo varían los tamaños de fuente y padding según el espacio disponible.

        Parámetros:
            font_header → tamaño de fuente del encabezado (fila verde)
            font_datos  → tamaño de fuente de las filas de datos
            pad_v       → padding vertical (arriba y abajo de cada celda)
            pad_h       → padding horizontal (izquierda y derecha de cada celda)
        """
        return TableStyle([
            # ── Fila de encabezado (índice 0) ────────────────────────────
            ('BACKGROUND',    (0, 0), (-1,  0), COLOR_VERDE),        # fondo verde
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.whitesmoke),  # texto blanco
            ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0), font_header),
            # ── Filas de datos (índice 1 en adelante) ────────────────────
            ('BACKGROUND',    (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR',     (0, 1), (-1, -1), colors.black),
            ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE',      (0, 1), (-1, -1), font_datos),
            # Filas alternas en gris muy claro para mejor lectura
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, COLOR_VERDE_CLARO]),
            # ── Toda la tabla ────────────────────────────────────────────
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING',    (0, 0), (-1, -1), pad_v),
            ('BOTTOMPADDING', (0, 0), (-1, -1), pad_v),
            ('LEFTPADDING',   (0, 0), (-1, -1), pad_h),
            ('RIGHTPADDING',  (0, 0), (-1, -1), pad_h),
        ])

    def add_header_footer(self, canvas, doc):
        """
        Dibuja el encabezado y pie de página en cada hoja del PDF.
        ReportLab llama a esta función automáticamente al construir el documento.
        No se llama manualmente — se pasa como parámetro a doc.build().
        """
        canvas.saveState()

        # Rectángulo verde en la parte superior de la página
        canvas.setFillColorRGB(0.18, 0.49, 0.20)
        canvas.rect(0, letter[1] - 60, letter[0], 60, fill=1)

        # Nombre de la institución en blanco
        canvas.setFillColorRGB(1, 1, 1)
        canvas.setFont('Helvetica-Bold', 16)
        canvas.drawString(50, letter[1] - 35, "SENA - Servicio Nacional de Aprendizaje")
        canvas.setFont('Helvetica', 10)
        canvas.drawString(50, letter[1] - 50, "Sistema de Gestión de Solicitudes de Formación")

        # Pie de página: fecha de generación y número de página
        canvas.setFillColorRGB(0.5, 0.5, 0.5)
        canvas.setFont('Helvetica', 8)
        canvas.drawString(50, 30, f"Generado: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
        canvas.drawRightString(letter[0] - 50, 30, f"Página {doc.page}")

        canvas.restoreState()

    # =========================================================================
    # REPORTE DE SOLICITUDES — PDF
    # =========================================================================

    def generate_solicitudes_report(self, solicitudes, filtros=None):
        """
        Genera el reporte PDF de solicitudes de formación.

        Incluye:
            - Tabla de resumen con conteo por estado
            - Tabla detallada con máximo 50 solicitudes
            - Nota al pie si hay más de 50

        Parámetros:
            solicitudes → queryset de Solicitud
            filtros     → texto con los filtros aplicados (opcional)
        """
        buffer = io.BytesIO()
        doc    = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            topMargin=80, bottomMargin=50,
            leftMargin=36, rightMargin=36,
            title="Reporte de Solicitudes - SENA",
        )
        elements = []

        # ── Título y filtros ──────────────────────────────────────────────
        elements.append(Paragraph(
            "REPORTE DE SOLICITUDES DE FORMACIÓN",
            self.styles['CustomTitle']
        ))
        elements.append(Spacer(1, 0.2 * inch))

        if filtros:
            elements.append(Paragraph(
                f"<b>Filtros aplicados:</b> {filtros}",
                self.styles['Normal']
            ))
            elements.append(Spacer(1, 0.2 * inch))

        # ── Tabla de resumen por estado ───────────────────────────────────
        total = solicitudes.count()

        stats_data = [
            # Fila de encabezados
            ['Total Solicitudes', 'Recibidas', 'Atendidas', 'Respondidas', 'Finalizadas'],
            # Fila de valores
            [
                str(total),
                str(solicitudes.filter(estado='RECIBIDA').count()),
                str(solicitudes.filter(estado='ATENDIDA').count()),
                str(solicitudes.filter(estado='RESPONDIDA').count()),
                str(solicitudes.filter(estado='FINALIZADA').count()),
            ]
        ]
        stats_table = Table(stats_data, colWidths=[1.4 * inch] * 5)
        stats_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0), COLOR_VERDE),
            ('TEXTCOLOR',     (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1, 0),  10),
            ('BOTTOMPADDING', (0, 0), (-1, 0),  12),
            ('BACKGROUND',    (0, 1), (-1, -1), colors.beige),
            ('GRID',          (0, 0), (-1, -1), 1, colors.grey),
        ]))
        elements.append(stats_table)
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph("Detalle de Solicitudes", self.styles['SectionHeader']))

        # ── Tabla detallada de solicitudes (máximo 50) ────────────────────
        headers = [
            'NIT Empresa', 'Empresa', 'Programa', 'Estado',
            'F. Recepción', 'F. Inicio Form.', 'F. Respuesta', 'F. Fin Form.',
            'Instructor', 'Disponibilidad',
        ]
        # Anchos de columna en pulgadas (deben sumar el ancho total disponible)
        col_widths = [
            0.85, 1.40, 1.60, 0.85,
            0.82, 0.82, 0.82, 0.82,
            1.25, 0.87,
        ]

        # Primera fila: encabezados
        data = [[Paragraph(h, self.styles['TableCell']) for h in headers]]

        # Filas de datos
        for sol in solicitudes[:50]:
            nit = sol.empresa.nit if hasattr(sol.empresa, 'nit') and sol.empresa.nit else 'Sin NIT'

            # La celda de disponibilidad solo aplica si hay instructor asignado
            if sol.instructor_asignado:
                celda_disp = self._disponibilidad_paragraph(sol.instructor_asignado)
            else:
                celda_disp = Paragraph('—', self.styles['TableCell'])

            data.append([
                Paragraph(nit,                                    self.styles['TableCell']),
                Paragraph(sol.empresa.nombre,                     self.styles['TableCell']),
                Paragraph(sol.programa.nombre,                    self.styles['TableCell']),
                Paragraph(sol.get_estado_display(),               self.styles['TableCell']),
                Paragraph(_fmt_fecha(sol.fecha_recepcion),        self.styles['TableCell']),
                Paragraph(_fmt_fecha(sol.fecha_atencion),         self.styles['TableCell']),
                Paragraph(_fmt_fecha(sol.fecha_respuesta),        self.styles['TableCell']),
                Paragraph(_fmt_fecha(sol.fecha_fin_formacion),    self.styles['TableCell']),
                Paragraph(
                    sol.instructor_asignado.nombre if sol.instructor_asignado else 'Sin asignar',
                    self.styles['TableCell']
                ),
                celda_disp,
            ])

        table = Table(data, colWidths=[w * inch for w in col_widths])
        table.setStyle(self._get_estilo_tabla(
            font_header=8, font_datos=7, pad_v=5, pad_h=3
        ))
        elements.append(table)

        # Nota si hay más de 50 solicitudes
        if total > 50:
            elements.append(Spacer(1, 0.2 * inch))
            elements.append(Paragraph(
                f"<i>Nota: Mostrando las primeras 50 solicitudes de {total} totales</i>",
                self.styles['Normal']
            ))

        doc.build(
            elements,
            onFirstPage=self.add_header_footer,
            onLaterPages=self.add_header_footer,
        )
        buffer.seek(0)
        return buffer

    # =========================================================================
    # REPORTE DE EMPRESAS — PDF
    # =========================================================================

    def generate_empresas_report(self, empresas):
        """
        Genera el reporte PDF del directorio de empresas.
        Muestra máximo 50 empresas con sus datos de contacto.
        """
        buffer = io.BytesIO()
        doc    = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=80, bottomMargin=50,
            leftMargin=40, rightMargin=40,
            title="Directorio de Empresas - SENA",
        )
        elements = []

        elements.append(Paragraph("DIRECTORIO DE EMPRESAS", self.styles['CustomTitle']))
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph(
            f"<b>Total de empresas:</b> {empresas.count()}",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.3 * inch))

        headers    = ['NIT', 'Empresa', 'Contacto', 'Teléfono', 'Correo', 'Municipio', 'N° Trab.']
        col_widths = [0.9, 1.6, 1.1, 0.85, 1.3, 0.9, 0.75]

        data = [[Paragraph(h, self.styles['TableCell']) for h in headers]]

        for emp in empresas[:50]:
            nit = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
            data.append([
                Paragraph(nit,                                                        self.styles['TableCell']),
                Paragraph(emp.nombre,                                                 self.styles['TableCell']),
                Paragraph(emp.contacto,                                               self.styles['TableCell']),
                Paragraph(emp.telefono or 'N/A',                                     self.styles['TableCell']),
                Paragraph(emp.correo,                                                 self.styles['TableCell']),
                Paragraph(emp.municipio if emp.municipio else 'N/A',                 self.styles['TableCell']),
                Paragraph(str(emp.numero_trabajadores) if emp.numero_trabajadores else '0',
                          self.styles['TableCell']),
            ])

        table = Table(data, colWidths=[w * inch for w in col_widths])
        table.setStyle(self._get_estilo_tabla(font_header=9, font_datos=8))
        elements.append(table)

        doc.build(
            elements,
            onFirstPage=self.add_header_footer,
            onLaterPages=self.add_header_footer,
        )
        buffer.seek(0)
        return buffer

    # =========================================================================
    # REPORTE DE PROGRAMAS — PDF
    # =========================================================================

    def generate_programas_report(self, programas):
        """
        Genera el reporte PDF del catálogo de programas de formación.
        Muestra máximo 50 programas.
        """
        buffer = io.BytesIO()
        doc    = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=80, bottomMargin=50,
            title="Programas de formacion - SENA",
        )
        elements = []

        total = programas.count()

        elements.append(Paragraph(
            "CATÁLOGO DE PROGRAMAS DE FORMACIÓN",
            self.styles['CustomTitle']
        ))
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph(
            f"<b>Total de programas activos:</b> {total}",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.3 * inch))

        headers    = ['Código', 'Nombre del Programa', 'Área', 'Duración', 'Estado']
        col_widths = [0.9, 3.0, 1.5, 0.8, 0.8]

        data = [[Paragraph(h, self.styles['TableCell']) for h in headers]]

        for prog in programas[:50]:
            data.append([
                Paragraph(prog.codigo or 'N/A',                                        self.styles['TableCell']),
                Paragraph(prog.nombre,                                                  self.styles['TableCell']),
                Paragraph(prog.area.nombre,                                             self.styles['TableCell']),
                Paragraph(f"{prog.duracion_horas}h" if prog.duracion_horas else 'N/A', self.styles['TableCell']),
                Paragraph('Activo' if prog.activo else 'Inactivo',                     self.styles['TableCell']),
            ])

        table = Table(data, colWidths=[w * inch for w in col_widths])
        table.setStyle(self._get_estilo_tabla(
            font_header=10, font_datos=9, pad_v=8, pad_h=5
        ))
        elements.append(table)

        if total > 50:
            elements.append(Spacer(1, 0.2 * inch))
            elements.append(Paragraph(
                f"<i>Nota: Mostrando los primeros 50 programas de {total} totales</i>",
                self.styles['Normal']
            ))

        doc.build(
            elements,
            onFirstPage=self.add_header_footer,
            onLaterPages=self.add_header_footer,
        )
        buffer.seek(0)
        return buffer

    # =========================================================================
    # REPORTE DE INSTRUCTORES — PDF
    # =========================================================================

    def generate_instructores_report(self, instructores):
        """
        Genera el reporte PDF del directorio de instructores.
        Incluye columna de disponibilidad con color verde/rojo.
        Muestra máximo 50 instructores.
        """
        buffer = io.BytesIO()
        doc    = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            topMargin=80, bottomMargin=50,
            leftMargin=40, rightMargin=40,
            title="Directorio de Instructores - SENA",
        )
        elements = []

        # Calcular estadísticas de disponibilidad
        total      = instructores.count()
        activos_qs = instructores.filter(activo=True)
        disponibles_hoy = sum(
            1 for inst in activos_qs
            if not get_disponibilidad_instructor(inst)['ocupado']
        )
        ocupados_hoy = activos_qs.count() - disponibles_hoy

        elements.append(Paragraph("DIRECTORIO DE INSTRUCTORES", self.styles['CustomTitle']))
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph(
            f"<b>Total de instructores:</b> {total} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<b>Activos:</b> {activos_qs.count()} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<b>Disponibles hoy:</b> {disponibles_hoy} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"<b>Ocupados hoy:</b> {ocupados_hoy}",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.3 * inch))

        headers    = ['Instructor', 'Cédula', 'Correo', 'Teléfono', 'Estado',
                      'Especialidades', 'Solicitudes', 'Disponibilidad']
        col_widths = [1.5, 1.0, 1.9, 0.95, 0.8, 0.95, 0.85, 1.05]

        data = [[Paragraph(h, self.styles['TableCell']) for h in headers]]

        for inst in instructores[:50]:
            data.append([
                Paragraph(inst.nombre,                                self.styles['TableCell']),
                Paragraph(inst.cedula if inst.cedula else 'N/A',     self.styles['TableCell']),
                Paragraph(inst.correo,                                self.styles['TableCell']),
                Paragraph(inst.telefono if inst.telefono else 'N/A', self.styles['TableCell']),
                Paragraph('Activo' if inst.activo else 'Inactivo',   self.styles['TableCell']),
                Paragraph(str(inst.especialidad.count()),             self.styles['TableCell']),
                Paragraph(str(inst.solicitud_set.count()),            self.styles['TableCell']),
                self._disponibilidad_paragraph(inst),
            ])

        table = Table(data, colWidths=[w * inch for w in col_widths])
        table.setStyle(self._get_estilo_tabla(font_header=9, font_datos=8))
        elements.append(table)

        if total > 50:
            elements.append(Spacer(1, 0.2 * inch))
            elements.append(Paragraph(
                f"<i>Nota: Mostrando los primeros 50 instructores de {total} totales</i>",
                self.styles['Normal']
            ))

        doc.build(
            elements,
            onFirstPage=self.add_header_footer,
            onLaterPages=self.add_header_footer,
        )
        buffer.seek(0)
        return buffer

    # =========================================================================
    # REPORTE CONSOLIDADO — PDF
    # =========================================================================

    def generate_consolidated_report(self, solicitudes, empresas, programas, instructores):
        """
        Genera el reporte consolidado PDF con las 4 secciones del sistema:
            1. Solicitudes de formación
            2. Directorio de empresas
            3. Programas de formación
            4. Directorio de instructores

        Cada sección está separada por un PageBreak (salto de página).
        """
        buffer = io.BytesIO()
        doc    = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=80, bottomMargin=50,
            leftMargin=50, rightMargin=50,
            title="Reporte Consolidado - SENA",
        )
        elements = []

        # ── Portada ───────────────────────────────────────────────────────
        elements.append(Paragraph(
            "REPORTE CONSOLIDADO DEL SISTEMA",
            self.styles['CustomTitle']
        ))
        elements.append(Spacer(1, 0.1 * inch))
        elements.append(Paragraph(
            "Sistema de Gestión de Solicitudes de Formación SENA",
            self.styles['CustomSubtitle']
        ))
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph(
            f"<b>Fecha de generación:</b> {timezone.now().strftime('%d/%m/%Y %H:%M')}",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.5 * inch))
        elements.append(Paragraph("RESUMEN EJECUTIVO", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))

        # Tabla resumen con los 4 módulos del sistema
        summary_data = [
            ['Módulo', 'Cantidad', 'Detalles'],
            ['Solicitudes', str(solicitudes.count()),
             f"Recibidas: {solicitudes.filter(estado='RECIBIDA').count()}, "
             f"Finalizadas: {solicitudes.filter(estado='FINALIZADA').count()}"],
            ['Empresas', str(empresas.count()),
             f"Con solicitudes activas: {empresas.filter(solicitud__isnull=False).distinct().count()}"],
            ['Programas', str(programas.count()),
             f"Activos: {programas.filter(activo=True).count()}"],
            ['Instructores', str(instructores.count()),
             f"Activos: {instructores.filter(activo=True).count()}"],
        ]
        summary_table = Table(summary_data, colWidths=[1.5*inch, 1*inch, 4*inch])
        summary_table.setStyle(self._get_estilo_tabla(font_header=9, font_datos=8))
        elements.append(summary_table)
        elements.append(PageBreak())

        # ── Sección 1: Solicitudes ────────────────────────────────────────
        elements.append(Paragraph("1. SOLICITUDES DE FORMACIÓN", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))

        # Tabla de distribución por estado con porcentajes
        total_sol = max(solicitudes.count(), 1)  # evitar división por cero
        sol_stats_data = [['Estado', 'Cantidad', 'Porcentaje']]

        for etiqueta, estado in [
            ('Recibidas',   'RECIBIDA'),
            ('Atendidas',   'ATENDIDA'),
            ('Respondidas', 'RESPONDIDA'),
            ('Finalizadas', 'FINALIZADA'),
        ]:
            cantidad = solicitudes.filter(estado=estado).count()
            sol_stats_data.append([
                etiqueta,
                str(cantidad),
                f"{cantidad / total_sol * 100:.1f}%",
            ])

        sol_stats_table = Table(sol_stats_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
        sol_stats_table.setStyle(self._get_estilo_tabla(
            font_header=10, font_datos=10, pad_v=8, pad_h=5
        ))
        elements.append(sol_stats_table)
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph("Últimas 10 Solicitudes", self.styles['SectionHeader']))
        elements.append(Spacer(1, 0.1 * inch))

        sol_headers    = [
            'NIT Empresa', 'Empresa', 'Programa', 'Estado',
            'F. Recepción', 'F. Inicio Form.', 'F. Respuesta', 'F. Fin Form.',
        ]
        sol_col_widths = [0.85, 1.35, 1.35, 0.80, 0.80, 0.80, 0.80, 0.80]
        sol_data       = [[Paragraph(h, self.styles['TableCell']) for h in sol_headers]]

        for sol in solicitudes[:10]:
            nit = sol.empresa.nit if hasattr(sol.empresa, 'nit') and sol.empresa.nit else 'Sin NIT'
            sol_data.append([
                Paragraph(nit,                                 self.styles['TableCell']),
                Paragraph(sol.empresa.nombre,                  self.styles['TableCell']),
                Paragraph(sol.programa.nombre,                 self.styles['TableCell']),
                Paragraph(sol.get_estado_display(),            self.styles['TableCell']),
                Paragraph(_fmt_fecha(sol.fecha_recepcion),     self.styles['TableCell']),
                Paragraph(_fmt_fecha(sol.fecha_atencion),      self.styles['TableCell']),
                Paragraph(_fmt_fecha(sol.fecha_respuesta),     self.styles['TableCell']),
                Paragraph(_fmt_fecha(sol.fecha_fin_formacion), self.styles['TableCell']),
            ])

        sol_table = Table(sol_data, colWidths=[w * inch for w in sol_col_widths])
        sol_table.setStyle(self._get_estilo_tabla(
            font_header=8, font_datos=7, pad_v=5, pad_h=3
        ))
        elements.append(sol_table)
        elements.append(PageBreak())

        # ── Sección 2: Empresas ───────────────────────────────────────────
        elements.append(Paragraph("2. DIRECTORIO DE EMPRESAS", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph(
            f"Total de empresas registradas: <b>{empresas.count()}</b>",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.2 * inch))

        emp_headers = ['NIT', 'Empresa', 'Contacto', 'Teléfono', 'Municipio', 'Solicitudes']
        emp_data    = [[Paragraph(h, self.styles['TableCell']) for h in emp_headers]]

        for emp in empresas[:15]:
            nit = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
            emp_data.append([
                Paragraph(nit,                            self.styles['TableCell']),
                Paragraph(emp.nombre or 'Sin nombre',     self.styles['TableCell']),
                Paragraph(emp.contacto or 'Sin contacto', self.styles['TableCell']),
                Paragraph(emp.telefono or 'N/A',          self.styles['TableCell']),
                Paragraph(emp.municipio or 'N/A',         self.styles['TableCell']),
                Paragraph(str(emp.solicitud_set.count()), self.styles['TableCell']),
            ])

        emp_table = Table(
            emp_data,
            colWidths=[1.1*inch, 1.8*inch, 1.2*inch, 0.9*inch, 1.0*inch, 0.9*inch]
        )
        emp_table.setStyle(self._get_estilo_tabla(font_header=9, font_datos=8))
        elements.append(emp_table)
        elements.append(PageBreak())

        # ── Sección 3: Programas ──────────────────────────────────────────
        elements.append(Paragraph("3. PROGRAMAS DE FORMACIÓN", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))

        # Tabla de programas por área (top 5)
        areas_stats = (
            programas.values('area__nombre')
            .annotate(total=Count('id'))
            .order_by('-total')[:5]
        )
        area_data = [['Área de Formación', 'Cantidad de Programas']]
        for area in areas_stats:
            area_data.append([
                Paragraph(area['area__nombre'] or 'Sin área', self.styles['TableCell']),
                Paragraph(str(area['total']),                 self.styles['TableCell']),
            ])

        area_table = Table(area_data, colWidths=[4.5*inch, 1.5*inch])
        area_table.setStyle(self._get_estilo_tabla(
            font_header=10, font_datos=10, pad_v=8, pad_h=5
        ))
        elements.append(area_table)
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph("Programas Más Solicitados", self.styles['SectionHeader']))
        elements.append(Spacer(1, 0.1 * inch))

        prog_headers    = ['Código', 'Programa', 'Área', 'Duración', 'Solicitudes']
        prog_col_widths = [0.9, 2.2, 1.6, 0.8, 1.0]
        prog_data       = [[Paragraph(h, self.styles['TableCell']) for h in prog_headers]]

        for prog in programas.annotate(num_sol=Count('solicitud')).order_by('-num_sol')[:15]:
            prog_data.append([
                Paragraph(prog.codigo or 'N/A',                                        self.styles['TableCell']),
                Paragraph(prog.nombre,                                                  self.styles['TableCell']),
                Paragraph(prog.area.nombre,                                             self.styles['TableCell']),
                Paragraph(f"{prog.duracion_horas}h" if prog.duracion_horas else 'N/A', self.styles['TableCell']),
                Paragraph(str(prog.num_sol),                                            self.styles['TableCell']),
            ])

        prog_table = Table(prog_data, colWidths=[w * inch for w in prog_col_widths])
        prog_table.setStyle(self._get_estilo_tabla(
            font_header=10, font_datos=9, pad_v=8, pad_h=5
        ))
        elements.append(prog_table)
        elements.append(PageBreak())

        # ── Sección 4: Instructores ───────────────────────────────────────
        elements.append(Paragraph("4. INSTRUCTORES", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))

        activos_qs      = instructores.filter(activo=True)
        disponibles_count = sum(
            1 for inst in activos_qs
            if not get_disponibilidad_instructor(inst)['ocupado']
        )
        ocupados_count = activos_qs.count() - disponibles_count

        elements.append(Paragraph(
            f"Total de instructores: <b>{instructores.count()}</b> "
            f"(Activos: <b>{activos_qs.count()}</b>)",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph(
            f"Disponibles hoy: <b>{disponibles_count}</b> &nbsp;|&nbsp; "
            f"Ocupados hoy: <b>{ocupados_count}</b>",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.2 * inch))

        inst_headers    = ['Instructor', 'Correo', 'Teléfono',
                           'Especialidades', 'Solicitudes', 'Disponibilidad']
        inst_col_widths = [1.4, 1.7, 0.8, 0.9, 0.8, 0.9]
        inst_data       = [[Paragraph(h, self.styles['TableCell']) for h in inst_headers]]

        for inst in instructores.filter(activo=True)[:20]:
            inst_data.append([
                Paragraph(inst.nombre,                               self.styles['TableCell']),
                Paragraph(inst.correo,                               self.styles['TableCell']),
                Paragraph(inst.telefono if inst.telefono else 'N/A', self.styles['TableCell']),
                Paragraph(str(inst.especialidad.count()),            self.styles['TableCell']),
                Paragraph(str(inst.solicitud_set.count()),           self.styles['TableCell']),
                self._disponibilidad_paragraph(inst),
            ])

        inst_table = Table(inst_data, colWidths=[w * inch for w in inst_col_widths])
        inst_table.setStyle(self._get_estilo_tabla(
            font_header=10, font_datos=9, pad_v=8, pad_h=5
        ))
        elements.append(inst_table)
        elements.append(Spacer(1, 0.5 * inch))
        elements.append(Paragraph(
            "<i>--- Fin del Reporte Consolidado ---</i>",
            self.styles['Normal']
        ))

        doc.build(
            elements,
            onFirstPage=self.add_header_footer,
            onLaterPages=self.add_header_footer,
        )
        buffer.seek(0)
        return buffer


# =============================================================================
# GENERADOR DE REPORTES EXCEL
# Usa la librería openpyxl para construir archivos .xlsx.
# Cada método público genera un tipo de reporte distinto y retorna un buffer.
# =============================================================================

class ExcelReportGenerator:
    """
    Genera reportes Excel con el formato visual del SENA.

    Uso básico desde una vista Django:
        generator = ExcelReportGenerator()
        buffer    = generator.generate_empresas_report(empresas)
        # buffer contiene el .xlsx en memoria listo para descargar
    """

    # Estilos de disponibilidad definidos como atributos de clase
    # para no recrearlos en cada llamada
    FILL_DISPONIBLE = PatternFill(start_color='C8E6C9', end_color='C8E6C9', fill_type='solid')
    FILL_OCUPADO    = PatternFill(start_color='FFCDD2', end_color='FFCDD2', fill_type='solid')
    FONT_DISPONIBLE = Font(bold=True, color=HEX_VERDE_OSCURO, size=10)
    FONT_OCUPADO    = Font(bold=True, color=HEX_ROJO,         size=10)

    def __init__(self):
        # Estilos reutilizados en todos los métodos
        self.header_fill = PatternFill(
            start_color=HEX_VERDE, end_color=HEX_VERDE, fill_type='solid'
        )
        self.header_font = Font(bold=True, color='FFFFFF', size=12)
        self.border      = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'),  bottom=Side(style='thin'),
        )

    def _apply_disponibilidad_cell(self, cell, instructor):
        """
        Escribe y colorea una celda de disponibilidad en Excel.
        Verde con texto 'Disponible' o rojo con texto 'Ocupado'.

        Parámetros:
            cell       → celda de openpyxl donde escribir
            instructor → objeto Instructor del modelo
        """
        info       = get_disponibilidad_instructor(instructor)
        cell.value = info['etiqueta']

        # Aplicar color según disponibilidad
        if info['ocupado']:
            cell.fill = self.FILL_OCUPADO
            cell.font = self.FONT_OCUPADO
        else:
            cell.fill = self.FILL_DISPONIBLE
            cell.font = self.FONT_DISPONIBLE

        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border    = self.border

    def apply_header_style(self, ws, row=1):
        """
        Aplica el estilo de encabezado (fondo verde, texto blanco) a
        todas las celdas de una fila completa.

        Parámetros:
            ws  → hoja de trabajo (worksheet) de openpyxl
            row → número de la fila a estilizar (por defecto la fila 1)
        """
        for cell in ws[row]:
            cell.fill      = self.header_fill
            cell.font      = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border    = self.border

    def adjust_column_width(self, ws):
        """
        Ajusta el ancho de cada columna según el contenido más largo.
        Mínimo 12 caracteres, máximo 60 caracteres de ancho.
        Se llama al final de cada reporte para que el Excel se vea ordenado.
        """
        for idx, column in enumerate(ws.columns, start=1):
            max_length    = 0
            column_letter = get_column_letter(idx)

            for cell in column:
                try:
                    if cell.value is not None:
                        largo = len(str(cell.value))
                        if largo > max_length:
                            max_length = largo
                except Exception:
                    pass

            # Aplicar ancho con límites mínimo y máximo
            ws.column_dimensions[column_letter].width = max(12, min(max_length + 4, 60))

    def _escribir_encabezados(self, ws, headers, fila=1):
        """
        Escribe una lista de encabezados en una fila y les aplica el estilo verde.

        Parámetros:
            ws      → hoja de trabajo
            headers → lista de strings con los nombres de columna
            fila    → número de fila donde escribir los encabezados
        """
        for col_idx, header in enumerate(headers, start=1):
            cell           = ws.cell(row=fila, column=col_idx, value=header)
            cell.fill      = self.header_fill
            cell.font      = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border    = self.border

    def _estilizar_filas_datos(self, ws, fila_inicio, fila_fin, total_columnas, col_saltar=None):
        """
        Aplica borde y alineación centrada a un rango de filas de datos.

        Parámetros:
            ws             → hoja de trabajo
            fila_inicio    → primera fila de datos
            fila_fin       → última fila de datos
            total_columnas → cantidad de columnas a estilizar
            col_saltar     → número de columna a omitir (ej: columna de disponibilidad
                             que ya tiene su propio estilo)
        """
        for row in ws.iter_rows(
            min_row=fila_inicio, max_row=fila_fin, max_col=total_columnas
        ):
            for cell in row:
                # Saltamos la columna que ya tiene estilo propio
                if col_saltar and cell.column == col_saltar:
                    continue
                cell.border    = self.border
                cell.alignment = Alignment(
                    horizontal='center', vertical='center', wrap_text=True
                )

    def _guardar_buffer(self, wb):
        """
        Guarda el workbook en memoria y retorna el buffer listo para descargar.
        Se usa al final de cada método generate_*_report.
        """
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer

    # =========================================================================
    # REPORTE DE SOLICITUDES — EXCEL
    # =========================================================================

    def generate_solicitudes_report(self, solicitudes, filtros=None):
        """
        Genera el reporte Excel de solicitudes con 12 columnas:
        NIT | Empresa | Programa | Área | Estado |
        F. Recepción | F. Inicio Form. | F. Respuesta | F. Fin Form. |
        Instructor | Disponibilidad | Observaciones
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "Solicitudes"

        # ── Título y metadata ─────────────────────────────────────────────
        ws['A1'] = 'REPORTE DE SOLICITUDES DE FORMACIÓN'
        ws['A1'].font      = Font(bold=True, size=16, color=HEX_VERDE)
        ws['A1'].alignment = Alignment(horizontal='center')
        ws.merge_cells('A1:L1')

        ws['A2'] = f'Generado: {timezone.now().strftime("%d/%m/%Y %H:%M")}'
        ws['A2'].font = Font(italic=True, size=10)
        ws.merge_cells('A2:L2')

        if filtros:
            ws['A3'] = f'Filtros aplicados: {filtros}'
            ws['A3'].font = Font(italic=True, size=10, color=HEX_VERDE_ITALIC)
            ws.merge_cells('A3:L3')

        # ── Tabla de resumen ──────────────────────────────────────────────
        ws['A4'] = 'RESUMEN ESTADÍSTICO'
        ws['A4'].font = Font(bold=True, size=12)

        stats_data = [
            ['Total Solicitudes', solicitudes.count(),
             'Recibidas',         solicitudes.filter(estado='RECIBIDA').count()],
            ['Atendidas',         solicitudes.filter(estado='ATENDIDA').count(),
             'Respondidas',       solicitudes.filter(estado='RESPONDIDA').count()],
            ['Finalizadas',       solicitudes.filter(estado='FINALIZADA').count(), '', ''],
        ]
        for row_idx, row_data in enumerate(stats_data, start=5):
            for col_idx, value in enumerate(row_data, start=1):
                cell           = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border    = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center')
                # Las celdas de etiqueta (columnas impares) van en verde claro
                if col_idx % 2 == 1:
                    cell.fill = PatternFill(
                        start_color=HEX_VERDE_FILL,
                        end_color=HEX_VERDE_FILL,
                        fill_type='solid'
                    )
                    cell.font = Font(bold=True)

        # ── Encabezados de la tabla principal ─────────────────────────────
        headers = [
            'NIT Empresa', 'Empresa', 'Programa', 'Área', 'Estado',
            'F. Recepción', 'F. Inicio Form.', 'F. Respuesta', 'F. Fin Form.',
            'Instructor', 'Disponibilidad', 'Observaciones',
        ]
        self._escribir_encabezados(ws, headers, fila=8)

        # ── Filas de datos ────────────────────────────────────────────────
        current_row = 9
        for sol in solicitudes:
            nit = sol.empresa.nit if hasattr(sol.empresa, 'nit') and sol.empresa.nit else 'Sin NIT'

            datos = [
                nit,
                sol.empresa.nombre,
                sol.programa.nombre,
                sol.programa.area.nombre,
                sol.get_estado_display(),
                _fmt_fecha_hora(sol.fecha_recepcion),
                _fmt_fecha(sol.fecha_atencion),
                _fmt_fecha_hora(sol.fecha_respuesta),
                _fmt_fecha(sol.fecha_fin_formacion),
                sol.instructor_asignado.nombre if sol.instructor_asignado else 'Sin asignar',
                None,   # columna 11: disponibilidad (se estiliza aparte)
                sol.observaciones[:100] if sol.observaciones else 'N/A',
            ]
            for col_idx, value in enumerate(datos, start=1):
                cell           = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border    = self.border
                cell.alignment = Alignment(
                    horizontal='center', vertical='center', wrap_text=True
                )

            # Columna 11: disponibilidad con color propio
            disp_cell = ws.cell(row=current_row, column=11)
            if sol.instructor_asignado:
                self._apply_disponibilidad_cell(disp_cell, sol.instructor_asignado)
            else:
                disp_cell.value     = '—'
                disp_cell.border    = self.border
                disp_cell.alignment = Alignment(horizontal='center', vertical='center')

            current_row += 1

        self.adjust_column_width(ws)
        return self._guardar_buffer(wb)

    # =========================================================================
    # REPORTE DE EMPRESAS — EXCEL
    # =========================================================================

    def generate_empresas_report(self, empresas):
        """
        Genera el reporte Excel del directorio de empresas.
        8 columnas: NIT | Nombre | Contacto | Teléfono | Correo |
                    Municipio | Dirección | N° Trabajadores
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "Empresas"

        ws['A1'] = 'DIRECTORIO DE EMPRESAS'
        ws['A1'].font = Font(bold=True, size=16, color=HEX_VERDE)
        ws.merge_cells('A1:H1')

        ws['A2'] = f'Total de empresas: {empresas.count()}'
        ws['A2'].font = Font(bold=True, size=11)

        headers = ['NIT', 'Nombre', 'Contacto', 'Teléfono',
                   'Correo', 'Municipio', 'Dirección', 'N° Trabajadores']
        self._escribir_encabezados(ws, headers, fila=4)

        current_row = 5
        for emp in empresas:
            nit = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
            datos = [
                nit, emp.nombre, emp.contacto,
                emp.telefono or 'N/A', emp.correo,
                emp.municipio or 'N/A', emp.direccion or 'N/A',
                emp.numero_trabajadores or 0,
            ]
            for col_idx, value in enumerate(datos, start=1):
                cell           = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border    = self.border
                cell.alignment = Alignment(
                    horizontal='center', vertical='center', wrap_text=True
                )
            current_row += 1

        self.adjust_column_width(ws)
        return self._guardar_buffer(wb)

    # =========================================================================
    # REPORTE DE PROGRAMAS — EXCEL
    # =========================================================================

    def generate_programas_report(self, programas):
        """
        Genera el reporte Excel del catálogo de programas.
        6 columnas: ID | Código | Nombre | Área | Duración (horas) | Estado
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "Programas"

        ws['A1'] = 'CATÁLOGO DE PROGRAMAS DE FORMACIÓN'
        ws['A1'].font = Font(bold=True, size=16, color=HEX_VERDE)
        ws.merge_cells('A1:F1')

        headers = ['ID', 'Código', 'Nombre', 'Área', 'Duración (horas)', 'Estado']
        self._escribir_encabezados(ws, headers, fila=3)

        current_row = 4
        for prog in programas:
            datos = [
                prog.id, prog.codigo or 'N/A', prog.nombre,
                prog.area.nombre, prog.duracion_horas or 0,
                'Activo' if prog.activo else 'Inactivo',
            ]
            for col_idx, value in enumerate(datos, start=1):
                cell           = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border    = self.border
                cell.alignment = Alignment(
                    horizontal='center', vertical='center', wrap_text=True
                )
            current_row += 1

        # Anchos fijos por contenido conocido (más eficiente que adjust_column_width)
        for col, width in zip(['A', 'B', 'C', 'D', 'E', 'F'], [8, 15, 45, 25, 18, 12]):
            ws.column_dimensions[col].width = width

        return self._guardar_buffer(wb)

    # =========================================================================
    # REPORTE DE INSTRUCTORES — EXCEL
    # =========================================================================

    def generate_instructores_report(self, instructores):
        """
        Genera el reporte Excel del directorio de instructores.
        8 columnas incluyendo Disponibilidad con color verde/rojo.
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "Instructores"

        ws['A1'] = 'DIRECTORIO DE INSTRUCTORES'
        ws['A1'].font      = Font(bold=True, size=16, color=HEX_VERDE)
        ws['A1'].alignment = Alignment(horizontal='center')
        ws.merge_cells('A1:H1')

        # Estadísticas de disponibilidad
        total      = instructores.count()
        activos_qs = instructores.filter(activo=True)
        disponibles_hoy = sum(
            1 for inst in activos_qs
            if not get_disponibilidad_instructor(inst)['ocupado']
        )
        ocupados_hoy = activos_qs.count() - disponibles_hoy

        ws['A2'] = f'Total: {total} | Activos: {activos_qs.count()}'
        ws['A2'].font = Font(bold=True, size=11)
        ws.merge_cells('A2:H2')

        ws['A3'] = f'Disponibles hoy: {disponibles_hoy}   |   Ocupados hoy: {ocupados_hoy}'
        ws['A3'].font = Font(italic=True, size=10, color=HEX_VERDE_ITALIC)
        ws.merge_cells('A3:H3')

        headers = ['ID', 'Nombre', 'Correo', 'Teléfono', 'Estado',
                   'Especialidades', 'Solicitudes Asignadas', 'Disponibilidad']
        self._escribir_encabezados(ws, headers, fila=5)

        current_row = 6
        for inst in instructores:
            datos = [
                inst.id, inst.nombre, inst.correo,
                inst.telefono or 'N/A',
                'Activo' if inst.activo else 'Inactivo',
                inst.especialidad.count(),
                inst.solicitud_set.count(),
                None,   # columna 8: disponibilidad (se estiliza aparte)
            ]
            for col_idx, value in enumerate(datos, start=1):
                cell           = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border    = self.border
                cell.alignment = Alignment(
                    horizontal='center', vertical='center', wrap_text=True
                )

            # Columna 8: disponibilidad con color propio
            self._apply_disponibilidad_cell(
                ws.cell(row=current_row, column=8), inst
            )
            current_row += 1

        # Anchos fijos por contenido conocido
        for col, width in zip(
            ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'],
            [8, 30, 28, 15, 12, 18, 22, 16]
        ):
            ws.column_dimensions[col].width = width

        return self._guardar_buffer(wb)

    # =========================================================================
    # REPORTE CONSOLIDADO — EXCEL (5 hojas)
    # =========================================================================

    def generate_consolidated_report(self, solicitudes, empresas, programas, instructores):
        """
        Genera el reporte consolidado Excel con 5 hojas:
            Hoja 1: Resumen Ejecutivo  → estadísticas generales del sistema
            Hoja 2: Solicitudes        → listado completo con distribución por estado
            Hoja 3: Empresas           → directorio completo de empresas
            Hoja 4: Programas          → catálogo con conteo de solicitudes
            Hoja 5: Instructores       → directorio con disponibilidad
        """
        wb = Workbook()

        # ── Hoja 1: Resumen Ejecutivo ─────────────────────────────────────
        ws_resumen = wb.active
        ws_resumen.title = "Resumen Ejecutivo"

        ws_resumen['A1'] = 'REPORTE CONSOLIDADO DEL SISTEMA'
        ws_resumen['A1'].font      = Font(bold=True, size=18, color=HEX_VERDE)
        ws_resumen['A1'].alignment = Alignment(horizontal='center')
        ws_resumen.merge_cells('A1:D1')

        ws_resumen['A2'] = f'Generado: {timezone.now().strftime("%d/%m/%Y %H:%M")}'
        ws_resumen['A2'].font = Font(italic=True)
        ws_resumen.merge_cells('A2:D2')

        ws_resumen['A4'] = 'ESTADÍSTICAS GENERALES'
        ws_resumen['A4'].font = Font(bold=True, size=14, color=HEX_VERDE)

        stats = [
            ['Módulo', 'Total', 'Activos/Finalizadas', 'Porcentaje'],
            ['Solicitudes', solicitudes.count(),
             solicitudes.filter(estado='FINALIZADA').count(),
             f"{solicitudes.filter(estado='FINALIZADA').count() / max(solicitudes.count(), 1) * 100:.1f}%"],
            ['Empresas', empresas.count(),
             empresas.filter(solicitud__isnull=False).distinct().count(),
             f"{empresas.filter(solicitud__isnull=False).distinct().count() / max(empresas.count(), 1) * 100:.1f}%"],
            ['Programas', programas.count(),
             programas.filter(activo=True).count(),
             f"{programas.filter(activo=True).count() / max(programas.count(), 1) * 100:.1f}%"],
            ['Instructores', instructores.count(),
             instructores.filter(activo=True).count(),
             f"{instructores.filter(activo=True).count() / max(instructores.count(), 1) * 100:.1f}%"],
        ]
        for idx, row in enumerate(stats, start=6):
            for col_idx, value in enumerate(row, start=1):
                cell           = ws_resumen.cell(row=idx, column=col_idx, value=value)
                cell.border    = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center')
                # La fila 6 es el encabezado de la tabla
                if idx == 6:
                    cell.fill = self.header_fill
                    cell.font = self.header_font

        for col, width in zip(['A', 'B', 'C', 'D'], [20, 15, 20, 15]):
            ws_resumen.column_dimensions[col].width = width

        # ── Hoja 2: Solicitudes ───────────────────────────────────────────
        ws_sol       = wb.create_sheet("Solicitudes")
        total_sol    = solicitudes.count()

        ws_sol['A1'] = 'SOLICITUDES DE FORMACIÓN'
        ws_sol['A1'].font = Font(bold=True, size=16, color=HEX_VERDE)
        ws_sol.merge_cells('A1:L1')

        ws_sol['A3'] = 'DISTRIBUCIÓN POR ESTADO'
        ws_sol['A3'].font = Font(bold=True, size=12)

        # Tabla de distribución por estado
        estados_data = [['Estado', 'Cantidad', 'Porcentaje']]
        for etiqueta, estado in [
            ('Recibidas',   'RECIBIDA'),
            ('Atendidas',   'ATENDIDA'),
            ('Respondidas', 'RESPONDIDA'),
            ('Finalizadas', 'FINALIZADA'),
        ]:
            cantidad = solicitudes.filter(estado=estado).count()
            estados_data.append([
                etiqueta,
                cantidad,
                f"{cantidad / max(total_sol, 1) * 100:.1f}%",
            ])

        for idx, row in enumerate(estados_data, start=4):
            for col_idx, value in enumerate(row, start=1):
                cell           = ws_sol.cell(row=idx, column=col_idx, value=value)
                cell.border    = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center')
                if idx == 4:
                    cell.fill = self.header_fill
                    cell.font = self.header_font

        ws_sol['A10'] = 'LISTADO COMPLETO'
        ws_sol['A10'].font = Font(bold=True, size=12)

        sol_headers = [
            'NIT Empresa', 'Empresa', 'Programa', 'Área', 'Estado',
            'F. Recepción', 'F. Inicio Form.', 'F. Respuesta', 'F. Fin Form.',
            'Instructor', 'Disponibilidad', 'Observaciones',
        ]
        ws_sol.append([])
        ws_sol.append(sol_headers)
        self.apply_header_style(ws_sol, row=ws_sol.max_row)

        for sol in solicitudes:
            nit         = sol.empresa.nit if hasattr(sol.empresa, 'nit') and sol.empresa.nit else 'Sin NIT'
            current_row = ws_sol.max_row + 1
            ws_sol.append([
                nit,
                sol.empresa.nombre,
                sol.programa.nombre,
                sol.programa.area.nombre,
                sol.get_estado_display(),
                _fmt_fecha_hora(sol.fecha_recepcion),
                _fmt_fecha(sol.fecha_atencion),
                _fmt_fecha_hora(sol.fecha_respuesta),
                _fmt_fecha(sol.fecha_fin_formacion),
                sol.instructor_asignado.nombre if sol.instructor_asignado else 'Sin asignar',
                None,   # columna 11: disponibilidad
                sol.observaciones[:100] if sol.observaciones else '',
            ])

            # Columna 11: disponibilidad con color propio
            disp_cell = ws_sol.cell(row=current_row, column=11)
            if sol.instructor_asignado:
                self._apply_disponibilidad_cell(disp_cell, sol.instructor_asignado)
            else:
                disp_cell.value     = '—'
                disp_cell.border    = self.border
                disp_cell.alignment = Alignment(horizontal='center', vertical='center')

        # Estilizar filas de datos saltando la columna 11 (ya tiene estilo)
        fila_datos_inicio = ws_sol.max_row - total_sol + 1
        self._estilizar_filas_datos(ws_sol, fila_datos_inicio, ws_sol.max_row, 12, col_saltar=11)
        self.adjust_column_width(ws_sol)

        # ── Hoja 3: Empresas ──────────────────────────────────────────────
        ws_emp = wb.create_sheet("Empresas")

        ws_emp['A1'] = 'DIRECTORIO DE EMPRESAS'
        ws_emp['A1'].font = Font(bold=True, size=16, color=HEX_VERDE)
        ws_emp.merge_cells('A1:I1')

        emp_headers = ['NIT', 'Nombre', 'Contacto', 'Teléfono', 'Correo',
                       'Municipio', 'Dirección', 'N° Trabajadores', 'Solicitudes']
        ws_emp.append([])
        ws_emp.append(emp_headers)
        self.apply_header_style(ws_emp, row=3)

        for emp in empresas:
            nit = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
            ws_emp.append([
                nit, emp.nombre, emp.contacto,
                emp.telefono or 'N/A', emp.correo,
                emp.municipio or 'N/A', emp.direccion or 'N/A',
                emp.numero_trabajadores or 0,
                emp.solicitud_set.count(),
            ])

        self._estilizar_filas_datos(ws_emp, 3, ws_emp.max_row, 9)
        self.adjust_column_width(ws_emp)

        # ── Hoja 4: Programas ─────────────────────────────────────────────
        ws_prog = wb.create_sheet("Programas")

        ws_prog['A1'] = 'CATÁLOGO DE PROGRAMAS'
        ws_prog['A1'].font = Font(bold=True, size=16, color=HEX_VERDE)
        ws_prog.merge_cells('A1:G1')

        prog_headers = ['ID', 'Código', 'Nombre', 'Área', 'Duración (h)', 'Estado', 'Solicitudes']
        ws_prog.append([])
        ws_prog.append(prog_headers)
        self.apply_header_style(ws_prog, row=3)

        # Anotamos el conteo de solicitudes por programa directamente en la query
        for prog in programas.annotate(num_sol=Count('solicitud')):
            ws_prog.append([
                prog.id, prog.codigo or 'N/A', prog.nombre,
                prog.area.nombre, prog.duracion_horas or 0,
                'Activo' if prog.activo else 'Inactivo',
                prog.num_sol,
            ])

        self._estilizar_filas_datos(ws_prog, 3, ws_prog.max_row, 7)
        self.adjust_column_width(ws_prog)

        # ── Hoja 5: Instructores ──────────────────────────────────────────
        ws_inst = wb.create_sheet("Instructores")

        ws_inst['A1'] = 'DIRECTORIO DE INSTRUCTORES'
        ws_inst['A1'].font = Font(bold=True, size=16, color=HEX_VERDE)
        ws_inst.merge_cells('A1:H1')

        activos_qs      = instructores.filter(activo=True)
        disponibles_hoy = sum(
            1 for inst in activos_qs
            if not get_disponibilidad_instructor(inst)['ocupado']
        )
        ocupados_hoy = activos_qs.count() - disponibles_hoy

        ws_inst['A2'] = (
            f'Total: {instructores.count()} | Activos: {activos_qs.count()} | '
            f'Disponibles hoy: {disponibles_hoy} | Ocupados hoy: {ocupados_hoy}'
        )
        ws_inst['A2'].font = Font(italic=True, size=10, color=HEX_VERDE_ITALIC)
        ws_inst.merge_cells('A2:H2')

        inst_headers = ['ID', 'Nombre', 'Correo', 'Teléfono', 'Estado',
                        'Especialidades', 'Solicitudes Asignadas', 'Disponibilidad']
        ws_inst.append([])
        ws_inst.append(inst_headers)
        self.apply_header_style(ws_inst, row=4)

        for inst in instructores:
            current_row = ws_inst.max_row + 1
            ws_inst.append([
                inst.id, inst.nombre, inst.correo,
                inst.telefono or 'N/A',
                'Activo' if inst.activo else 'Inactivo',
                inst.especialidad.count(),
                inst.solicitud_set.count(),
                None,   # columna 8: disponibilidad
            ])
            # Columna 8: disponibilidad con color propio
            self._apply_disponibilidad_cell(
                ws_inst.cell(row=current_row, column=8), inst
            )

        # Estilizar filas saltando columna 8 (ya tiene estilo de disponibilidad)
        self._estilizar_filas_datos(ws_inst, 4, ws_inst.max_row, 8, col_saltar=8)
        self.adjust_column_width(ws_inst)

        return self._guardar_buffer(wb)