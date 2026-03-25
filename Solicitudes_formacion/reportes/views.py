"""
Vistas del módulo de reportes
Sistema de Gestión de Solicitudes SENA
"""

import time
from datetime import datetime, timedelta, date
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, FileResponse
from django.utils import timezone

from solicitudes.models import Solicitud
from empresas.models import Empresa
from programas.models import Programa
from instructores.models import Instructor

from .generators import PDFReportGenerator, ExcelReportGenerator
from django.core.paginator import Paginator
from django.db.models import Count, Q
from core.management.decorators import puede_ver_requerido


# ============================================================================
# FUNCIÓN AUXILIAR PARA REGISTRAR REPORTES
# ============================================================================

def registrar_reporte(request, tipo, formato, filtros_dict, total_registros, tiempo=0):
    """Función auxiliar para registrar reportes en el historial"""
    from .models import Reporte

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')

    Reporte.objects.create(
        tipo=tipo,
        formato=formato,
        generado_por=request.user,
        filtros_aplicados=filtros_dict,
        total_registros=total_registros,
        tiempo_generacion=tiempo,
        ip_address=ip
    )


# ============================================================================
# FUNCIÓN AUXILIAR PARA RANGOS DE FECHA PREDEFINIDOS
# ============================================================================

def calcular_rango_fechas(rango_fecha):
    """
    Calcula las fechas de inicio y fin según el rango predefinido seleccionado.
    Retorna (fecha_inicio, fecha_fin) o (None, None) si no hay rango.
    """
    if not rango_fecha:
        return None, None

    hoy = timezone.now().date()

    rangos = {
        'hoy':            (hoy, hoy),
        'ayer':           (hoy - timedelta(days=1), hoy - timedelta(days=1)),
        'esta_semana':    (hoy - timedelta(days=hoy.weekday()), hoy),
        'semana_pasada':  (
            hoy - timedelta(days=hoy.weekday() + 7),
            hoy - timedelta(days=hoy.weekday() + 1),
        ),
        'este_mes':       (hoy.replace(day=1), hoy),
        'ultimos_7_dias': (hoy - timedelta(days=7), hoy),
        'ultimos_30_dias':(hoy - timedelta(days=30), hoy),
        'este_año':       (hoy.replace(month=1, day=1), hoy),
    }

    if rango_fecha == 'mes_pasado':
        primer_dia_mes = hoy.replace(day=1)
        ultimo_dia_mes_pasado = primer_dia_mes - timedelta(days=1)
        return ultimo_dia_mes_pasado.replace(day=1), ultimo_dia_mes_pasado

    return rangos.get(rango_fecha, (None, None))


# ============================================================================
# FUNCIÓN AUXILIAR PARA OBTENER Y VALIDAR FECHAS EXACTAS DEL REQUEST
# ============================================================================

def obtener_fechas_exactas(request):
    """
    Lee fecha_inicio y fecha_fin del request GET.
    Retorna (fecha_inicio: date | None, fecha_fin: date | None, errores: list).
    Las fechas exactas tienen PRIORIDAD sobre rango_fecha (igual que en el JS).
    """
    errores = []
    fecha_inicio = None
    fecha_fin = None

    raw_inicio = request.GET.get('fecha_inicio', '').strip()
    raw_fin    = request.GET.get('fecha_fin', '').strip()

    if raw_inicio:
        try:
            fecha_inicio = datetime.strptime(raw_inicio, '%Y-%m-%d').date()
        except ValueError:
            errores.append(f"Formato de fecha inicio inválido: '{raw_inicio}'. Use YYYY-MM-DD.")

    if raw_fin:
        try:
            fecha_fin = datetime.strptime(raw_fin, '%Y-%m-%d').date()
        except ValueError:
            errores.append(f"Formato de fecha fin inválido: '{raw_fin}'. Use YYYY-MM-DD.")

    # Validar coherencia
    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        errores.append("La fecha fin no puede ser anterior a la fecha inicio.")
        fecha_fin = None   # descartamos el fin incoherente

    return fecha_inicio, fecha_fin, errores


# ============================================================================
# FUNCIÓN AUXILIAR: APLICA FILTRO DE FECHA A UN QUERYSET
# ============================================================================

def aplicar_filtro_fecha(queryset, campo_fecha, fecha_inicio, fecha_fin):
    """
    Filtra el queryset por el campo indicado usando un rango aware.
    Ambos parámetros son objetos `date` (pueden ser None).
    """
    if fecha_inicio:
        dt_inicio = timezone.make_aware(datetime.combine(fecha_inicio, datetime.min.time()))
        queryset = queryset.filter(**{f'{campo_fecha}__gte': dt_inicio})

    if fecha_fin:
        dt_fin = timezone.make_aware(datetime.combine(fecha_fin, datetime.max.time()))
        queryset = queryset.filter(**{f'{campo_fecha}__lte': dt_fin})

    return queryset


# ============================================================================
# PANEL PRINCIPAL DE REPORTES
# ============================================================================

@login_required
def panel_reportes(request):
    """Panel principal de reportes con estadísticas y filtros"""

    context = {
        # Totales generales
        'total_solicitudes':     Solicitud.objects.count(),
        'total_empresas':        Empresa.objects.count(),
        'total_programas':       Programa.objects.filter(activo=True).count(),
        'total_instructores':    Instructor.objects.filter(activo=True).count(),

        # Solicitudes por estado
        'solicitudes_recibidas':   Solicitud.objects.filter(estado='RECIBIDA').count(),
        'solicitudes_respondidas': Solicitud.objects.filter(estado='RESPONDIDA').count(),
        'solicitudes_atendidas':   Solicitud.objects.filter(estado='ATENDIDA').count(),
        'solicitudes_finalizadas': Solicitud.objects.filter(estado='FINALIZADA').count(),

        # Datos para los selectores del formulario de filtros
        'programas':    Programa.objects.filter(activo=True).order_by('nombre'),
        'empresas':     Empresa.objects.all().order_by('nombre'),
        'instructores': Instructor.objects.filter(activo=True).order_by('nombre'),
        'estados':      Solicitud.ESTADO_CHOICES,

        # ── Valores actuales de los filtros (para re-pintar el form) ──
        'estado_filter':      request.GET.get('estado', ''),
        'programa_filter':    request.GET.get('programa', ''),
        'empresa_filter':     request.GET.get('empresa', ''),
        'nit_filter':         request.GET.get('nit', ''),
        'instructor_filter':  request.GET.get('instructor', ''),
        'rango_fecha':        request.GET.get('rango_fecha', ''),

        # Fechas exactas  (nuevas)
        'fecha_inicio_filter': request.GET.get('fecha_inicio', ''),
        'fecha_fin_filter':    request.GET.get('fecha_fin', ''),
    }

    return render(request, 'reportes/panel_reportes.html', context)


# ============================================================================
# FUNCIÓN INTERNA: CONSTRUIR QUERYSET DE SOLICITUDES CON TODOS LOS FILTROS
# ============================================================================

def _filtrar_solicitudes(request):
    """
    Lee todos los parámetros GET y devuelve:
      (queryset_filtrado, filtros_texto: list, filtros_dict: dict)

    Lógica de prioridad de fechas (idéntica al JS del template):
      1. Si hay fecha_inicio o fecha_fin  → se usan esas fechas exactas.
      2. Si no hay fechas exactas y hay rango_fecha → se usa el período predefinido.
    """
    estado       = request.GET.get('estado', '')
    programa_id  = request.GET.get('programa', '')
    empresa_id   = request.GET.get('empresa', '')
    nit          = request.GET.get('nit', '').strip()
    instructor_id= request.GET.get('instructor', '')
    rango_fecha  = request.GET.get('rango_fecha', '')

    # Leer fechas exactas
    fecha_inicio_exacta, fecha_fin_exacta, _ = obtener_fechas_exactas(request)
    usar_fechas_exactas = bool(fecha_inicio_exacta or fecha_fin_exacta)

    # Queryset base optimizado
    solicitudes = Solicitud.objects.select_related(
        'empresa', 'programa', 'programa__area', 'instructor_asignado'
    ).all()

    filtros_texto = []

    # ── Estado ──────────────────────────────────────────────────────────────
    if estado:
        solicitudes = solicitudes.filter(estado=estado)
        nombre_estado = dict(Solicitud.ESTADO_CHOICES).get(estado, estado)
        filtros_texto.append(f"Estado: {nombre_estado}")

    # ── Programa ─────────────────────────────────────────────────────────────
    if programa_id:
        solicitudes = solicitudes.filter(programa_id=programa_id)
        try:
            p = Programa.objects.get(id=programa_id)
            filtros_texto.append(f"Programa: {p.nombre}")
        except Programa.DoesNotExist:
            pass

    # ── Empresa ──────────────────────────────────────────────────────────────
    if empresa_id:
        solicitudes = solicitudes.filter(empresa_id=empresa_id)
        try:
            e = Empresa.objects.get(id=empresa_id)
            filtros_texto.append(f"Empresa: {e.nombre}")
        except Empresa.DoesNotExist:
            pass

    # ── NIT ──────────────────────────────────────────────────────────────────
    if nit:
        solicitudes = solicitudes.filter(empresa__nit__icontains=nit)
        filtros_texto.append(f"NIT: {nit}")

    # ── Instructor ───────────────────────────────────────────────────────────
    if instructor_id:
        solicitudes = solicitudes.filter(instructor_asignado_id=instructor_id)
        try:
            i = Instructor.objects.get(id=instructor_id)
            filtros_texto.append(f"Instructor: {i.nombre}")
        except Instructor.DoesNotExist:
            pass

    # ── Fechas ───────────────────────────────────────────────────────────────
    if usar_fechas_exactas:
        # PRIORIDAD: rango exacto definido por el usuario
        solicitudes = aplicar_filtro_fecha(
            solicitudes, 'fecha_recepcion',
            fecha_inicio_exacta, fecha_fin_exacta
        )

        partes = []
        if fecha_inicio_exacta:
            partes.append(f"desde {fecha_inicio_exacta.strftime('%d/%m/%Y')}")
        if fecha_fin_exacta:
            partes.append(f"hasta {fecha_fin_exacta.strftime('%d/%m/%Y')}")
        filtros_texto.append(f"Fechas: {' '.join(partes)}")

    elif rango_fecha:
        # Período predefinido solo si NO hay fechas exactas
        fecha_inicio_pred, fecha_fin_pred = calcular_rango_fechas(rango_fecha)

        if fecha_inicio_pred and fecha_fin_pred:
            solicitudes = aplicar_filtro_fecha(
                solicitudes, 'fecha_recepcion',
                fecha_inicio_pred, fecha_fin_pred
            )

            etiquetas = {
                'hoy': 'Hoy',
                'ayer': 'Ayer',
                'esta_semana': 'Esta semana',
                'semana_pasada': 'Semana pasada',
                'este_mes': 'Este mes',
                'mes_pasado': 'Mes pasado',
                'ultimos_7_dias': 'Últimos 7 días',
                'ultimos_30_dias': 'Últimos 30 días',
                'este_año': 'Este año',
            }
            filtros_texto.append(f"Período: {etiquetas.get(rango_fecha, rango_fecha)}")

    # ── Diccionario para historial ────────────────────────────────────────────
    filtros_dict = {
        'estado':         estado or None,
        'programa_id':    programa_id or None,
        'empresa_id':     empresa_id or None,
        'nit':            nit or None,
        'instructor_id':  instructor_id or None,
        'rango_fecha':    rango_fecha or None,
        # Fechas exactas (nuevas)
        'fecha_inicio':   str(fecha_inicio_exacta) if fecha_inicio_exacta else None,
        'fecha_fin':      str(fecha_fin_exacta)    if fecha_fin_exacta    else None,
    }

    return solicitudes.order_by('-fecha_recepcion'), filtros_texto, filtros_dict


# ============================================================================
# REPORTES INDIVIDUALES - SOLICITUDES
# ============================================================================

@login_required
def generar_reporte_solicitudes_pdf(request):
    """Genera reporte PDF de solicitudes con filtros avanzados (incluye rango exacto de fechas)"""

    tiempo_inicio = time.time()

    solicitudes, filtros_texto, filtros_dict = _filtrar_solicitudes(request)

    generator = PDFReportGenerator()
    buffer = generator.generate_solicitudes_report(
        solicitudes,
        filtros=' | '.join(filtros_texto) if filtros_texto else 'Ninguno'
    )

    tiempo_total = time.time() - tiempo_inicio
    registrar_reporte(
        request=request,
        tipo='solicitudes',
        formato='pdf',
        filtros_dict=filtros_dict,
        total_registros=solicitudes.count(),
        tiempo=tiempo_total
    )

    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'solicitudes_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def generar_reporte_solicitudes_excel(request):
    """Genera reporte Excel de solicitudes con filtros avanzados (incluye rango exacto de fechas)"""

    tiempo_inicio = time.time()

    solicitudes, _filtros_texto, filtros_dict = _filtrar_solicitudes(request)

    generator = ExcelReportGenerator()
    buffer = generator.generate_solicitudes_report(
        solicitudes,
        filtros=' | '.join(_filtros_texto) if _filtros_texto else None
    )

    tiempo_total = time.time() - tiempo_inicio
    registrar_reporte(
        request=request,
        tipo='solicitudes',
        formato='excel',
        filtros_dict=filtros_dict,
        total_registros=solicitudes.count(),
        tiempo=tiempo_total
    )

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

    tiempo_inicio = time.time()
    empresas = Empresa.objects.all().order_by('nombre')

    generator = PDFReportGenerator()
    buffer = generator.generate_empresas_report(empresas)

    tiempo_total = time.time() - tiempo_inicio
    registrar_reporte(
        request=request, tipo='empresas', formato='pdf',
        filtros_dict={}, total_registros=empresas.count(), tiempo=tiempo_total
    )

    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'empresas_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def generar_reporte_empresas_excel(request):
    """Genera reporte Excel de empresas"""

    tiempo_inicio = time.time()
    empresas = Empresa.objects.all().order_by('nombre')

    generator = ExcelReportGenerator()
    buffer = generator.generate_empresas_report(empresas)

    tiempo_total = time.time() - tiempo_inicio
    registrar_reporte(
        request=request, tipo='empresas', formato='excel',
        filtros_dict={}, total_registros=empresas.count(), tiempo=tiempo_total
    )

    buffer.seek(0)
    filename = f'empresas_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(
        buffer, as_attachment=True, filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ============================================================================
# REPORTES INDIVIDUALES - PROGRAMAS
# ============================================================================

@login_required
def generar_reporte_programas_pdf(request):
    """Genera reporte PDF de programas de formación"""

    tiempo_inicio = time.time()
    programas = Programa.objects.select_related('area').filter(activo=True).order_by('nombre')

    generator = PDFReportGenerator()
    buffer = generator.generate_programas_report(programas)

    tiempo_total = time.time() - tiempo_inicio
    registrar_reporte(
        request=request, tipo='programas', formato='pdf',
        filtros_dict={}, total_registros=programas.count(), tiempo=tiempo_total
    )

    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'programas_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def generar_reporte_programas_excel(request):
    """Genera reporte Excel de programas de formación"""

    tiempo_inicio = time.time()
    programas = Programa.objects.select_related('area').filter(activo=True).order_by('nombre')

    generator = ExcelReportGenerator()
    buffer = generator.generate_programas_report(programas)

    tiempo_total = time.time() - tiempo_inicio
    registrar_reporte(
        request=request, tipo='programas', formato='excel',
        filtros_dict={}, total_registros=programas.count(), tiempo=tiempo_total
    )

    buffer.seek(0)
    filename = f'programas_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(
        buffer, as_attachment=True, filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ============================================================================
# REPORTES INDIVIDUALES - INSTRUCTORES
# ============================================================================

@login_required
def generar_reporte_instructores_pdf(request):
    """Genera reporte PDF de instructores"""

    tiempo_inicio = time.time()

    instructores = Instructor.objects.prefetch_related('especialidad').all().order_by('nombre')

    generator = PDFReportGenerator()

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.units import inch
    import io

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=80, bottomMargin=50,
        title="Directorio de Instructores - SENA",
        author="SENA - Sistema de Gestión",
        subject="Instructores Activos"
    )

    elements = []

    title = Paragraph("DIRECTORIO DE INSTRUCTORES", generator.styles['CustomTitle'])
    elements.append(title)
    elements.append(Spacer(1, 0.3 * inch))

    total   = instructores.count()
    activos = instructores.filter(activo=True).count()
    elements.append(Paragraph(
        f"<b>Total de instructores:</b> {total} (Activos: {activos})",
        generator.styles['Normal']
    ))
    elements.append(Spacer(1, 0.3 * inch))

    data = [['Instructor', 'Correo', 'Teléfono', 'Especialidades', 'Estado', 'Solicitudes']]
    for inst in instructores[:50]:
        data.append([
            inst.nombre[:30],
            inst.correo[:30],
            inst.telefono[:15] if inst.telefono else 'N/A',
            str(inst.especialidad.count()),
            'Activo' if inst.activo else 'Inactivo',
            str(inst.solicitud_set.count())
        ])

    table = Table(data, colWidths=[
        1.5*inch, 1.5*inch, 1*inch, 1*inch, 0.8*inch, 0.9*inch
    ])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME',   (0, 0), (-1,  0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1,  0), 9),
        ('FONTSIZE',   (0, 1), (-1, -1), 7),
        ('GRID',       (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
    ]))
    elements.append(table)

    doc.build(
        elements,
        onFirstPage=generator.add_header_footer,
        onLaterPages=generator.add_header_footer
    )
    buffer.seek(0)

    tiempo_total = time.time() - tiempo_inicio
    registrar_reporte(
        request=request, tipo='instructores', formato='pdf',
        filtros_dict={}, total_registros=instructores.count(), tiempo=tiempo_total
    )

    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'instructores_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def generar_reporte_instructores_excel(request):
    """Genera reporte Excel de instructores"""

    tiempo_inicio = time.time()
    instructores = Instructor.objects.prefetch_related('especialidad').all().order_by('nombre')

    generator = ExcelReportGenerator()
    buffer = generator.generate_instructores_report(instructores)

    tiempo_total = time.time() - tiempo_inicio
    registrar_reporte(
        request=request, tipo='instructores', formato='excel',
        filtros_dict={}, total_registros=instructores.count(), tiempo=tiempo_total
    )

    buffer.seek(0)
    filename = f'instructores_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(
        buffer, as_attachment=True, filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ============================================================================
# REPORTES CONSOLIDADOS - TODO EL SISTEMA
# ============================================================================

@login_required
def generar_reporte_consolidado_pdf(request):
    """Genera reporte consolidado PDF de todo el sistema"""

    tiempo_inicio = time.time()

    solicitudes  = Solicitud.objects.select_related(
        'empresa', 'programa', 'programa__area', 'instructor_asignado'
    ).all()
    empresas     = Empresa.objects.all()
    programas    = Programa.objects.select_related('area').all()
    instructores = Instructor.objects.prefetch_related('especialidad').all()

    generator = PDFReportGenerator()
    buffer = generator.generate_consolidated_report(
        solicitudes, empresas, programas, instructores
    )

    tiempo_total = time.time() - tiempo_inicio
    total_registros = (
        solicitudes.count() + empresas.count() +
        programas.count()  + instructores.count()
    )
    registrar_reporte(
        request=request, tipo='consolidado', formato='pdf',
        filtros_dict={}, total_registros=total_registros, tiempo=tiempo_total
    )

    response = HttpResponse(buffer, content_type='application/pdf')
    filename = f'reporte_consolidado_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def generar_reporte_consolidado_excel(request):
    """Genera reporte consolidado Excel de todo el sistema (5 hojas)"""

    tiempo_inicio = time.time()

    solicitudes  = Solicitud.objects.select_related(
        'empresa', 'programa', 'programa__area', 'instructor_asignado'
    ).all()
    empresas     = Empresa.objects.all()
    programas    = Programa.objects.select_related('area').all()
    instructores = Instructor.objects.prefetch_related('especialidad').all()

    generator = ExcelReportGenerator()
    buffer = generator.generate_consolidated_report(
        solicitudes, empresas, programas, instructores
    )

    tiempo_total = time.time() - tiempo_inicio
    total_registros = (
        solicitudes.count() + empresas.count() +
        programas.count()  + instructores.count()
    )
    registrar_reporte(
        request=request, tipo='consolidado', formato='excel',
        filtros_dict={}, total_registros=total_registros, tiempo=tiempo_total
    )

    buffer.seek(0)
    filename = f'reporte_consolidado_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    return FileResponse(
        buffer, as_attachment=True, filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


# ============================================================================
# HISTORIAL DE REPORTES
# ============================================================================

@puede_ver_requerido
def historial_reportes(request):
    """Vista para mostrar el historial de generación de reportes con paginación y filtros"""
    from .models import Reporte

    user = request.user
    es_administrador = user.is_superuser or user.groups.filter(name='Administrador')
    es_coordinador   = user.groups.filter(name='Coordinador').exists()

    logs = Reporte.objects.select_related('generado_por').order_by('-fecha_generacion')

    # Asistente: solo ve sus propios reportes
    if not es_administrador and not es_coordinador:
        logs = logs.filter(generado_por=user)

    # ── Filtros ──────────────────────────────────────────────────────────────
    tipo_filter    = request.GET.get('tipo', '')
    formato_filter = request.GET.get('formato', '')
    usuario_filter = request.GET.get('usuario', '')
    rango_filter   = request.GET.get('rango', '')
    search         = request.GET.get('search', '')

    if tipo_filter:
        logs = logs.filter(tipo=tipo_filter)

    if formato_filter:
        logs = logs.filter(formato=formato_filter)

    if usuario_filter and (es_administrador or es_coordinador):
        logs = logs.filter(generado_por_id=usuario_filter)

    if rango_filter:
        hoy = timezone.now().date()
        if rango_filter == 'hoy':
            logs = logs.filter(fecha_generacion__date=hoy)
        elif rango_filter == 'ayer':
            logs = logs.filter(fecha_generacion__date=hoy - timedelta(days=1))
        elif rango_filter == 'esta_semana':
            inicio_semana = hoy - timedelta(days=hoy.weekday())
            logs = logs.filter(fecha_generacion__date__gte=inicio_semana)
        elif rango_filter == 'este_mes':
            logs = logs.filter(
                fecha_generacion__year=hoy.year,
                fecha_generacion__month=hoy.month
            )
        elif rango_filter == 'ultimos_30':
            logs = logs.filter(fecha_generacion__date__gte=hoy - timedelta(days=30))

    if search:
        logs = logs.filter(
            Q(generado_por__username__icontains=search)   |
            Q(generado_por__first_name__icontains=search) |
            Q(generado_por__last_name__icontains=search)
        )

    # ── Estadísticas ─────────────────────────────────────────────────────────
    stats = {
        'total':       logs.count(),
        'por_tipo':    logs.values('tipo').annotate(count=Count('id')),
        'por_formato': logs.values('formato').annotate(count=Count('id')),
    }

    # ── Paginación ───────────────────────────────────────────────────────────
    paginator  = Paginator(logs, 25)
    page_obj   = paginator.get_page(request.GET.get('page', 1))

    # ── Usuarios disponibles (solo para admin/coordinador) ───────────────────
    usuarios_disponibles = []
    if es_administrador or es_coordinador:
        usuarios_disponibles = Reporte.objects.values(
            'generado_por__id',
            'generado_por__username',
            'generado_por__first_name',
            'generado_por__last_name'
        ).distinct().order_by('generado_por__username')

    context = {
        'page_obj': page_obj,
        'logs':     page_obj.object_list,
        'stats':    stats,
        'es_administrador': es_administrador,
        'es_coordinador':   es_coordinador,

        # Filtros aplicados
        'tipo_filter':    tipo_filter,
        'formato_filter': formato_filter,
        'usuario_filter': usuario_filter,
        'rango_filter':   rango_filter,
        'search':         search,

        # Datos para selectores
        'usuarios_disponibles': usuarios_disponibles,
        'tipos_reporte':        Reporte.TIPO_CHOICES,
        'formatos_reporte':     Reporte.FORMATO_CHOICES,
    }

    return render(request, 'reportes/historial_reportes.html', context)