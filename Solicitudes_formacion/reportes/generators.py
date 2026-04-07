"""
Módulo de generación de reportes en PDF y Excel
Sistema de Gestión de Solicitudes SENA
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Count
from datetime import datetime
import io


# =============================================================================
# HELPER: disponibilidad de instructor
# =============================================================================

def get_disponibilidad_instructor(instructor):
    """
    Devuelve un dict con:
        ocupado   : bool
        etiqueta  : str  → 'Disponible' | 'Ocupado'
    Replica la misma lógica de instructores/views.py:
      - Ocupado si tiene solicitudes con fecha_atencion registrada,
        no finalizadas, cuyo rango inicio-fin abarca el día de hoy.
    """
    hoy = timezone.now().date()

    solicitudes_programadas = instructor.solicitud_set.filter(
        fecha_atencion__isnull=False,
    ).exclude(estado='FINALIZADA')

    ocupado = False
    for sol in solicitudes_programadas.only('fecha_atencion', 'fecha_finalizacion', 'estado'):
        fecha_inicio = sol.fecha_atencion.date()
        fecha_fin    = sol.fecha_finalizacion.date() if sol.fecha_finalizacion else None

        if fecha_inicio <= hoy and (fecha_fin is None or fecha_fin >= hoy):
            ocupado = True
            break

    return {
        'ocupado':  ocupado,
        'etiqueta': 'Ocupado' if ocupado else 'Disponible',
    }


class PDFReportGenerator:
    """Generador de reportes PDF con estilo SENA"""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()

    def setup_custom_styles(self):
        """Configura estilos personalizados"""
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#2e7d32'),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='CustomSubtitle',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#1b5e20'),
            spaceAfter=20,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading3'],
            fontSize=12,
            textColor=colors.HexColor('#2e7d32'),
            spaceAfter=10,
            spaceBefore=15,
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='TableCell',
            parent=self.styles['Normal'],
            fontSize=8,
            leading=11,
            alignment=TA_CENTER,
            wordWrap='CJK',
            fontName='Helvetica'
        ))

        # ── Estilos para la celda de disponibilidad ──────────────────────────
        self.styles.add(ParagraphStyle(
            name='Disponible',
            parent=self.styles['Normal'],
            fontSize=8,
            leading=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#1b5e20'),
            fontName='Helvetica-Bold'
        ))

        self.styles.add(ParagraphStyle(
            name='Ocupado',
            parent=self.styles['Normal'],
            fontSize=8,
            leading=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#b71c1c'),
            fontName='Helvetica-Bold'
        ))

    def _disponibilidad_paragraph(self, instructor):
        """Devuelve un Paragraph coloreado según disponibilidad."""
        info = get_disponibilidad_instructor(instructor)
        style_name = 'Ocupado' if info['ocupado'] else 'Disponible'
        return Paragraph(info['etiqueta'], self.styles[style_name])

    def _disponibilidad_row_colors(self, data_rows):
        """
        Genera comandos TableStyle para colorear la celda de disponibilidad
        (última columna) fila por fila, a partir de la fila 1 (índice 0 = header).
        data_rows: lista de filas de datos (sin la fila de encabezado).
        Devuelve lista de tuplas de estilo.
        """
        styles_cmd = []
        for i, row in enumerate(data_rows, start=1):      # fila 1 en adelante
            last_col = len(row) - 1
            # El texto ya tiene color vía Paragraph; aquí solo resaltamos el fondo levemente
            # para distinguirla visualmente
            pass   # los colores de texto se aplican en el Paragraph; no se necesita nada extra
        return styles_cmd

    def add_header_footer(self, canvas, doc):
        """Agrega encabezado y pie de página"""
        canvas.saveState()

        canvas.setFillColorRGB(0.18, 0.49, 0.20)
        canvas.rect(0, letter[1] - 60, letter[0], 60, fill=1)

        canvas.setFillColorRGB(1, 1, 1)
        canvas.setFont('Helvetica-Bold', 16)
        canvas.drawString(50, letter[1] - 35, "SENA - Servicio Nacional de Aprendizaje")
        canvas.setFont('Helvetica', 10)
        canvas.drawString(50, letter[1] - 50, "Sistema de Gestión de Solicitudes de Formación")

        canvas.setFillColorRGB(0.5, 0.5, 0.5)
        canvas.setFont('Helvetica', 8)
        canvas.drawString(50, 30, f"Generado: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
        canvas.drawRightString(letter[0] - 50, 30, f"Página {doc.page}")

        canvas.restoreState()

    # -------------------------------------------------------------------------
    # SOLICITUDES — PDF
    # -------------------------------------------------------------------------

    def generate_solicitudes_report(self, solicitudes, filtros=None):
        """Genera reporte de solicitudes en PDF con fechas de atención y respuesta"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            topMargin=80,
            bottomMargin=50,
            leftMargin=36,
            rightMargin=36,
            title="Reporte de Solicitudes - SENA",
            author="SENA - Sistema de Gestión",
            subject="Solicitudes de Formación"
        )

        elements = []

        title = Paragraph("REPORTE DE SOLICITUDES DE FORMACIÓN", self.styles['CustomTitle'])
        elements.append(title)
        elements.append(Spacer(1, 0.2 * inch))

        if filtros:
            info_text = f"<b>Filtros aplicados:</b> {filtros}"
            elements.append(Paragraph(info_text, self.styles['Normal']))
            elements.append(Spacer(1, 0.2 * inch))

        total       = solicitudes.count()
        recibidas   = solicitudes.filter(estado='RECIBIDA').count()
        atendidas   = solicitudes.filter(estado='ATENDIDA').count()
        respondidas = solicitudes.filter(estado='RESPONDIDA').count()
        finalizadas = solicitudes.filter(estado='FINALIZADA').count()

        stats_data = [
            ['Total Solicitudes', 'Recibidas', 'Atendidas', 'Respondidas', 'Finalizadas'],
            [str(total), str(recibidas), str(atendidas), str(respondidas), str(finalizadas)]
        ]

        stats_table = Table(stats_data, colWidths=[1.4 * inch] * 5)
        stats_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
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

        # ── Ahora incluye columna Disponibilidad del instructor ───────────────
        headers = [
            'NIT Empresa', 'Empresa', 'Programa',
            'Estado',
            'F. Recepción', 'F. Atención', 'F. Respuesta',
            'Instructor', 'Disponibilidad'
        ]
        data = [headers]

        for sol in solicitudes[:50]:
            nit_empresa = (
                sol.empresa.nit
                if hasattr(sol.empresa, 'nit') and sol.empresa.nit
                else 'Sin NIT'
            )
            if sol.instructor_asignado:
                disp_cell = self._disponibilidad_paragraph(sol.instructor_asignado)
            else:
                disp_cell = Paragraph('—', self.styles['TableCell'])

            data.append([
                Paragraph(nit_empresa,                                                         self.styles['TableCell']),
                Paragraph(sol.empresa.nombre,                                                  self.styles['TableCell']),
                Paragraph(sol.programa.nombre,                                                 self.styles['TableCell']),
                Paragraph(sol.get_estado_display(),                                            self.styles['TableCell']),
                Paragraph(sol.fecha_recepcion.strftime('%d/%m/%Y')  if sol.fecha_recepcion  else '—', self.styles['TableCell']),
                Paragraph(sol.fecha_atencion.strftime('%d/%m/%Y')   if sol.fecha_atencion   else '—', self.styles['TableCell']),
                Paragraph(sol.fecha_respuesta.strftime('%d/%m/%Y')  if sol.fecha_respuesta  else '—', self.styles['TableCell']),
                Paragraph(
                    sol.instructor_asignado.nombre if sol.instructor_asignado else 'Sin asignar',
                    self.styles['TableCell']
                ),
                disp_cell,
            ])

        col_widths = [0.9*inch, 1.6*inch, 1.8*inch, 0.9*inch, 0.85*inch, 0.85*inch, 0.85*inch, 1.3*inch, 0.9*inch]
        table = Table(data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.whitesmoke),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0), 9),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 4),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
            ('BACKGROUND',    (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR',     (0, 1), (-1, -1), colors.black),
            ('FONTNAME',      (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE',      (0, 1), (-1, -1), 8),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))

        elements.append(table)

        if solicitudes.count() > 50:
            elements.append(Spacer(1, 0.2 * inch))
            elements.append(Paragraph(
                f"<i>Nota: Mostrando las primeras 50 solicitudes de {solicitudes.count()} totales</i>",
                self.styles['Normal']
            ))

        doc.build(elements, onFirstPage=self.add_header_footer, onLaterPages=self.add_header_footer)
        buffer.seek(0)
        return buffer

    # -------------------------------------------------------------------------
    # EMPRESAS — PDF
    # -------------------------------------------------------------------------

    def generate_empresas_report(self, empresas):
        """Genera reporte de empresas en PDF CON NIT"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=80,
            bottomMargin=50,
            leftMargin=40,
            rightMargin=40,
            title="Directorio de Empresas - SENA",
            author="SENA - Sistema de Gestión",
            subject="Empresas Registradas"
        )
        elements = []

        title = Paragraph("DIRECTORIO DE EMPRESAS", self.styles['CustomTitle'])
        elements.append(title)
        elements.append(Spacer(1, 0.3 * inch))

        total = empresas.count()
        elements.append(Paragraph(f"<b>Total de empresas:</b> {total}", self.styles['Normal']))
        elements.append(Spacer(1, 0.3 * inch))

        data = [['NIT', 'Empresa', 'Contacto', 'Teléfono', 'Correo', 'Municipio', 'N° Trab.']]

        for emp in empresas[:50]:
            nit_empresa = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
            data.append([
                Paragraph(nit_empresa,                                                  self.styles['TableCell']),
                Paragraph(emp.nombre,                                                   self.styles['TableCell']),
                Paragraph(emp.contacto,                                                 self.styles['TableCell']),
                Paragraph(emp.telefono or 'N/A',                                       self.styles['TableCell']),
                Paragraph(emp.correo,                                                   self.styles['TableCell']),
                Paragraph(emp.municipio if emp.municipio else 'N/A',                   self.styles['TableCell']),
                Paragraph(str(emp.numero_trabajadores) if emp.numero_trabajadores else '0', self.styles['TableCell']),
            ])

        table = Table(data, colWidths=[0.9*inch, 1.6*inch, 1.1*inch, 0.85*inch, 1.3*inch, 0.9*inch, 0.75*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1,  0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR',  (0, 0), (-1,  0), colors.whitesmoke),
            ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',   (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1,  0), 9),
            ('FONTSIZE',   (0, 1), (-1, -1), 8),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 3),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))

        elements.append(table)
        doc.build(elements, onFirstPage=self.add_header_footer, onLaterPages=self.add_header_footer)
        buffer.seek(0)
        return buffer

    # -------------------------------------------------------------------------
    # PROGRAMAS — PDF
    # -------------------------------------------------------------------------

    def generate_programas_report(self, programas):
        """Genera reporte de programas en PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=80,
            bottomMargin=50,
            title="Programas de formacion - SENA",
            author="SENA - Sistema de Gestión",
            subject="Programas de Formación"
        )
        elements = []

        title = Paragraph("CATÁLOGO DE PROGRAMAS DE FORMACIÓN", self.styles['CustomTitle'])
        elements.append(title)
        elements.append(Spacer(1, 0.3 * inch))

        total = programas.count()
        elements.append(Paragraph(f"<b>Total de programas activos:</b> {total}", self.styles['Normal']))
        elements.append(Spacer(1, 0.3 * inch))

        data = [['Código', 'Nombre del Programa', 'Área', 'Duración', 'Estado']]
        for prog in programas[:50]:
            data.append([
                Paragraph(prog.codigo or 'N/A',                                 self.styles['TableCell']),
                Paragraph(prog.nombre,                                           self.styles['TableCell']),
                Paragraph(prog.area.nombre,                                      self.styles['TableCell']),
                Paragraph(f"{prog.duracion_horas}h" if prog.duracion_horas else 'N/A', self.styles['TableCell']),
                Paragraph('Activo' if prog.activo else 'Inactivo',              self.styles['TableCell']),
            ])

        table = Table(data, colWidths=[0.9*inch, 3*inch, 1.5*inch, 0.8*inch, 0.8*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.whitesmoke),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0), 10),
            ('FONTSIZE',      (0, 1), (-1, -1), 9),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))

        elements.append(table)

        if programas.count() > 50:
            elements.append(Spacer(1, 0.2 * inch))
            elements.append(Paragraph(
                f"<i>Nota: Mostrando los primeros 50 programas de {programas.count()} totales</i>",
                self.styles['Normal']
            ))

        doc.build(elements, onFirstPage=self.add_header_footer, onLaterPages=self.add_header_footer)
        buffer.seek(0)
        return buffer

    # -------------------------------------------------------------------------
    # CONSOLIDADO — PDF
    # -------------------------------------------------------------------------

    def generate_consolidated_report(self, solicitudes, empresas, programas, instructores):
        """Genera reporte consolidado de todo el sistema"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=80,
            bottomMargin=50,
            leftMargin=50,
            rightMargin=50,
            title="Reporte Consolidado - SENA",
            author="SENA - Sistema de Gestión",
            subject="Reporte Consolidado"
        )
        elements = []

        title = Paragraph("REPORTE CONSOLIDADO DEL SISTEMA", self.styles['CustomTitle'])
        elements.append(title)
        elements.append(Spacer(1, 0.1 * inch))

        subtitle = Paragraph(
            "Sistema de Gestión de Solicitudes de Formación SENA",
            self.styles['CustomSubtitle']
        )
        elements.append(subtitle)
        elements.append(Spacer(1, 0.3 * inch))

        elements.append(Paragraph(
            f"<b>Fecha de generación:</b> {timezone.now().strftime('%d/%m/%Y %H:%M')}",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.5 * inch))

        elements.append(Paragraph("RESUMEN EJECUTIVO", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))

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
        summary_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.whitesmoke),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0), 9),
            ('FONTSIZE',      (0, 1), (-1, -1), 8),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 4),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ]))

        elements.append(summary_table)
        elements.append(PageBreak())

        # ── Sección 1: Solicitudes ───────────────────────────────────────────
        elements.append(Paragraph("1. SOLICITUDES DE FORMACIÓN", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))

        sol_stats_data = [
            ['Estado', 'Cantidad', 'Porcentaje'],
            ['Recibidas',   str(solicitudes.filter(estado='RECIBIDA').count()),
             f"{solicitudes.filter(estado='RECIBIDA').count()  / max(solicitudes.count(), 1) * 100:.1f}%"],
            ['Atendidas',   str(solicitudes.filter(estado='ATENDIDA').count()),
             f"{solicitudes.filter(estado='ATENDIDA').count()  / max(solicitudes.count(), 1) * 100:.1f}%"],
            ['Respondidas', str(solicitudes.filter(estado='RESPONDIDA').count()),
             f"{solicitudes.filter(estado='RESPONDIDA').count()/ max(solicitudes.count(), 1) * 100:.1f}%"],
            ['Finalizadas', str(solicitudes.filter(estado='FINALIZADA').count()),
             f"{solicitudes.filter(estado='FINALIZADA').count()/ max(solicitudes.count(), 1) * 100:.1f}%"],
        ]

        sol_stats_table = Table(sol_stats_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
        sol_stats_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.whitesmoke),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0), 10),
            ('FONTSIZE',      (0, 1), (-1, -1), 10),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
        ]))

        elements.append(sol_stats_table)
        elements.append(Spacer(1, 0.3 * inch))

        elements.append(Paragraph("Últimas 10 Solicitudes", self.styles['SectionHeader']))
        elements.append(Spacer(1, 0.1 * inch))

        sol_data = [['NIT Empresa', 'Empresa', 'Programa', 'Estado', 'F. Recepción', 'F. Atención', 'F. Respuesta']]
        for sol in solicitudes[:10]:
            nit_empresa = (
                sol.empresa.nit
                if hasattr(sol.empresa, 'nit') and sol.empresa.nit
                else 'Sin NIT'
            )
            sol_data.append([
                Paragraph(nit_empresa,                                                         self.styles['TableCell']),
                Paragraph(sol.empresa.nombre,                                                  self.styles['TableCell']),
                Paragraph(sol.programa.nombre,                                                 self.styles['TableCell']),
                Paragraph(sol.get_estado_display(),                                            self.styles['TableCell']),
                Paragraph(sol.fecha_recepcion.strftime('%d/%m/%Y') if sol.fecha_recepcion else '—', self.styles['TableCell']),
                Paragraph(sol.fecha_atencion.strftime('%d/%m/%Y')  if sol.fecha_atencion  else '—', self.styles['TableCell']),
                Paragraph(sol.fecha_respuesta.strftime('%d/%m/%Y') if sol.fecha_respuesta else '—', self.styles['TableCell']),
            ])

        sol_table = Table(sol_data, colWidths=[0.9*inch, 1.5*inch, 1.5*inch, 0.85*inch, 0.85*inch, 0.85*inch, 0.85*inch])
        sol_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.whitesmoke),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0), 9),
            ('FONTSIZE',      (0, 1), (-1, -1), 8),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 4),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ]))

        elements.append(sol_table)
        elements.append(PageBreak())

        # ── Sección 2: Empresas ──────────────────────────────────────────────
        elements.append(Paragraph("2. DIRECTORIO DE EMPRESAS", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph(
            f"Total de empresas registradas: <b>{empresas.count()}</b>",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.2 * inch))

        emp_data = [['NIT', 'Empresa', 'Contacto', 'Teléfono', 'Municipio', 'Solicitudes']]
        for emp in empresas[:15]:
            nit_empresa = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
            emp_data.append([
                Paragraph(nit_empresa,                           self.styles['TableCell']),
                Paragraph(emp.nombre or 'Sin nombre',           self.styles['TableCell']),
                Paragraph(emp.contacto or 'Sin contacto',       self.styles['TableCell']),
                Paragraph(emp.telefono or 'N/A',                self.styles['TableCell']),
                Paragraph(emp.municipio or 'No especificado',   self.styles['TableCell']),
                Paragraph(str(emp.solicitud_set.count()),        self.styles['TableCell']),
            ])

        emp_table = Table(emp_data, colWidths=[1.1*inch, 1.8*inch, 1.2*inch, 0.9*inch, 1*inch, 0.9*inch])
        emp_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.whitesmoke),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0), 9),
            ('FONTSIZE',      (0, 1), (-1, -1), 8),
            ('TOPPADDING',    (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING',   (0, 0), (-1, -1), 4),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))

        elements.append(emp_table)
        elements.append(PageBreak())

        # ── Sección 3: Programas ─────────────────────────────────────────────
        elements.append(Paragraph("3. PROGRAMAS DE FORMACIÓN", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))

        from django.db.models import Count as DjCount
        areas_stats = programas.values('area__nombre').annotate(total=DjCount('id')).order_by('-total')[:5]

        area_data = [['Área de Formación', 'Cantidad de Programas']]
        for area in areas_stats:
            area_data.append([
                Paragraph(area['area__nombre'] or 'Sin área', self.styles['TableCell']),
                Paragraph(str(area['total']),                 self.styles['TableCell']),
            ])

        area_table = Table(area_data, colWidths=[4.5*inch, 1.5*inch])
        area_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.whitesmoke),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0), 10),
            ('FONTSIZE',      (0, 1), (-1, -1), 10),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
        ]))

        elements.append(area_table)
        elements.append(Spacer(1, 0.3 * inch))

        elements.append(Paragraph("Programas Más Solicitados", self.styles['SectionHeader']))
        elements.append(Spacer(1, 0.1 * inch))

        prog_data = [['Código', 'Programa', 'Área', 'Duración', 'Solicitudes']]
        for prog in programas.annotate(num_sol=DjCount('solicitud')).order_by('-num_sol')[:15]:
            prog_data.append([
                Paragraph(prog.codigo or 'N/A',                                          self.styles['TableCell']),
                Paragraph(prog.nombre,                                                   self.styles['TableCell']),
                Paragraph(prog.area.nombre,                                              self.styles['TableCell']),
                Paragraph(f"{prog.duracion_horas}h" if prog.duracion_horas else 'N/A',  self.styles['TableCell']),
                Paragraph(str(prog.num_sol),                                             self.styles['TableCell']),
            ])

        prog_table = Table(prog_data, colWidths=[0.9*inch, 2.2*inch, 1.6*inch, 0.8*inch, 1*inch])
        prog_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.whitesmoke),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0), 10),
            ('FONTSIZE',      (0, 1), (-1, -1), 9),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
        ]))

        elements.append(prog_table)
        elements.append(PageBreak())

        # ── Sección 4: Instructores — AHORA CON DISPONIBILIDAD ───────────────
        elements.append(Paragraph("4. INSTRUCTORES", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph(
            f"Total de instructores: <b>{instructores.count()}</b> "
            f"(Activos: <b>{instructores.filter(activo=True).count()}</b>)",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.2 * inch))

        # Contadores de disponibilidad para el resumen
        activos_qs = instructores.filter(activo=True)
        disponibles_count = sum(
            1 for inst in activos_qs
            if not get_disponibilidad_instructor(inst)['ocupado']
        )
        ocupados_count = activos_qs.count() - disponibles_count

        elements.append(Paragraph(
            f"Disponibles hoy: <b>{disponibles_count}</b> &nbsp;|&nbsp; "
            f"Ocupados hoy: <b>{ocupados_count}</b>",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.2 * inch))

        inst_data = [['Instructor', 'Correo', 'Teléfono', 'Especialidades', 'Solicitudes', 'Disponibilidad']]
        for inst in instructores.filter(activo=True)[:20]:
            inst_data.append([
                Paragraph(inst.nombre,                                   self.styles['TableCell']),
                Paragraph(inst.correo,                                   self.styles['TableCell']),
                Paragraph(inst.telefono if inst.telefono else 'N/A',     self.styles['TableCell']),
                Paragraph(str(inst.especialidad.count()),                self.styles['TableCell']),
                Paragraph(str(inst.solicitud_set.count()),               self.styles['TableCell']),
                self._disponibilidad_paragraph(inst),
            ])

        inst_table = Table(inst_data, colWidths=[1.4*inch, 1.7*inch, 0.8*inch, 0.9*inch, 0.8*inch, 0.9*inch])
        inst_table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR',     (0, 0), (-1,  0), colors.whitesmoke),
            ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0), 10),
            ('FONTSIZE',      (0, 1), (-1, -1), 9),
            ('GRID',          (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING',   (0, 0), (-1, -1), 5),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 5),
        ]))

        elements.append(inst_table)
        elements.append(Spacer(1, 0.5 * inch))
        elements.append(Paragraph("<i>--- Fin del Reporte Consolidado ---</i>", self.styles['Normal']))

        doc.build(elements, onFirstPage=self.add_header_footer, onLaterPages=self.add_header_footer)
        buffer.seek(0)
        return buffer


# =============================================================================
# EXCEL
# =============================================================================

class ExcelReportGenerator:
    """Generador de reportes Excel con formato SENA"""

    # Rellenos para disponibilidad
    FILL_DISPONIBLE = PatternFill(start_color="C8E6C9", end_color="C8E6C9", fill_type="solid")  # verde claro
    FILL_OCUPADO    = PatternFill(start_color="FFCDD2", end_color="FFCDD2", fill_type="solid")  # rojo claro
    FONT_DISPONIBLE = Font(bold=True, color="1b5e20", size=10)  # verde oscuro
    FONT_OCUPADO    = Font(bold=True, color="b71c1c", size=10)  # rojo oscuro

    def __init__(self):
        self.header_fill = PatternFill(start_color="2e7d32", end_color="2e7d32", fill_type="solid")
        self.header_font = Font(bold=True, color="FFFFFF", size=12)
        self.border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )

    def _apply_disponibilidad_cell(self, cell, instructor):
        """Escribe y da formato a una celda de disponibilidad."""
        info = get_disponibilidad_instructor(instructor)
        cell.value     = info['etiqueta']
        cell.fill      = self.FILL_OCUPADO    if info['ocupado'] else self.FILL_DISPONIBLE
        cell.font      = self.FONT_OCUPADO    if info['ocupado'] else self.FONT_DISPONIBLE
        cell.alignment = Alignment(horizontal='center', vertical='center')
        cell.border    = self.border

    def apply_header_style(self, ws, row=1):
        for cell in ws[row]:
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.border

    def adjust_column_width(self, ws):
        for idx, column in enumerate(ws.columns, start=1):
            max_length = 0
            column_letter = get_column_letter(idx)
            for cell in column:
                try:
                    if cell.value is not None:
                        cell_length = len(str(cell.value))
                        if cell_length > max_length:
                            max_length = cell_length
                except Exception:
                    pass
            ws.column_dimensions[column_letter].width = max(12, min(max_length + 4, 60))

    # -------------------------------------------------------------------------
    # SOLICITUDES — EXCEL
    # -------------------------------------------------------------------------

    def generate_solicitudes_report(self, solicitudes, filtros=None):
        """Genera reporte de solicitudes en Excel con F. Atención, F. Respuesta y Disponibilidad"""
        wb = Workbook()
        ws = wb.active
        ws.title = "Solicitudes"

        ws['A1'] = 'REPORTE DE SOLICITUDES DE FORMACIÓN'
        ws['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws['A1'].alignment = Alignment(horizontal='center')
        ws.merge_cells('A1:K1')

        ws['A2'] = f'Generado: {timezone.now().strftime("%d/%m/%Y %H:%M")}'
        ws['A2'].font = Font(italic=True, size=10)
        ws.merge_cells('A2:K2')

        if filtros:
            ws['A3'] = f'Filtros aplicados: {filtros}'
            ws['A3'].font = Font(italic=True, size=10, color="558b2f")
            ws.merge_cells('A3:K3')

        ws['A4'] = 'RESUMEN ESTADÍSTICO'
        ws['A4'].font = Font(bold=True, size=12)

        stats_data = [
            ['Total Solicitudes', solicitudes.count(),
             'Recibidas',   solicitudes.filter(estado='RECIBIDA').count()],
            ['Atendidas',   solicitudes.filter(estado='ATENDIDA').count(),
             'Respondidas', solicitudes.filter(estado='RESPONDIDA').count()],
            ['Finalizadas', solicitudes.filter(estado='FINALIZADA').count(), '', ''],
        ]

        for row_idx, row_data in enumerate(stats_data, start=5):
            for col_idx, value in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center')
                if col_idx % 2 == 1:
                    cell.fill = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
                    cell.font = Font(bold=True)

        # ── Encabezados — ahora 11 columnas ──────────────────────────────────
        headers = [
            'NIT Empresa', 'Empresa', 'Programa', 'Área', 'Estado',
            'F. Recepción', 'F. Atención', 'F. Respuesta',
            'Instructor', 'Disponibilidad', 'Observaciones'
        ]

        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=8, column=col_idx, value=header)
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.border

        # ── Datos ─────────────────────────────────────────────────────────────
        current_row = 9
        for sol in solicitudes:
            nit_empresa = (
                sol.empresa.nit
                if hasattr(sol.empresa, 'nit') and sol.empresa.nit
                else 'Sin NIT'
            )
            datos = [
                nit_empresa,
                sol.empresa.nombre,
                sol.programa.nombre,
                sol.programa.area.nombre,
                sol.get_estado_display(),
                sol.fecha_recepcion.strftime('%d/%m/%Y %H:%M') if sol.fecha_recepcion else '—',
                sol.fecha_atencion.strftime('%d/%m/%Y %H:%M')  if sol.fecha_atencion  else '—',
                sol.fecha_respuesta.strftime('%d/%m/%Y %H:%M') if sol.fecha_respuesta else '—',
                sol.instructor_asignado.nombre if sol.instructor_asignado else 'Sin asignar',
                # columna 10: disponibilidad — se aplica después
                None,
                sol.observaciones[:100] if sol.observaciones else 'N/A',
            ]

            for col_idx, value in enumerate(datos, start=1):
                cell = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

            # Celda de disponibilidad (columna 10)
            disp_cell = ws.cell(row=current_row, column=10)
            if sol.instructor_asignado:
                self._apply_disponibilidad_cell(disp_cell, sol.instructor_asignado)
            else:
                disp_cell.value = '—'

            current_row += 1

        self.adjust_column_width(ws)

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer

    # -------------------------------------------------------------------------
    # EMPRESAS — EXCEL
    # -------------------------------------------------------------------------

    def generate_empresas_report(self, empresas):
        wb = Workbook()
        ws = wb.active
        ws.title = "Empresas"

        ws['A1'] = 'DIRECTORIO DE EMPRESAS'
        ws['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws.merge_cells('A1:H1')

        ws['A2'] = f'Total de empresas: {empresas.count()}'
        ws['A2'].font = Font(bold=True, size=11)

        headers = ['NIT', 'Nombre', 'Contacto', 'Teléfono', 'Correo', 'Municipio', 'Dirección', 'N° Trabajadores']
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=4, column=col_idx, value=header)
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.border

        current_row = 5
        for emp in empresas:
            nit_empresa = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
            datos = [
                nit_empresa, emp.nombre, emp.contacto,
                emp.telefono or 'N/A', emp.correo,
                emp.municipio or 'N/A', emp.direccion or 'N/A',
                emp.numero_trabajadores or 0,
            ]
            for col_idx, value in enumerate(datos, start=1):
                cell = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            current_row += 1

        self.adjust_column_width(ws)
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer

    # -------------------------------------------------------------------------
    # PROGRAMAS — EXCEL
    # -------------------------------------------------------------------------

    def generate_programas_report(self, programas):
        wb = Workbook()
        ws = wb.active
        ws.title = "Programas"

        ws['A1'] = 'CATÁLOGO DE PROGRAMAS DE FORMACIÓN'
        ws['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws.merge_cells('A1:F1')

        headers = ['ID', 'Código', 'Nombre', 'Área', 'Duración (horas)', 'Estado']
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=3, column=col_idx, value=header)
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.border

        current_row = 4
        for prog in programas:
            datos = [
                prog.id, prog.codigo or 'N/A', prog.nombre,
                prog.area.nombre, prog.duracion_horas or 0,
                'Activo' if prog.activo else 'Inactivo',
            ]
            for col_idx, value in enumerate(datos, start=1):
                cell = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            current_row += 1

        ws.column_dimensions['A'].width = 8
        ws.column_dimensions['B'].width = 15
        ws.column_dimensions['C'].width = 45
        ws.column_dimensions['D'].width = 25
        ws.column_dimensions['E'].width = 18
        ws.column_dimensions['F'].width = 12

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer

    # -------------------------------------------------------------------------
    # INSTRUCTORES — EXCEL  (con columna Disponibilidad)
    # -------------------------------------------------------------------------

    def generate_instructores_report(self, instructores):
        wb = Workbook()
        ws = wb.active
        ws.title = "Instructores"

        ws['A1'] = 'DIRECTORIO DE INSTRUCTORES'
        ws['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws.merge_cells('A1:H1')
        ws['A1'].alignment = Alignment(horizontal='center')

        total   = instructores.count()
        activos = instructores.filter(activo=True).count()
        ws['A2'] = f'Total: {total} | Activos: {activos}'
        ws['A2'].font = Font(bold=True, size=11)
        ws.merge_cells('A2:H2')

        # ── Resumen de disponibilidad ─────────────────────────────────────────
        activos_qs      = instructores.filter(activo=True)
        disponibles_hoy = sum(1 for i in activos_qs if not get_disponibilidad_instructor(i)['ocupado'])
        ocupados_hoy    = activos_qs.count() - disponibles_hoy

        ws['A3'] = f'Disponibles hoy: {disponibles_hoy}   |   Ocupados hoy: {ocupados_hoy}'
        ws['A3'].font = Font(italic=True, size=10, color="558b2f")
        ws.merge_cells('A3:H3')

        # ── Encabezados — 8 columnas con Disponibilidad ──────────────────────
        headers = ['ID', 'Nombre', 'Correo', 'Teléfono', 'Estado', 'Especialidades', 'Solicitudes Asignadas', 'Disponibilidad']
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=5, column=col_idx, value=header)
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.border

        current_row = 6
        for inst in instructores:
            datos = [
                inst.id, inst.nombre, inst.correo,
                inst.telefono or 'N/A',
                'Activo' if inst.activo else 'Inactivo',
                inst.especialidad.count(),
                inst.solicitud_set.count(),
                # columna 8: disponibilidad — se aplica después
                None,
            ]

            for col_idx, value in enumerate(datos, start=1):
                cell = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

            # Celda de disponibilidad (columna 8)
            disp_cell = ws.cell(row=current_row, column=8)
            self._apply_disponibilidad_cell(disp_cell, inst)

            current_row += 1

        ws.column_dimensions['A'].width = 8
        ws.column_dimensions['B'].width = 30
        ws.column_dimensions['C'].width = 28
        ws.column_dimensions['D'].width = 15
        ws.column_dimensions['E'].width = 12
        ws.column_dimensions['F'].width = 18
        ws.column_dimensions['G'].width = 22
        ws.column_dimensions['H'].width = 16   # Disponibilidad

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer

    # -------------------------------------------------------------------------
    # CONSOLIDADO — EXCEL  (hoja Instructores con disponibilidad)
    # -------------------------------------------------------------------------

    def generate_consolidated_report(self, solicitudes, empresas, programas, instructores):
        """Genera reporte consolidado en Excel con múltiples hojas"""
        wb = Workbook()

        # ── Hoja 1: Resumen ejecutivo ────────────────────────────────────────
        ws_resumen = wb.active
        ws_resumen.title = "Resumen Ejecutivo"

        ws_resumen['A1'] = 'REPORTE CONSOLIDADO DEL SISTEMA'
        ws_resumen['A1'].font = Font(bold=True, size=18, color="2e7d32")
        ws_resumen.merge_cells('A1:D1')
        ws_resumen['A1'].alignment = Alignment(horizontal='center')

        ws_resumen['A2'] = f'Generado: {timezone.now().strftime("%d/%m/%Y %H:%M")}'
        ws_resumen['A2'].font = Font(italic=True)
        ws_resumen.merge_cells('A2:D2')

        ws_resumen['A4'] = 'ESTADÍSTICAS GENERALES'
        ws_resumen['A4'].font = Font(bold=True, size=14, color="2e7d32")

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
                cell = ws_resumen.cell(row=idx, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center')
                if idx == 6:
                    cell.fill = self.header_fill
                    cell.font = self.header_font

        ws_resumen.column_dimensions['A'].width = 20
        ws_resumen.column_dimensions['B'].width = 15
        ws_resumen.column_dimensions['C'].width = 20
        ws_resumen.column_dimensions['D'].width = 15

        # ── Hoja 2: Solicitudes ──────────────────────────────────────────────
        ws_sol = wb.create_sheet("Solicitudes")

        ws_sol['A1'] = 'SOLICITUDES DE FORMACIÓN'
        ws_sol['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws_sol.merge_cells('A1:K1')

        ws_sol['A3'] = 'DISTRIBUCIÓN POR ESTADO'
        ws_sol['A3'].font = Font(bold=True, size=12)

        estados = [
            ['Estado', 'Cantidad', 'Porcentaje'],
            ['Recibidas',   solicitudes.filter(estado='RECIBIDA').count(),
             f"{solicitudes.filter(estado='RECIBIDA').count()   / max(solicitudes.count(), 1) * 100:.1f}%"],
            ['Atendidas',   solicitudes.filter(estado='ATENDIDA').count(),
             f"{solicitudes.filter(estado='ATENDIDA').count()   / max(solicitudes.count(), 1) * 100:.1f}%"],
            ['Respondidas', solicitudes.filter(estado='RESPONDIDA').count(),
             f"{solicitudes.filter(estado='RESPONDIDA').count() / max(solicitudes.count(), 1) * 100:.1f}%"],
            ['Finalizadas', solicitudes.filter(estado='FINALIZADA').count(),
             f"{solicitudes.filter(estado='FINALIZADA').count() / max(solicitudes.count(), 1) * 100:.1f}%"],
        ]

        for idx, row in enumerate(estados, start=4):
            for col_idx, value in enumerate(row, start=1):
                cell = ws_sol.cell(row=idx, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center')
                if idx == 4:
                    cell.fill = self.header_fill
                    cell.font = self.header_font

        ws_sol['A10'] = 'LISTADO COMPLETO'
        ws_sol['A10'].font = Font(bold=True, size=12)

        # ── 11 columnas con Disponibilidad ────────────────────────────────────
        headers = [
            'NIT Empresa', 'Empresa', 'Programa', 'Área', 'Estado',
            'F. Recepción', 'F. Atención', 'F. Respuesta',
            'Instructor', 'Disponibilidad', 'Observaciones'
        ]
        ws_sol.append([])
        ws_sol.append(headers)

        header_row = ws_sol.max_row
        for cell in ws_sol[header_row]:
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.border = self.border
            cell.alignment = Alignment(horizontal='center', vertical='center')

        for sol in solicitudes:
            nit_empresa = (
                sol.empresa.nit
                if hasattr(sol.empresa, 'nit') and sol.empresa.nit
                else 'Sin NIT'
            )
            current_row = ws_sol.max_row + 1
            row_data = [
                nit_empresa,
                sol.empresa.nombre,
                sol.programa.nombre,
                sol.programa.area.nombre,
                sol.get_estado_display(),
                sol.fecha_recepcion.strftime('%d/%m/%Y %H:%M') if sol.fecha_recepcion else '—',
                sol.fecha_atencion.strftime('%d/%m/%Y %H:%M')  if sol.fecha_atencion  else '—',
                sol.fecha_respuesta.strftime('%d/%m/%Y %H:%M') if sol.fecha_respuesta else '—',
                sol.instructor_asignado.nombre if sol.instructor_asignado else 'Sin asignar',
                None,   # disponibilidad — se aplica después
                sol.observaciones[:100] if sol.observaciones else '',
            ]
            ws_sol.append(row_data)

            # Celda de disponibilidad (columna 10)
            disp_cell = ws_sol.cell(row=current_row, column=10)
            if sol.instructor_asignado:
                self._apply_disponibilidad_cell(disp_cell, sol.instructor_asignado)
            else:
                disp_cell.value = '—'
                disp_cell.border = self.border
                disp_cell.alignment = Alignment(horizontal='center', vertical='center')

        data_start = header_row + 1
        for row in ws_sol.iter_rows(min_row=data_start, max_row=ws_sol.max_row, max_col=11):
            for cell in row:
                if cell.column != 10:   # la columna 10 ya tiene formato propio
                    cell.border = self.border
                    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        self.adjust_column_width(ws_sol)

        # ── Hoja 3: Empresas ─────────────────────────────────────────────────
        ws_emp = wb.create_sheet("Empresas")

        ws_emp['A1'] = 'DIRECTORIO DE EMPRESAS'
        ws_emp['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws_emp.merge_cells('A1:I1')

        emp_headers = ['NIT', 'Nombre', 'Contacto', 'Teléfono', 'Correo', 'Municipio', 'Dirección', 'N° Trabajadores', 'Solicitudes']
        ws_emp.append([])
        ws_emp.append(emp_headers)

        for cell in ws_emp[3]:
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.border = self.border
            cell.alignment = Alignment(horizontal='center', vertical='center')

        for emp in empresas:
            nit_empresa = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
            ws_emp.append([
                nit_empresa, emp.nombre, emp.contacto,
                emp.telefono or 'N/A', emp.correo,
                emp.municipio or 'N/A', emp.direccion or 'N/A',
                emp.numero_trabajadores or 0,
                emp.solicitud_set.count(),
            ])

        for row in ws_emp.iter_rows(min_row=3, max_row=ws_emp.max_row, max_col=9):
            for cell in row:
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        self.adjust_column_width(ws_emp)

        # ── Hoja 4: Programas ────────────────────────────────────────────────
        ws_prog = wb.create_sheet("Programas")

        ws_prog['A1'] = 'CATÁLOGO DE PROGRAMAS'
        ws_prog['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws_prog.merge_cells('A1:G1')

        prog_headers = ['ID', 'Código', 'Nombre', 'Área', 'Duración (h)', 'Estado', 'Solicitudes']
        ws_prog.append([])
        ws_prog.append(prog_headers)

        for cell in ws_prog[3]:
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.border = self.border
            cell.alignment = Alignment(horizontal='center', vertical='center')

        from django.db.models import Count as DjCount2
        for prog in programas.annotate(num_sol=DjCount2('solicitud')):
            ws_prog.append([
                prog.id, prog.codigo or 'N/A', prog.nombre,
                prog.area.nombre, prog.duracion_horas or 0,
                'Activo' if prog.activo else 'Inactivo',
                prog.num_sol,
            ])

        for row in ws_prog.iter_rows(min_row=3, max_row=ws_prog.max_row, max_col=7):
            for cell in row:
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        self.adjust_column_width(ws_prog)

        # ── Hoja 5: Instructores — CON DISPONIBILIDAD ────────────────────────
        ws_inst = wb.create_sheet("Instructores")

        ws_inst['A1'] = 'DIRECTORIO DE INSTRUCTORES'
        ws_inst['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws_inst.merge_cells('A1:H1')

        # Resumen de disponibilidad en la hoja
        activos_qs      = instructores.filter(activo=True)
        disponibles_hoy = sum(1 for i in activos_qs if not get_disponibilidad_instructor(i)['ocupado'])
        ocupados_hoy    = activos_qs.count() - disponibles_hoy

        ws_inst['A2'] = (
            f'Total: {instructores.count()} | Activos: {activos_qs.count()} | '
            f'Disponibles hoy: {disponibles_hoy} | Ocupados hoy: {ocupados_hoy}'
        )
        ws_inst['A2'].font = Font(italic=True, size=10, color="558b2f")
        ws_inst.merge_cells('A2:H2')

        inst_headers = ['ID', 'Nombre', 'Correo', 'Teléfono', 'Estado', 'Especialidades', 'Solicitudes Asignadas', 'Disponibilidad']
        ws_inst.append([])
        ws_inst.append(inst_headers)

        for cell in ws_inst[4]:
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.border = self.border
            cell.alignment = Alignment(horizontal='center', vertical='center')

        for inst in instructores:
            current_row = ws_inst.max_row + 1
            ws_inst.append([
                inst.id, inst.nombre, inst.correo,
                inst.telefono or 'N/A',
                'Activo' if inst.activo else 'Inactivo',
                inst.especialidad.count(),
                inst.solicitud_set.count(),
                None,   # disponibilidad — se aplica después
            ])

            # Celda de disponibilidad (columna 8)
            disp_cell = ws_inst.cell(row=current_row, column=8)
            self._apply_disponibilidad_cell(disp_cell, inst)

        for row in ws_inst.iter_rows(min_row=4, max_row=ws_inst.max_row, max_col=8):
            for cell in row:
                if cell.column != 8:   # columna 8 ya tiene formato propio
                    cell.border = self.border
                    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        self.adjust_column_width(ws_inst)

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer