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


class PDFReportGenerator:
    """Generador de reportes PDF con estilo SENA"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()
    
    def setup_custom_styles(self):
        """Configura estilos personalizados"""
        # Título principal
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#2e7d32'),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
    
        # Subtítulo
        self.styles.add(ParagraphStyle(
            name='CustomSubtitle',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#1b5e20'),
            spaceAfter=20,
            fontName='Helvetica-Bold'
        ))
    
        # Encabezado de sección
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading3'],
            fontSize=12,
            textColor=colors.HexColor('#2e7d32'),
            spaceAfter=10,
            spaceBefore=15,
            fontName='Helvetica-Bold'
        ))
    
        # Estilo para celdas de tabla (NUEVO)
        self.styles.add(ParagraphStyle(
            name='TableCell',
            parent=self.styles['Normal'],
            fontSize=8,
            leading=11,
            alignment=TA_CENTER,
            wordWrap='CJK',
            fontName='Helvetica'
        ))
    
    def add_header_footer(self, canvas, doc):
        """Agrega encabezado y pie de página"""
        canvas.saveState()
        
        # Header
        canvas.setFillColorRGB(0.18, 0.49, 0.20)  # Verde SENA
        canvas.rect(0, letter[1] - 60, letter[0], 60, fill=1)
        
        canvas.setFillColorRGB(1, 1, 1)
        canvas.setFont('Helvetica-Bold', 16)
        canvas.drawString(50, letter[1] - 35, "SENA - Servicio Nacional de Aprendizaje")
        canvas.setFont('Helvetica', 10)
        canvas.drawString(50, letter[1] - 50, "Sistema de Gestión de Solicitudes de Formación")
        
        # Footer
        canvas.setFillColorRGB(0.5, 0.5, 0.5)
        canvas.setFont('Helvetica', 8)
        canvas.drawString(50, 30, f"Generado: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
        canvas.drawRightString(letter[0] - 50, 30, f"Página {doc.page}")
        
        canvas.restoreState()
    
    # ============================================================================
# SOLO LA FUNCIÓN MODIFICADA - Reemplaza en tu generators.py
# ============================================================================

    def generate_solicitudes_report(self, solicitudes, filtros=None):
        """Genera reporte de solicitudes en PDF CON NIT"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=80,
            bottomMargin=50,
            title="Reporte de Solicitudes - SENA",  
            author="SENA - Sistema de Gestión",     
            subject="Solicitudes de Formación"
            
        )

        elements = []

        # Título
        title = Paragraph("REPORTE DE SOLICITUDES DE FORMACIÓN", self.styles['CustomTitle'])
        elements.append(title)
        elements.append(Spacer(1, 0.2 * inch))

        # Información de filtros
        if filtros:
            info_text = f"<b>Filtros aplicados:</b> {filtros}"
            elements.append(Paragraph(info_text, self.styles['Normal']))
            elements.append(Spacer(1, 0.2 * inch))

        # Estadísticas resumidas
        total = solicitudes.count()
        recibidas = solicitudes.filter(estado='RECIBIDA').count()
        respondidas = solicitudes.filter(estado='RESPONDIDA').count()
        atendidas = solicitudes.filter(estado='ATENDIDA').count()
        finalizadas = solicitudes.filter(estado='FINALIZADA').count()

        stats_data = [
            ['Total Solicitudes', 'Recibidas', 'Respondidas', 'Atendidas', 'Finalizadas'],
            [str(total), str(recibidas), str(respondidas), str(atendidas), str(finalizadas)]
        ]

        stats_table = Table(stats_data, colWidths=[1.1*inch]*5)
        stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey)
        ]))

        elements.append(stats_table)
        elements.append(Spacer(1, 0.3 * inch))

        # Tabla de solicitudes
        elements.append(Paragraph("Detalle de Solicitudes", self.styles['SectionHeader']))

        # 🔴  NIT 
        data = [['NIT Empresa', 'Empresa', 'Programa', 'Estado', 'Fecha Recepción', 'Instructor']]

        for sol in solicitudes[:50]:
            # 🔴 Obtener NIT de forma segura
            nit_empresa = sol.empresa.nit if hasattr(sol.empresa, 'nit') and sol.empresa.nit else 'Sin NIT'
        
            data.append([
                Paragraph(nit_empresa, self.styles['TableCell']),
                Paragraph(sol.empresa.nombre, self.styles['TableCell']),
                Paragraph(sol.programa.nombre, self.styles['TableCell']),
                Paragraph(sol.get_estado_display(), self.styles['TableCell']),
                Paragraph(sol.fecha_recepcion.strftime('%d/%m/%Y'), self.styles['TableCell']),
                Paragraph(sol.instructor_asignado.nombre if sol.instructor_asignado else 'Sin asignar', self.styles['TableCell'])
            ])

        # 🔴 AJUSTE: Ancho de columna para NIT (más grande que ID)
        table = Table(data, colWidths=[1.2*inch, 1.8*inch, 2*inch, 1*inch, 1.2*inch, 1.5*inch]) 
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))

        elements.append(table)

        if solicitudes.count() > 50:
            elements.append(Spacer(1, 0.2 * inch))
            note = Paragraph(
                f"<i>Nota: Mostrando las primeras 50 solicitudes de {solicitudes.count()} totales</i>",
                self.styles['Normal']
            )
            elements.append(note)

        # Construir PDF
        doc.build(elements, onFirstPage=self.add_header_footer, onLaterPages=self.add_header_footer)

        buffer.seek(0)
        return buffer
    
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
    
        # Título
        title = Paragraph("DIRECTORIO DE EMPRESAS", self.styles['CustomTitle'])
        elements.append(title)
        elements.append(Spacer(1, 0.3 * inch))
    
        # Estadísticas
        total = empresas.count()
        elements.append(Paragraph(f"<b>Total de empresas:</b> {total}", self.styles['Normal']))
        elements.append(Spacer(1, 0.3 * inch))
    
        # 🔴 TABLA CON NIT
        data = [['NIT', 'Empresa', 'Contacto', 'Teléfono', 'Correo', 'Municipio', 'N° Trab.']]
    
        for emp in empresas[:50]:
            # Obtener NIT de forma segura
            nit_empresa = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
        
            data.append([
                Paragraph(nit_empresa, self.styles['TableCell']),  # 🔴 NUEVA COLUMNA NIT
                Paragraph(emp.nombre, self.styles['TableCell']),
                Paragraph(emp.contacto, self.styles['TableCell']),
                Paragraph(emp.telefono or 'N/A', self.styles['TableCell']),
                Paragraph(emp.correo, self.styles['TableCell']),
                Paragraph(emp.municipio if emp.municipio else 'N/A', self.styles['TableCell']),
                Paragraph(str(emp.numero_trabajadores) if emp.numero_trabajadores else '0', self.styles['TableCell'])
            ])
    
        # 🔴 AJUSTE: Anchos de columna con NIT incluido
        table = Table(data, colWidths=[0.9*inch, 1.6*inch, 1.1*inch, 0.85*inch, 1.3*inch, 0.9*inch, 0.75*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))
    
        elements.append(table)
    
        doc.build(elements, onFirstPage=self.add_header_footer, onLaterPages=self.add_header_footer)
        buffer.seek(0)
        return buffer
    
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
        #Titulo
        title = Paragraph("CATÁLOGO DE PROGRAMAS DE FORMACIÓN", self.styles['CustomTitle'])
        elements.append(title)
        elements.append(Spacer(1, 0.3 * inch))
        
        #Estadisticas
        total = programas.count()
        elements.append(Paragraph(f"<b>Total de programas activos:</b> {total}", self.styles['Normal']))
        elements.append(Spacer(1,0.3 * inch))
        data = [['Código', 'Nombre del Programa', 'Área', 'Duración', 'Estado']]
        
        for prog in programas[:50]:
            data.append([
                Paragraph(prog.codigo or 'N/A', self.styles['TableCell']),
                Paragraph(prog.nombre, self.styles['TableCell']),
                Paragraph(prog.area.nombre, self.styles['TableCell']),
                Paragraph(f"{prog.duracion_horas}h" if prog.duracion_horas else 'N/A', self.styles['TableCell']),
                Paragraph('Activo' if prog.activo else 'Inactivo', self.styles['TableCell'])
            ])
        
        table = Table(data, colWidths=[0.9*inch, 3*inch, 1.5*inch, 0.8*inch, 0.8*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN',(0,0), (-1,-1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TOPPADDING', (0, 0),(-1, -1), 8),
            ('BOTTOMPADDING', (0, 0),(-1, -1), 8),
            ('LEFTPADDING', (0 ,0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1,-1), 5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))
        
        elements.append(table)
        #Nota si  hay mas de 50  programas
        if programas.count() > 50:
            elements.append(Spacer(1,0.2 * inch))
            note=Paragraph(
                f"<i>Nota: Mostrando los primeros 50 programas de {programas.count()} totales</i>",
                self.styles['Normal']
            )
            elements.append(note)
            
        doc.build(elements, onFirstPage=self.add_header_footer, onLaterPages=self.add_header_footer)
        buffer.seek(0)
        return buffer
    
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
            title ="Reporte Consolidado -SENA",
            author="SENA - Sistema de Gestión",
            subject="Reporte Consolidado"
        )
    
        elements = []
    
        # ========== PORTADA ==========
        title = Paragraph("REPORTE CONSOLIDADO DEL SISTEMA", self.styles['CustomTitle'])
        elements.append(title)
        elements.append(Spacer(1, 0.1 * inch))
    
        subtitle = Paragraph(
            "Sistema de Gestión de Solicitudes de Formación SENA",
            self.styles['CustomSubtitle']
        )
        elements.append(subtitle)
        elements.append(Spacer(1, 0.3 * inch))
    
        # Fecha de generación
        fecha_text = f"<b>Fecha de generación:</b> {timezone.now().strftime('%d/%m/%Y %H:%M')}"
        elements.append(Paragraph(fecha_text, self.styles['Normal']))
        elements.append(Spacer(1, 0.5 * inch))
    
        # ========== RESUMEN EJECUTIVO ==========
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
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
    
        elements.append(summary_table)
        elements.append(PageBreak())
    
        # ========== SECCIÓN 1: SOLICITUDES ==========
        elements.append(Paragraph("1. SOLICITUDES DE FORMACIÓN", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))
    
        # Estadísticas de solicitudes
        sol_stats_data = [
            ['Estado', 'Cantidad', 'Porcentaje'],
            ['Recibidas', str(solicitudes.filter(estado='RECIBIDA').count()), 
            f"{(solicitudes.filter(estado='RECIBIDA').count() / max(solicitudes.count(), 1) * 100):.1f}%"],
            ['Respondidas', str(solicitudes.filter(estado='RESPONDIDA').count()),
            f"{(solicitudes.filter(estado='RESPONDIDA').count() / max(solicitudes.count(), 1) * 100):.1f}%"],
            ['Atendidas', str(solicitudes.filter(estado='ATENDIDA').count()),
            f"{(solicitudes.filter(estado='ATENDIDA').count() / max(solicitudes.count(), 1) * 100):.1f}%"],
            ['Finalizadas', str(solicitudes.filter(estado='FINALIZADA').count()),
            f"{(solicitudes.filter(estado='FINALIZADA').count() / max(solicitudes.count(), 1) * 100):.1f}%"],
        ]
    
        sol_stats_table = Table(sol_stats_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
        sol_stats_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING',(0,0),(-1,-1),5),
            ('RIGHTPADDING',(0,0),(-1,-1),5),
        ]))
    
        elements.append(sol_stats_table)
        elements.append(Spacer(1, 0.3 * inch))
    
        # Top 10 solicitudes recientes
        elements.append(Paragraph("Últimas 10 Solicitudes", self.styles['SectionHeader']))
        elements.append(Spacer(1, 0.1 * inch))
    
        sol_data = [['NIT Empresa', 'Empresa', 'Programa', 'Estado', 'Fecha']]
        for sol in solicitudes[:10]:
            #obtener nit de forma segura
            nit_empresa = sol.empresa.nit if hasattr(sol.empresa, 'nit') and sol.empresa.nit else 'Sin NIT'
            sol_data.append([
                Paragraph(nit_empresa, self.styles['TableCell']),
                Paragraph(sol.empresa.nombre, self.styles['TableCell']),
                Paragraph(sol.programa.nombre, self.styles['TableCell']),
                Paragraph(sol.get_estado_display(), self.styles['TableCell']),
                Paragraph(sol.fecha_recepcion.strftime('%d/%m/%Y'), self.styles['TableCell'])
            ])
    
        sol_table = Table(sol_data, colWidths=[1.2*inch, 2*inch, 2*inch, 1*inch, 0.8*inch])
        sol_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))
    
        elements.append(sol_table)
        elements.append(PageBreak())
    
        # ========== SECCIÓN 2: EMPRESAS ==========
        elements.append(Paragraph("2. DIRECTORIO DE EMPRESAS", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph(
            f"Total de empresas registradas: <b>{empresas.count()}</b>",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.2 * inch))

        # Top 15 empresas - MEJORADO CON TEXTO COMPLETO
        emp_data = [['NIT','Empresa', 'Contacto', 'Teléfono', 'Municipio', 'Solicitudes']]
        for emp in empresas[:15]:
            nit_empresa = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
            emp_data.append([
                Paragraph (nit_empresa, self.styles['TableCell']),
                Paragraph(emp.nombre or 'Sin nombre', self.styles['TableCell']),
                Paragraph(emp.contacto or 'Sin contacto', self.styles['TableCell']),
                Paragraph(emp.telefono or 'N/A', self.styles['TableCell']),
                Paragraph(emp.municipio or 'No especificado', self.styles['TableCell']),
                Paragraph(str(emp.solicitud_set.count()), self.styles['TableCell'])
        ])

        # Anchos optimizados - sin truncar texto
        emp_table = Table(emp_data, colWidths=[1.1*inch, 1.8*inch, 1.2*inch, 0.9*inch, 1*inch, 0.9*inch])
        emp_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))
    
        elements.append(emp_table)
        elements.append(PageBreak())
    
        # ========== SECCIÓN 3: PROGRAMAS ==========
        elements.append(Paragraph("3. PROGRAMAS DE FORMACIÓN", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))
    
        # Programas por área
        from django.db.models import Count
        areas_stats = programas.values('area__nombre').annotate(
            total=Count('id')
        ).order_by('-total')[:5]
    
        area_data = [['Área de Formación', 'Cantidad de Programas']]
        for area in areas_stats:
            area_data.append([
                Paragraph(area['area__nombre'] or 'Sin área', self.styles['TableCell']),
                Paragraph(str(area['total']), self.styles['TableCell'])
            ])
    
        area_table = Table(area_data, colWidths=[4.5*inch, 1.5*inch])
        area_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))
    
        elements.append(area_table)
        elements.append(Spacer(1, 0.3 * inch))
    
        # Lista de programas
        elements.append(Paragraph("Programas Más Solicitados", self.styles['SectionHeader']))
        elements.append(Spacer(1, 0.1 * inch))
    
        prog_data = [['Codigo','Programa', 'Área', 'Duración', 'Solicitudes']]
        for prog in programas.annotate(num_sol=Count('solicitud')).order_by('-num_sol')[:15]:
            prog_data.append([
                Paragraph(prog.codigo or 'N/A', self.styles['TableCell']),
                Paragraph(prog.nombre, self.styles['TableCell']),
                Paragraph(prog.area.nombre, self.styles['TableCell']),
                Paragraph(f"{prog.duracion_horas}h" if prog.duracion_horas else 'N/A', self.styles['TableCell']),
                Paragraph(str(prog.num_sol), self.styles['TableCell'])
            ])
    
        prog_table = Table(prog_data, colWidths=[0.9*inch, 2.2*inch, 1.6*inch, 0.8*inch, 1*inch])
        prog_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))
    
        elements.append(prog_table)
        elements.append(PageBreak())
    
        # ========== SECCIÓN 4: INSTRUCTORES ==========
        elements.append(Paragraph("4. INSTRUCTORES", self.styles['CustomSubtitle']))
        elements.append(Spacer(1, 0.2 * inch))
    
        elements.append(Paragraph(
            f"Total de instructores: <b>{instructores.count()}</b> "
            f"(Activos: <b>{instructores.filter(activo=True).count()}</b>)",
            self.styles['Normal']
        ))
        elements.append(Spacer(1, 0.2 * inch))
    
        inst_data = [['Instructor', 'Correo', 'Teléfono', 'Especialidades', 'Solicitudes']]
        for inst in instructores.filter(activo=True)[:20]:
            inst_data.append([
                Paragraph(inst.nombre, self.styles['TableCell']),
                Paragraph(inst.correo, self.styles['TableCell']),
                Paragraph(inst.telefono if inst.telefono else 'N/A', self.styles['TableCell']),
                Paragraph(str(inst.especialidad.count()), self.styles['TableCell']),
                Paragraph(str(inst.solicitud_set.count()), self.styles['TableCell'])
            ])
    
        inst_table = Table(inst_data, colWidths=[1.6*inch, 1.9*inch, 0.8*inch, 1.1*inch, 0.9*inch])
        inst_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))
    
        elements.append(inst_table)
    
        # ========== PIE DE REPORTE ==========
        elements.append(Spacer(1, 0.5 * inch))
        elements.append(Paragraph(
            "<i>--- Fin del Reporte Consolidado ---</i>",
            self.styles['Normal']
        ))
    
        # Construir PDF
        doc.build(elements, onFirstPage=self.add_header_footer, onLaterPages=self.add_header_footer)
    
        buffer.seek(0)
        return buffer

class ExcelReportGenerator:
    """Generador de reportes Excel con formato SENA"""
    
    def __init__(self):
        self.header_fill = PatternFill(start_color="2e7d32", end_color="2e7d32", fill_type="solid")
        self.header_font = Font(bold=True, color="FFFFFF", size=12)
        self.border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
    
    def apply_header_style(self, ws, row=1):
        """Aplica estilo al encabezado"""
        for cell in ws[row]:
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.border
    
    def adjust_column_width(self, ws):
        """Ajusta el ancho de las columnas automáticamente"""
        # Recorremos las columnas por índice para evitar errores con MergedCell
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
                    # Ignoramos celdas que no se puedan convertir a str
                    pass
            adjusted_width = max(12, min(max_length + 4,60))
            ws.column_dimensions[column_letter].width = adjusted_width
    
    def generate_solicitudes_report(self, solicitudes):
        """Genera reporte de solicitudes en Excel"""
        wb = Workbook()
        ws = wb.active
        ws.title = "Solicitudes"
        
        # Título
        ws['A1'] = 'REPORTE DE SOLICITUDES DE FORMACIÓN'
        ws['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws['A1'].alignment = Alignment(horizontal='center')
        ws.merge_cells('A1:I1')
        
        # Fecha de generación
        ws['A2'] = f'Generado: {timezone.now().strftime("%d/%m/%Y %H:%M")}'
        ws['A2'].font = Font(italic=True, size=10)
        ws.merge_cells('A2:I2')
        
        # Estadísticas
        ws['A4'] = 'RESUMEN ESTADÍSTICO'
        ws['A4'].font = Font(bold=True, size=12)
        
        stats_row = 5
        stats_data = [
            ['Total Solicitudes', solicitudes.count(), 'Recibidas', solicitudes.filter(estado='RECIBIDA').count()],
            ['Respondidas', solicitudes.filter(estado='RESPONDIDA').count(), 'Finalizadas', solicitudes.filter(estado='FINALIZADA').count()]
        ]

        for row_idx, row_data in enumerate(stats_data, start=stats_row):
            for col_idx, value in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center')  # ✓ CENTRADO
                if col_idx % 2 == 1:  # Etiquetas en columnas impares
                    cell.fill = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
                    cell.font = Font(bold=True)
        
        # Encabezados de tabla
        headers = ['NIT Empresa', 'Empresa', 'Programa', 'Área', 'Estado', 'Fecha Recepción', 'Instructor', 'Observaciones']
        ws.append([])  # Línea en blanco
        ws.append(headers)
        
        self.apply_header_style(ws, row=7)
        
        # Datos
        for sol in solicitudes:
            #obtener nit de forma segura
            nit_empresa = sol.empresa.nit if hasattr(sol.empresa, 'nit') and sol.empresa.nit else 'Sin NIT'
            ws.append([
                nit_empresa,
                sol.empresa.nombre,
                sol.programa.nombre,
                sol.programa.area.nombre,
                sol.get_estado_display(),
                sol.fecha_recepcion.strftime('%d/%m/%Y %H:%M'),
                sol.instructor_asignado.nombre if sol.instructor_asignado else 'Sin asignar',
                sol.observaciones[:100] if sol.observaciones else 'N/A'
            ])
        
        # Aplicar bordes a todas las celdas de datos
        for row in ws.iter_rows(min_row=7, max_row=ws.max_row, max_col=8):
            for cell in row:
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        
        self.adjust_column_width(ws)
        
        # Guardar en buffer
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer
    
    def generate_empresas_report(self, empresas):
        """Genera reporte de empresas en Excel"""
        wb = Workbook()
        ws = wb.active
        ws.title = "Empresas"
    
        # Título
        ws['A1'] = 'DIRECTORIO DE EMPRESAS'
        ws['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws.merge_cells('A1:H1')
    
        ws['A2'] = f'Total de empresas: {empresas.count()}'
        ws['A2'].font = Font(bold=True, size=11)
    
        # Encabezados en fila 4
        headers = ['NIT', 'Nombre', 'Contacto', 'Teléfono', 'Correo', 'Municipio', 'Dirección', 'N° Trabajadores']
    
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=4, column=col_idx, value=header)
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.border
    
        # Datos desde fila 5
        current_row = 5
        for emp in empresas:
            nit_empresa = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
        
            # Crear lista con los datos de esta empresa
            datos_empresa = [
                nit_empresa,
                emp.nombre,
                emp.contacto,
                emp.telefono or 'N/A',
                emp.correo,
                emp.municipio or 'N/A',
                emp.direccion or 'N/A',
                emp.numero_trabajadores or 0
            ]
        
            # Escribir cada celda
            for col_idx, value in enumerate(datos_empresa, start=1):
                cell = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        
            current_row += 1
    
        self.adjust_column_width(ws)
    
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer
    def generate_programas_report(self, programas):
        """Genera reporte de programas en Excel"""
        wb = Workbook()
        ws = wb.active
        ws.title = "Programas"
    
        # Título
        ws['A1'] = 'CATÁLOGO DE PROGRAMAS DE FORMACIÓN'
        ws['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws.merge_cells('A1:F1')
    
        # Encabezados en fila 3
        headers = ['ID', 'Código', 'Nombre', 'Área', 'Duración (horas)', 'Estado']
    
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=3, column=col_idx, value=header)
            cell.fill = self.header_fill  # ✅ CORRECTO (sin "cell")
            cell.font = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.border
    
        # Datos desde fila 4
        current_row = 4
        for prog in programas:
            datos_programa = [
                prog.id,
                prog.codigo or 'N/A',
                prog.nombre,
                prog.area.nombre,
                prog.duracion_horas or 0,
                'Activo' if prog.activo else 'Inactivo'
            ]
        
            for col_idx, value in enumerate(datos_programa, start=1):
                cell = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        
            current_row += 1
    
        # Ajuste manual de anchos
        ws.column_dimensions['A'].width = 8   # ID
        ws.column_dimensions['B'].width = 15  # Código
        ws.column_dimensions['C'].width = 45  # Nombre
        ws.column_dimensions['D'].width = 25  # Área
        ws.column_dimensions['E'].width = 18  # Duración
        ws.column_dimensions['F'].width = 12  # Estado
    
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer
    def generate_instructores_report(self, instructores):
        """Genera reporte de instructores en Excel"""
        wb = Workbook()
        ws = wb.active
        ws.title = "Instructores"
    
        # Título
        ws['A1'] = 'DIRECTORIO DE INSTRUCTORES'
        ws['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws.merge_cells('A1:G1')
        ws['A1'].alignment = Alignment(horizontal='center')
    
        # Subtítulo con totales
        total = instructores.count()
        activos = instructores.filter(activo=True).count()
        ws['A2'] = f'Total: {total} | Activos: {activos}'
        ws['A2'].font = Font(bold=True, size=11)
        ws.merge_cells('A2:G2')
    
        # Encabezados en fila 4
        headers = ['ID', 'Nombre', 'Correo', 'Teléfono', 'Estado', 'Especialidades', 'Solicitudes Asignadas']
    
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=4, column=col_idx, value=header)
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = self.border
    
        # Datos desde fila 5
        current_row = 5
        for inst in instructores:
            datos_instructor = [
                inst.id,
                inst.nombre,
                inst.correo,
                inst.telefono or 'N/A',
                'Activo' if inst.activo else 'Inactivo',
                inst.especialidad.count(),
                inst.solicitud_set.count()
            ]
        
            for col_idx, value in enumerate(datos_instructor, start=1):
                cell = ws.cell(row=current_row, column=col_idx, value=value)
                cell.border = self.border  # ✅ CLAVE: Aplicar bordes
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        
            current_row += 1
    
        # Ajuste manual de anchos
        ws.column_dimensions['A'].width = 8   # ID
        ws.column_dimensions['B'].width = 30  # Nombre
        ws.column_dimensions['C'].width = 28  # Correo
        ws.column_dimensions['D'].width = 15  # Teléfono
        ws.column_dimensions['E'].width = 12  # Estado
        ws.column_dimensions['F'].width = 18  # Especialidades
        ws.column_dimensions['G'].width = 22  # Solicitudes
    
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer
        
        
    def generate_consolidated_report(self, solicitudes, empresas, programas, instructores):
        """Genera reporte consolidado en Excel con múltiples hojas"""
        wb = Workbook()
        
        # ========== HOJA 1: RESUMEN EJECUTIVO ==========
        ws_resumen = wb.active
        ws_resumen.title = "Resumen Ejecutivo"
        
        # Título
        ws_resumen['A1'] = 'REPORTE CONSOLIDADO DEL SISTEMA'
        ws_resumen['A1'].font = Font(bold=True, size=18, color="2e7d32")
        ws_resumen.merge_cells('A1:D1')
        ws_resumen['A1'].alignment = Alignment(horizontal='center')
        
        ws_resumen['A2'] = f'Generado: {timezone.now().strftime("%d/%m/%Y %H:%M")}'
        ws_resumen['A2'].font = Font(italic=True)
        ws_resumen.merge_cells('A2:D2')
        
        # Estadísticas generales
        ws_resumen['A4'] = 'ESTADÍSTICAS GENERALES'
        ws_resumen['A4'].font = Font(bold=True, size=14, color="2e7d32")
        
        stats = [
            ['Módulo', 'Total', 'Activos/Finalizadas', 'Porcentaje'],
            ['Solicitudes', solicitudes.count(), 
             solicitudes.filter(estado='FINALIZADA').count(),
             f"{(solicitudes.filter(estado='FINALIZADA').count() / max(solicitudes.count(), 1) * 100):.1f}%"],
            ['Empresas', empresas.count(), 
             empresas.filter(solicitud__isnull=False).distinct().count(),
             f"{(empresas.filter(solicitud__isnull=False).distinct().count() / max(empresas.count(), 1) * 100):.1f}%"],
            ['Programas', programas.count(), 
             programas.filter(activo=True).count(),
             f"{(programas.filter(activo=True).count() / max(programas.count(), 1) * 100):.1f}%"],
            ['Instructores', instructores.count(), 
             instructores.filter(activo=True).count(),
             f"{(instructores.filter(activo=True).count() / max(instructores.count(), 1) * 100):.1f}%"],
        ]
        
        for idx, row in enumerate(stats, start=6):
            for col_idx, value in enumerate(row, start=1):
                cell = ws_resumen.cell(row=idx, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center')
                if idx == 6:
                    cell.fill = self.header_fill
                    cell.font = self.header_font
                    
        
        # Ajustar anchos
        ws_resumen.column_dimensions['A'].width = 20
        ws_resumen.column_dimensions['B'].width = 15
        ws_resumen.column_dimensions['C'].width = 20
        ws_resumen.column_dimensions['D'].width = 15
        
        # ========== HOJA 2: SOLICITUDES ==========
        ws_sol = wb.create_sheet("Solicitudes")
        
        ws_sol['A1'] = 'SOLICITUDES DE FORMACIÓN'
        ws_sol['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws_sol.merge_cells('A1:H1')
        
        # Estadísticas por estado
        ws_sol['A3'] = 'DISTRIBUCIÓN POR ESTADO'
        ws_sol['A3'].font = Font(bold=True, size=12)
        
        estados = [
            ['Estado', 'Cantidad', 'Porcentaje'],
            ['Recibidas', solicitudes.filter(estado='RECIBIDA').count(), 
             f"{(solicitudes.filter(estado='RECIBIDA').count() / max(solicitudes.count(), 1) * 100):.1f}%"],
            ['Respondidas', solicitudes.filter(estado='RESPONDIDA').count(),
             f"{(solicitudes.filter(estado='RESPONDIDA').count() / max(solicitudes.count(), 1) * 100):.1f}%"],
            ['Atendidas', solicitudes.filter(estado='ATENDIDA').count(),
             f"{(solicitudes.filter(estado='ATENDIDA').count() / max(solicitudes.count(), 1) * 100):.1f}%"],
            ['Finalizadas', solicitudes.filter(estado='FINALIZADA').count(),
             f"{(solicitudes.filter(estado='FINALIZADA').count() / max(solicitudes.count(), 1) * 100):.1f}%"],
        ]
        
        for idx, row in enumerate(estados, start=4):
            for col_idx, value in enumerate(row, start=1):
                cell = ws_sol.cell(row=idx, column=col_idx, value=value)
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center')
                if idx == 4:
                    cell.fill = self.header_fill
                    cell.font = self.header_font
        
        # Listado completo
        ws_sol['A10'] = 'LISTADO COMPLETO'
        ws_sol['A10'].font = Font(bold=True, size=12)
        
        headers = ['NIT Empresa', 'Empresa', 'Programa', 'Área', 'Estado', 'Fecha Recepción', 'Instructor', 'Observaciones']
        ws_sol.append([])
        ws_sol.append(headers)
        
        header_row = ws_sol.max_row
        for cell in ws_sol[header_row]:
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.border = self.border
        
        for sol in solicitudes:
            nit_empresa = sol.empresa.nit if hasattr(sol.empresa, 'nit') and sol.empresa.nit else 'Sin NIT'
            ws_sol.append([
                nit_empresa,
                sol.empresa.nombre,
                sol.programa.nombre,
                sol.programa.area.nombre,
                sol.get_estado_display(),
                sol.fecha_recepcion.strftime('%d/%m/%Y %H:%M'),
                sol.instructor_asignado.nombre if sol.instructor_asignado else 'Sin asignar',
                sol.observaciones[:100] if sol.observaciones else ''
            ])
        #Aplicar centrado  a todas las celdas de datos
        for row in ws_sol.iter_rows(min_row=12, max_row=ws_sol.max_row,max_col=8):
            for cell in row:
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center',wrap_text=True)
        
        self.adjust_column_width(ws_sol)
        
        # ========== HOJA 3: EMPRESAS ==========
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
        
        for emp in empresas:
            nit_empresa = emp.nit if hasattr(emp, 'nit') and emp.nit else 'Sin NIT'
            ws_emp.append([
                nit_empresa,
                emp.nombre,
                emp.contacto,
                emp.telefono or 'N/A',
                emp.correo,
                emp.municipio or 'N/A',
                emp.direccion or 'N/A',
                emp.numero_trabajadores or 0,
                emp.solicitud_set.count()
            ])
            #Aplicar Centrado
        for row in ws_emp.iter_rows(min_row=3,max_row=ws_emp.max_row, max_col=9):
            for cell in row:
                cell.border = self.border
                cell.alignment = Alignment(horizontal='center', vertical='center',wrap_text=True)
        
        self.adjust_column_width(ws_emp)
        
        # ========== HOJA 4: PROGRAMAS ==========
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
        
        from django.db.models import Count
        for prog in programas.annotate(num_sol=Count('solicitud')):
            ws_prog.append([
                prog.id,
                prog.codigo or 'N/A',
                prog.nombre,
                prog.area.nombre,
                prog.duracion_horas or 0,
                'Activo' if prog.activo else 'Inactivo',
                prog.num_sol
            ])
        #Aplicar centrado
        for row in ws_prog.iter_rows(min_row=3, max_row=ws_prog.max_row, max_col=7):
            for cell in row:
                cell.border = self.border
                cell.alignment=Alignment( horizontal='center', vertical='center',wrap_text=True)
        self.adjust_column_width(ws_prog)
        
        # ========== HOJA 5: INSTRUCTORES ==========
        ws_inst = wb.create_sheet("Instructores")
        
        ws_inst['A1'] = 'DIRECTORIO DE INSTRUCTORES'
        ws_inst['A1'].font = Font(bold=True, size=16, color="2e7d32")
        ws_inst.merge_cells('A1:G1')
        
        inst_headers = ['ID', 'Nombre', 'Correo', 'Teléfono', 'Estado', 'Especialidades', 'Solicitudes Asignadas']
        ws_inst.append([])
        ws_inst.append(inst_headers)
        
        for cell in ws_inst[3]:
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.border = self.border
        
        for inst in instructores:
            ws_inst.append([
                inst.id,
                inst.nombre,
                inst.correo,
                inst.telefono,
                'Activo' if inst.activo else 'Inactivo',
                inst.especialidad.count(),
                inst.solicitud_set.count()
            ])
        #Aplicar centrado
        for row in ws_inst.iter_rows(min_row=3, max_row=ws_inst.max_row, max_col=7):
            for cell in row:
                cell.border=self.border
                cell.alignment = Alignment(horizontal='center', vertical='center',wrap_text=True)
        
        self.adjust_column_width(ws_inst)
        
        # Guardar
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer