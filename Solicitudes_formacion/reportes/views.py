"""
Vistas del módulo de reportes
Sistema de Gestión de Solicitudes SENA
"""

from datetime import datetime, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, FileResponse
from django.utils import timezone

from solicitudes.models import Solicitud
from empresas.models import Empresa
from programas.models import Programa
from instructores.models import Instructor

from .generators import PDFReportGenerator, ExcelReportGenerator


# ============================================================================
# FUNCIÓN AUXILIAR PARA RANGOS DE FECHA
# ============================================================================

def calcular_rango_fechas(rango_fecha):
    """
    Calcula las fechas de inicio y fin según el rango seleccionado
    Retorna (fecha_inicio, fecha_fin) o (None, None) si no hay rango
    """
    if not rango_fecha:
        return None, None
    
    hoy = timezone.now().date()
    fecha_inicio = None
    fecha_fin = None
    
    if rango_fecha == 'hoy':
        fecha_inicio = hoy
        fecha_fin = hoy
    
    elif rango_fecha == 'ayer':
        ayer = hoy - timedelta(days=1)
        fecha_inicio = ayer
        fecha_fin = ayer
    
    elif rango_fecha == 'esta_semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        fecha_inicio = inicio_semana
        fecha_fin = hoy
    
    elif rango_fecha == 'semana_pasada':
        inicio_semana_pasada = hoy - timedelta(days=hoy.weekday() + 7)
        fin_semana_pasada = inicio_semana_pasada + timedelta(days=6)
        fecha_inicio = inicio_semana_pasada
        fecha_fin = fin_semana_pasada
    
    elif rango_fecha == 'este_mes':
        inicio_mes = hoy.replace(day=1)
        fecha_inicio = inicio_mes
        fecha_fin = hoy
    
    elif rango_fecha == 'mes_pasado':
        primer_dia_mes_actual = hoy.replace(day=1)
        ultimo_dia_mes_pasado = primer_dia_mes_actual - timedelta(days=1)
        primer_dia_mes_pasado = ultimo_dia_mes_pasado.replace(day=1)
        fecha_inicio = primer_dia_mes_pasado
        fecha_fin = ultimo_dia_mes_pasado
    
    elif rango_fecha == 'ultimos_7_dias':
        fecha_inicio = hoy - timedelta(days=7)
        fecha_fin = hoy
    
    elif rango_fecha == 'ultimos_30_dias':
        fecha_inicio = hoy - timedelta(days=30)
        fecha_fin = hoy
    
    elif rango_fecha == 'este_año':
        fecha_inicio = hoy.replace(month=1, day=1)
        fecha_fin = hoy
    
    return fecha_inicio, fecha_fin


# ============================================================================
# PANEL PRINCIPAL DE REPORTES
# ============================================================================

@login_required
def panel_reportes(request):
    """Panel principal de reportes con estadísticas y filtros"""
    
    # Estadísticas para el panel
    context = {
        # Totales generales
        'total_solicitudes': Solicitud.objects.count(),
        'total_empresas': Empresa.objects.count(),
        'total_programas': Programa.objects.filter(activo=True).count(),
        'total_instructores': Instructor.objects.filter(activo=True).count(),
        
        # Solicitudes por estado
        'solicitudes_recibidas': Solicitud.objects.filter(estado='RECIBIDA').count(),
        'solicitudes_respondidas': Solicitud.objects.filter(estado='RESPONDIDA').count(),
        'solicitudes_atendidas': Solicitud.objects.filter(estado='ATENDIDA').count(),
        'solicitudes_finalizadas': Solicitud.objects.filter(estado='FINALIZADA').count(),
        
        # Datos para los filtros
        'programas': Programa.objects.filter(activo=True).order_by('nombre'),
        'empresas': Empresa.objects.all().order_by('nombre'),
        'estados': Solicitud.ESTADO_CHOICES,
        
        # Mantener valores de filtros seleccionados
        'estado_filter': request.GET.get('estado', ''),
        'programa_filter': request.GET.get('programa', ''),
        'empresa_filter': request.GET.get('empresa', ''),
        'nit_filter': request.GET.get('nit', ''),
        'rango_fecha': request.GET.get('rango_fecha', ''),
    }
    
    return render(request, 'reportes/panel_reportes.html', context)


# ============================================================================
# REPORTES INDIVIDUALES - SOLICITUDES
# ============================================================================

@login_required
def generar_reporte_solicitudes_pdf(request):
    """Genera reporte PDF de solicitudes con filtros avanzados"""
    
    # Obtener todos los filtros
    estado = request.GET.get('estado', '')
    programa_id = request.GET.get('programa', '')
    empresa_id = request.GET.get('empresa', '')
    nit = request.GET.get('nit', '')
    rango_fecha = request.GET.get('rango_fecha', '')
    
    # Consulta base con relaciones optimizadas
    solicitudes = Solicitud.objects.select_related(
        'empresa', 'programa', 'programa__area', 'instructor_asignado'
    ).all()
    
    # Lista para mostrar filtros aplicados en el reporte
    filtros_texto = []
    
    # Filtro de Estado
    if estado:
        solicitudes = solicitudes.filter(estado=estado)
        estado_nombre = dict(Solicitud.ESTADO_CHOICES).get(estado, estado)
        filtros_texto.append(f"Estado: {estado_nombre}")
    
    # Filtro de Programa
    if programa_id:
        solicitudes = solicitudes.filter(programa_id=programa_id)
        try:
            programa = Programa.objects.get(id=programa_id)
            filtros_texto.append(f"Programa: {programa.nombre}")
        except Programa.DoesNotExist:
            pass
    
    # Filtro de Empresa
    if empresa_id:
        solicitudes = solicitudes.filter(empresa_id=empresa_id)
        try:
            empresa = Empresa.objects.get(id=empresa_id)
            filtros_texto.append(f"Empresa: {empresa.nombre}")
        except Empresa.DoesNotExist:
            pass
    
    # Filtro de NIT
    if nit:
        nit_limpio = nit.strip()
        solicitudes = solicitudes.filter(empresa__nit__icontains=nit_limpio)
        filtros_texto.append(f"NIT: {nit_limpio}")
    
    # Filtro de Rango de Fecha
    if rango_fecha:
        fecha_inicio, fecha_fin = calcular_rango_fechas(rango_fecha)
        
        if fecha_inicio and fecha_fin:
            # Convertir a datetime con timezone para comparación correcta
            fecha_inicio_dt = timezone.make_aware(
                datetime.combine(fecha_inicio, datetime.min.time())
            )
            fecha_fin_dt = timezone.make_aware(
                datetime.combine(fecha_fin, datetime.max.time())
            )
            
            solicitudes = solicitudes.filter(
                fecha_recepcion__gte=fecha_inicio_dt,
                fecha_recepcion__lte=fecha_fin_dt
            )
            
            # Texto amigable para mostrar en el reporte
            rangos_texto = {
                'hoy': 'Hoy',
                'ayer': 'Ayer',
                'esta_semana': 'Esta semana',
                'semana_pasada': 'Semana pasada',
                'este_mes': 'Este mes',
                'mes_pasado': 'Mes pasado',
                'ultimos_7_dias': 'Últimos 7 días',
                'ultimos_30_dias': 'Últimos 30 días',
                'este_año': 'Este año'
            }
            filtros_texto.append(f"Período: {rangos_texto.get(rango_fecha, rango_fecha)}")
    
    # Ordenar por fecha más reciente
    solicitudes = solicitudes.order_by('-fecha_recepcion')
    
    # Generar el PDF
    generator = PDFReportGenerator()
    buffer = generator.generate_solicitudes_report(
        solicitudes,
        filtros=' | '.join(filtros_texto) if filtros_texto else 'Ninguno'
    )
    
    # Preparar respuesta HTTP
    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'solicitudes_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@login_required
def generar_reporte_solicitudes_excel(request):
    """Genera reporte Excel de solicitudes con filtros avanzados"""
    
    # Obtener todos los filtros (misma lógica que PDF)
    estado = request.GET.get('estado', '')
    programa_id = request.GET.get('programa', '')
    empresa_id = request.GET.get('empresa', '')
    nit = request.GET.get('nit', '')
    rango_fecha = request.GET.get('rango_fecha', '')
    
    # Consulta base
    solicitudes = Solicitud.objects.select_related(
        'empresa', 'programa', 'programa__area', 'instructor_asignado'
    ).all()
    
    # Aplicar filtros
    if estado:
        solicitudes = solicitudes.filter(estado=estado)
    
    if programa_id:
        solicitudes = solicitudes.filter(programa_id=programa_id)
    
    if empresa_id:
        solicitudes = solicitudes.filter(empresa_id=empresa_id)
    
    if nit:
        nit_limpio = nit.strip()
        solicitudes = solicitudes.filter(empresa__nit__icontains=nit_limpio)
    
    # Filtro de Rango de Fecha
    if rango_fecha:
        fecha_inicio, fecha_fin = calcular_rango_fechas(rango_fecha)
        
        if fecha_inicio and fecha_fin:
            fecha_inicio_dt = timezone.make_aware(
                datetime.combine(fecha_inicio, datetime.min.time())
            )
            fecha_fin_dt = timezone.make_aware(
                datetime.combine(fecha_fin, datetime.max.time())
            )
            
            solicitudes = solicitudes.filter(
                fecha_recepcion__gte=fecha_inicio_dt,
                fecha_recepcion__lte=fecha_fin_dt
            )
    
    # Ordenar resultados
    solicitudes = solicitudes.order_by('-fecha_recepcion')
    
    # Generar Excel
    generator = ExcelReportGenerator()
    buffer = generator.generate_solicitudes_report(solicitudes)
    
    buffer.seek(0)
    filename = f'solicitudes_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


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
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ============================================================================
# REPORTES INDIVIDUALES - PROGRAMAS
# ============================================================================

@login_required
def generar_reporte_programas_pdf(request):
    """Genera reporte PDF de programas de formación"""
    programas = Programa.objects.select_related('area').filter(activo=True).order_by('nombre')
    
    generator = PDFReportGenerator()
    buffer = generator.generate_programas_report(programas)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'programas_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@login_required
def generar_reporte_programas_excel(request):
    """Genera reporte Excel de programas de formación"""
    programas = Programa.objects.select_related('area').filter(activo=True).order_by('nombre')
    
    generator = ExcelReportGenerator()
    buffer = generator.generate_programas_report(programas)
    
    buffer.seek(0)
    filename = f'programas_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ============================================================================
# REPORTES INDIVIDUALES - INSTRUCTORES
# ============================================================================

@login_required
def generar_reporte_instructores_pdf(request):
    """Genera reporte PDF de instructores"""
    instructores = Instructor.objects.prefetch_related('especialidad').all().order_by('nombre')
    
    generator = PDFReportGenerator()
    
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.units import inch
    import io
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=80,
        bottomMargin=50,
        title="Directorio de Instructores - SENA",
        author="SENA - Sistema de Gestión",
        subject="Instructores Activos"
    )
    
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
    
    generator = ExcelReportGenerator()
    buffer = generator.generate_instructores_report(instructores)
    
    buffer.seek(0)
    filename = f'instructores_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


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
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )