"""
Vistas del módulo de reportes
Sistema de Gestión de Solicitudes SENA
"""

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, FileResponse
from django.utils import timezone

from solicitudes.models import Solicitud
from empresas.models import Empresa
from programas.models import Programa
from instructores.models import Instructor

from .generators import PDFReportGenerator, ExcelReportGenerator


@login_required
def panel_reportes(request):
    """Panel principal de reportes con estadísticas"""
    
    # Estadísticas para el panel
    context = {
        # Totales
        'total_solicitudes': Solicitud.objects.count(),
        'total_empresas': Empresa.objects.count(),
        'total_programas': Programa.objects.filter(activo=True).count(),
        'total_instructores': Instructor.objects.filter(activo=True).count(),
        
        # Solicitudes por estado
        'solicitudes_recibidas': Solicitud.objects.filter(estado='RECIBIDA').count(),
        'solicitudes_respondidas': Solicitud.objects.filter(estado='RESPONDIDA').count(),
        'solicitudes_atendidas': Solicitud.objects.filter(estado='ATENDIDA').count(),
        'solicitudes_finalizadas': Solicitud.objects.filter(estado='FINALIZADA').count(),
        
        # Para filtros
        'programas': Programa.objects.filter(activo=True).order_by('nombre'),
        'empresas': Empresa.objects.all().order_by('nombre'),
        'estados': Solicitud.ESTADO_CHOICES,
    }
    
    return render(request, 'reportes/panel_reportes.html', context)


# ============================================================================
# REPORTES INDIVIDUALES - SOLICITUDES
# ============================================================================

@login_required
def generar_reporte_solicitudes_pdf(request):
    """Genera reporte PDF de solicitudes con filtros"""
    
    # Obtener filtros
    estado = request.GET.get('estado', '')
    programa_id = request.GET.get('programa', '')
    empresa_id = request.GET.get('empresa', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    # Consulta base
    solicitudes = Solicitud.objects.select_related(
        'empresa', 'programa', 'programa__area', 'instructor_asignado'
    ).all()
    
    # Aplicar filtros
    filtros_texto = []
    
    if estado:
        solicitudes = solicitudes.filter(estado=estado)
        filtros_texto.append(f"Estado: {dict(Solicitud.ESTADO_CHOICES)[estado]}")
    
    if programa_id:
        solicitudes = solicitudes.filter(programa_id=programa_id)
        try:
            programa = Programa.objects.get(id=programa_id)
            filtros_texto.append(f"Programa: {programa.nombre}")
        except Programa.DoesNotExist:
            pass
    
    if empresa_id:
        solicitudes = solicitudes.filter(empresa_id=empresa_id)
        try:
            empresa = Empresa.objects.get(id=empresa_id)
            filtros_texto.append(f"Empresa: {empresa.nombre}")
        except Empresa.DoesNotExist:
            pass
    
    if fecha_desde:
        solicitudes = solicitudes.filter(fecha_recepcion__gte=fecha_desde)
        filtros_texto.append(f"Desde: {fecha_desde}")
    
    if fecha_hasta:
        solicitudes = solicitudes.filter(fecha_recepcion__lte=fecha_hasta)
        filtros_texto.append(f"Hasta: {fecha_hasta}")
    
    solicitudes = solicitudes.order_by('-fecha_recepcion')
    
    # Generar PDF
    generator = PDFReportGenerator()
    buffer = generator.generate_solicitudes_report(
        solicitudes,
        filtros=' | '.join(filtros_texto) if filtros_texto else 'Ninguno'
    )
    
    # Respuesta HTTP
    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'solicitudes_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@login_required
def generar_reporte_solicitudes_excel(request):
    """Genera reporte Excel de solicitudes con filtros"""
    
    # Mismo filtrado que PDF
    estado = request.GET.get('estado', '')
    programa_id = request.GET.get('programa', '')
    empresa_id = request.GET.get('empresa', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    solicitudes = Solicitud.objects.select_related(
        'empresa', 'programa', 'programa__area', 'instructor_asignado'
    ).all()
    
    if estado:
        solicitudes = solicitudes.filter(estado=estado)
    if programa_id:
        solicitudes = solicitudes.filter(programa_id=programa_id)
    if empresa_id:
        solicitudes = solicitudes.filter(empresa_id=empresa_id)
    if fecha_desde:
        solicitudes = solicitudes.filter(fecha_recepcion__gte=fecha_desde)
    if fecha_hasta:
        solicitudes = solicitudes.filter(fecha_recepcion__lte=fecha_hasta)
    
    solicitudes = solicitudes.order_by('-fecha_recepcion')
    
    # Generar Excel
    generator = ExcelReportGenerator()
    buffer = generator.generate_solicitudes_report(solicitudes)
    
    buffer.seek(0)
    filename = f'solicitudes_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ============================================================================
# REPORTES INDIVIDUALES - EMPRESAS
# ============================================================================

@login_required
def generar_reporte_empresas_pdf(request):
    """Genera reporte PDF de empresas"""
    empresas = Empresa.objects.all().order_by('nombre')
    
    generator = PDFReportGenerator()
    buffer = generator.generate_empresas_report(empresas)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'empresas_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@login_required
def generar_reporte_empresas_excel(request):
    """Genera reporte Excel de empresas"""
    empresas = Empresa.objects.all().order_by('nombre')
    
    generator = ExcelReportGenerator()
    buffer = generator.generate_empresas_report(empresas)
    
    buffer.seek(0)
    filename = f'empresas_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')




# ============================================================================
# REPORTES INDIVIDUALES - INSTRUCTORES
# ============================================================================

@login_required
def generar_reporte_instructores_pdf(request):
    """Genera reporte PDF de instructores"""
    instructores = Instructor.objects.prefetch_related('especialidad').all().order_by('nombre')
    
    generator = PDFReportGenerator()
    # Reutilizamos el método de empresas como base
    # Puedes crear un método específico si necesitas formato diferente
    
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.units import inch
    import io
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=80, bottomMargin=50)
    
    elements = []
    
    # Título
    title = Paragraph("DIRECTORIO DE INSTRUCTORES", generator.styles['CustomTitle'])
    elements.append(title)
    elements.append(Spacer(1, 0.3 * inch))
    
    # Estadísticas
    total = instructores.count()
    activos = instructores.filter(activo=True).count()
    elements.append(Paragraph(
        f"<b>Total de instructores:</b> {total} (Activos: {activos})",
        generator.styles['Normal']
    ))
    elements.append(Spacer(1, 0.3 * inch))
    
    # Tabla
    data = [['Instructor', 'Correo', 'Teléfono', 'Especialidades', 'Estado', 'Solicitudes']]
    
    for inst in instructores[:50]:
        data.append([
            inst.nombre[:30],
            inst.correo[:30],
            inst.telefono[:15],
            str(inst.especialidad.count()),
            'Activo' if inst.activo else 'Inactivo',
            str(inst.solicitud_set.count())
        ])
    
    table = Table(data, colWidths=[1.5*inch, 1.5*inch, 1*inch, 1*inch, 0.8*inch, 0.9*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
    ]))
    
    elements.append(table)
    
    doc.build(elements, onFirstPage=generator.add_header_footer, onLaterPages=generator.add_header_footer)
    buffer.seek(0)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'instructores_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@login_required
def generar_reporte_instructores_excel(request):
    """Genera reporte Excel de instructores"""
    instructores = Instructor.objects.prefetch_related('especialidad').all().order_by('nombre')
    
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    import io
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Instructores"
    
    # Título
    ws['A1'] = 'DIRECTORIO DE INSTRUCTORES'
    ws['A1'].font = Font(bold=True, size=16, color="2e7d32")
    ws.merge_cells('A1:G1')
    
    ws['A2'] = f'Total: {instructores.count()} | Activos: {instructores.filter(activo=True).count()}'
    ws['A2'].font = Font(bold=True, size=11)
    
    # Encabezados
    headers = ['ID', 'Nombre', 'Correo', 'Teléfono', 'Estado', 'Especialidades', 'Solicitudes Asignadas']
    ws.append([])
    ws.append(headers)
    
    header_fill = PatternFill(start_color="2e7d32", end_color="2e7d32", fill_type="solid")
    for cell in ws[4]:
        cell.fill = header_fill
        cell.font = Font(bold=True, color="FFFFFF")
    
    # Datos
    for inst in instructores:
        ws.append([
            inst.id,
            inst.nombre,
            inst.correo,
            inst.telefono,
            'Activo' if inst.activo else 'Inactivo',
            inst.especialidad.count(),
            inst.solicitud_set.count()
        ])
    
    # Ajustar anchos
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        ws.column_dimensions[column_letter].width = min(max_length + 2, 50)
    
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    filename = f'instructores_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ============================================================================
# REPORTES CONSOLIDADOS - TODO EL SISTEMA
# ============================================================================

@login_required
def generar_reporte_consolidado_pdf(request):
    """Genera reporte consolidado PDF de todo el sistema"""
    
    solicitudes = Solicitud.objects.select_related(
        'empresa', 'programa', 'programa__area', 'instructor_asignado'
    ).all()
    
    empresas = Empresa.objects.all()
    programas = Programa.objects.select_related('area').all()
    instructores = Instructor.objects.prefetch_related('especialidad').all()
    
    generator = PDFReportGenerator()
    buffer = generator.generate_consolidated_report(
        solicitudes, empresas, programas, instructores
    )
    
    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'reporte_consolidado_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@login_required
def generar_reporte_consolidado_excel(request):
    """Genera reporte consolidado Excel de todo el sistema (5 hojas)"""
    
    solicitudes = Solicitud.objects.select_related(
        'empresa', 'programa', 'programa__area', 'instructor_asignado'
    ).all()
    
    empresas = Empresa.objects.all()
    programas = Programa.objects.select_related('area').all()
    instructores = Instructor.objects.prefetch_related('especialidad').all()
    
    generator = ExcelReportGenerator()
    buffer = generator.generate_consolidated_report(
        solicitudes, empresas, programas, instructores
    )
    
    buffer.seek(0)
    filename = f'reporte_consolidado_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')