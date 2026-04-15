"""
Vistas del módulo de reportes
Sistema de Gestión de Solicitudes SENA
"""

import time
from datetime import datetime, timedelta

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, FileResponse
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Count, Q

from solicitudes.models import Solicitud
from empresas.models import Empresa
from programas.models import Programa
from instructores.models import Instructor

from .generators import PDFReportGenerator, ExcelReportGenerator
from core.management.decorators import puede_ver_requerido


# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────

CONTENT_TYPES = {
    'pdf':   'application/pdf',
    'excel': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

EXTENSIONES = {
    'pdf':   'pdf',
    'excel': 'xlsx',
}

ETIQUETAS_RANGO = {
    'hoy':            'Hoy',
    'ayer':           'Ayer',
    'esta_semana':    'Esta semana',
    'semana_pasada':  'Semana pasada',
    'este_mes':       'Este mes',
    'mes_pasado':     'Mes pasado',
    'ultimos_7_dias': 'Últimos 7 días',
    'ultimos_30_dias':'Últimos 30 días',
    'este_año':       'Este año',
}


# ─────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────

def _get_ip(request):
    """Extrae la IP real del request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    return x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')


def registrar_reporte(request, tipo, formato, filtros_dict, total_registros, tiempo=0):
    """Registra el reporte generado en el historial de auditoría."""
    from .models import Reporte
    Reporte.objects.create(
        tipo=tipo,
        formato=formato,
        generado_por=request.user,
        filtros_aplicados=filtros_dict,
        total_registros=total_registros,
        tiempo_generacion=tiempo,
        ip_address=_get_ip(request),
    )


def calcular_rango_fechas(rango_fecha):
    """
    Calcula fechas de inicio y fin según el rango predefinido.
    Retorna (fecha_inicio, fecha_fin) o (None, None).
    """
    if not rango_fecha:
        return None, None

    hoy = timezone.now().date()

    if rango_fecha == 'mes_pasado':
        ultimo = hoy.replace(day=1) - timedelta(days=1)
        return ultimo.replace(day=1), ultimo

    rangos = {
        'hoy':            (hoy, hoy),
        'ayer':           (hoy - timedelta(days=1), hoy - timedelta(days=1)),
        'esta_semana':    (hoy - timedelta(days=hoy.weekday()), hoy),
        'semana_pasada':  (
            hoy - timedelta(days=hoy.weekday() + 7),
            hoy - timedelta(days=hoy.weekday() + 1),
        ),
        'este_mes':       (hoy.replace(day=1), hoy),
        'ultimos_7_dias': (hoy - timedelta(days=7),  hoy),
        'ultimos_30_dias':(hoy - timedelta(days=30), hoy),
        'este_año':       (hoy.replace(month=1, day=1), hoy),
    }
    return rangos.get(rango_fecha, (None, None))


def obtener_fechas_exactas(request):
    """
    Lee fecha_inicio y fecha_fin del request GET.
    Retorna (fecha_inicio, fecha_fin, errores).
    """
    errores      = []
    fecha_inicio = None
    fecha_fin    = None

    for campo, nombre in [('fecha_inicio', 'inicio'), ('fecha_fin', 'fin')]:
        raw = request.GET.get(campo, '').strip()
        if raw:
            try:
                valor = datetime.strptime(raw, '%Y-%m-%d').date()
                if nombre == 'inicio':
                    fecha_inicio = valor
                else:
                    fecha_fin = valor
            except ValueError:
                errores.append(f"Formato de fecha {nombre} inválido: '{raw}'. Use YYYY-MM-DD.")

    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        errores.append("La fecha fin no puede ser anterior a la fecha inicio.")
        fecha_fin = None

    return fecha_inicio, fecha_fin, errores


def aplicar_filtro_fecha(queryset, campo_fecha, fecha_inicio, fecha_fin):
    """Filtra el queryset por rango de fechas usando datetime aware."""
    if fecha_inicio:
        dt_inicio = timezone.make_aware(datetime.combine(fecha_inicio, datetime.min.time()))
        queryset  = queryset.filter(**{f'{campo_fecha}__gte': dt_inicio})
    if fecha_fin:
        dt_fin   = timezone.make_aware(datetime.combine(fecha_fin, datetime.max.time()))
        queryset = queryset.filter(**{f'{campo_fecha}__lte': dt_fin})
    return queryset


def _build_response(buffer, formato, nombre_base):
    """
    Construye el HttpResponse o FileResponse según el formato.
    Centraliza la construcción de respuestas de descarga.
    """
    extension    = EXTENSIONES[formato]
    content_type = CONTENT_TYPES[formato]
    filename     = f'{nombre_base}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.{extension}'

    if formato == 'pdf':
        response = HttpResponse(buffer, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type=content_type)


def _generar_reporte(request, tipo, formato, queryset_fn, generator_method_name,
                     nombre_base, filtros_dict=None, filtros_texto=None, extra_args=None):
    """
    Orquesta la generación de cualquier reporte:
    1. Mide tiempo
    2. Obtiene el queryset
    3. Llama al método del generador correcto
    4. Registra en historial
    5. Retorna la respuesta de descarga
    """
    tiempo_inicio = time.time()

    datos        = queryset_fn()
    generadores  = {'pdf': PDFReportGenerator, 'excel': ExcelReportGenerator}
    generator    = generadores[formato]()
    metodo       = getattr(generator, generator_method_name)

    args = extra_args or [datos]
    buffer = metodo(*args) if isinstance(args, list) and len(args) > 1 else metodo(datos)

    if filtros_texto:
        buffer = metodo(datos, filtros=' | '.join(filtros_texto) if filtros_texto else 'Ninguno')

    tiempo_total = time.time() - tiempo_inicio
    total = datos.count() if hasattr(datos, 'count') else sum(d.count() for d in datos)

    registrar_reporte(
        request=request, tipo=tipo, formato=formato,
        filtros_dict=filtros_dict or {}, total_registros=total, tiempo=tiempo_total,
    )
    return _build_response(buffer, formato, nombre_base)


def _filtrar_solicitudes(request):
    """
    Lee parámetros GET y retorna (queryset, filtros_texto, filtros_dict).
    """
    estado        = request.GET.get('estado', '')
    programa_id   = request.GET.get('programa', '')
    empresa_id    = request.GET.get('empresa', '')
    nit           = request.GET.get('nit', '').strip()
    instructor_id = request.GET.get('instructor', '')
    rango_fecha   = request.GET.get('rango_fecha', '')

    fecha_inicio_exacta, fecha_fin_exacta, _ = obtener_fechas_exactas(request)
    usar_fechas_exactas = bool(fecha_inicio_exacta or fecha_fin_exacta)

    solicitudes = Solicitud.objects.select_related(
        'empresa', 'programa', 'programa__area', 'instructor_asignado'
    ).all()

    filtros_texto = []

    # ── Filtros simples ───────────────────────
    filtros_simples = [
        (estado,        lambda qs: qs.filter(estado=estado),
         lambda: f"Estado: {dict(Solicitud.ESTADO_CHOICES).get(estado, estado)}"),
        (programa_id,   lambda qs: qs.filter(programa_id=programa_id),
         lambda: f"Programa: {Programa.objects.filter(id=programa_id).values_list('nombre', flat=True).first() or ''}"),
        (empresa_id,    lambda qs: qs.filter(empresa_id=empresa_id),
         lambda: f"Empresa: {Empresa.objects.filter(id=empresa_id).values_list('nombre', flat=True).first() or ''}"),
        (nit,           lambda qs: qs.filter(empresa__nit__icontains=nit),
         lambda: f"NIT: {nit}"),
        (instructor_id, lambda qs: qs.filter(instructor_asignado_id=instructor_id),
         lambda: f"Instructor: {Instructor.objects.filter(id=instructor_id).values_list('nombre', flat=True).first() or ''}"),
    ]

    for condicion, aplicar, etiqueta in filtros_simples:
        if condicion:
            solicitudes = aplicar(solicitudes)
            filtros_texto.append(etiqueta())

    # ── Filtros de fecha ──────────────────────
    if usar_fechas_exactas:
        solicitudes = aplicar_filtro_fecha(
            solicitudes, 'fecha_recepcion', fecha_inicio_exacta, fecha_fin_exacta
        )
        partes = []
        if fecha_inicio_exacta:
            partes.append(f"desde {fecha_inicio_exacta.strftime('%d/%m/%Y')}")
        if fecha_fin_exacta:
            partes.append(f"hasta {fecha_fin_exacta.strftime('%d/%m/%Y')}")
        filtros_texto.append(f"Fechas: {' '.join(partes)}")

    elif rango_fecha:
        fi, ff = calcular_rango_fechas(rango_fecha)
        if fi and ff:
            solicitudes = aplicar_filtro_fecha(solicitudes, 'fecha_recepcion', fi, ff)
            filtros_texto.append(f"Período: {ETIQUETAS_RANGO.get(rango_fecha, rango_fecha)}")

    filtros_dict = {
        'estado':        estado        or None,
        'programa_id':   programa_id   or None,
        'empresa_id':    empresa_id    or None,
        'nit':           nit           or None,
        'instructor_id': instructor_id or None,
        'rango_fecha':   rango_fecha   or None,
        'fecha_inicio':  str(fecha_inicio_exacta) if fecha_inicio_exacta else None,
        'fecha_fin':     str(fecha_fin_exacta)    if fecha_fin_exacta    else None,
    }

    return solicitudes.order_by('-fecha_recepcion'), filtros_texto, filtros_dict


# ─────────────────────────────────────────────
# Vistas
# ─────────────────────────────────────────────

@login_required
def panel_reportes(request):
    """Panel principal de reportes con estadísticas y filtros."""
    context = {
        'total_solicitudes':       Solicitud.objects.count(),
        'total_empresas':          Empresa.objects.count(),
        'total_programas':         Programa.objects.filter(activo=True).count(),
        'total_instructores':      Instructor.objects.filter(activo=True).count(),
        'solicitudes_recibidas':   Solicitud.objects.filter(estado='RECIBIDA').count(),
        'solicitudes_respondidas': Solicitud.objects.filter(estado='RESPONDIDA').count(),
        'solicitudes_atendidas':   Solicitud.objects.filter(estado='ATENDIDA').count(),
        'solicitudes_finalizadas': Solicitud.objects.filter(estado='FINALIZADA').count(),
        'programas':               Programa.objects.filter(activo=True).order_by('nombre'),
        'empresas':                Empresa.objects.all().order_by('nombre'),
        'instructores':            Instructor.objects.filter(activo=True).order_by('nombre'),
        'estados':                 Solicitud.ESTADO_CHOICES,
        'estado_filter':           request.GET.get('estado', ''),
        'programa_filter':         request.GET.get('programa', ''),
        'empresa_filter':          request.GET.get('empresa', ''),
        'nit_filter':              request.GET.get('nit', ''),
        'instructor_filter':       request.GET.get('instructor', ''),
        'rango_fecha':             request.GET.get('rango_fecha', ''),
        'fecha_inicio_filter':     request.GET.get('fecha_inicio', ''),
        'fecha_fin_filter':        request.GET.get('fecha_fin', ''),
    }
    return render(request, 'reportes/panel_reportes.html', context)


@login_required
def generar_reporte_solicitudes_pdf(request):
    """Genera reporte PDF de solicitudes con filtros avanzados."""
    tiempo_inicio                         = time.time()
    solicitudes, filtros_texto, filtros_dict = _filtrar_solicitudes(request)
    generator = PDFReportGenerator()
    buffer    = generator.generate_solicitudes_report(
        solicitudes,
        filtros=' | '.join(filtros_texto) if filtros_texto else 'Ninguno',
    )
    registrar_reporte(request, 'solicitudes', 'pdf', filtros_dict,
                      solicitudes.count(), time.time() - tiempo_inicio)
    return _build_response(buffer, 'pdf', 'solicitudes')


@login_required
def generar_reporte_solicitudes_excel(request):
    """Genera reporte Excel de solicitudes con filtros avanzados."""
    tiempo_inicio                         = time.time()
    solicitudes, filtros_texto, filtros_dict = _filtrar_solicitudes(request)
    generator = ExcelReportGenerator()
    buffer    = generator.generate_solicitudes_report(
        solicitudes,
        filtros=' | '.join(filtros_texto) if filtros_texto else None,
    )
    registrar_reporte(request, 'solicitudes', 'excel', filtros_dict,
                      solicitudes.count(), time.time() - tiempo_inicio)
    return _build_response(buffer, 'excel', 'solicitudes')


@login_required
def generar_reporte_empresas_pdf(request):
    """Genera reporte PDF de empresas."""
    tiempo_inicio = time.time()
    empresas      = Empresa.objects.all().order_by('nombre')
    buffer        = PDFReportGenerator().generate_empresas_report(empresas)
    registrar_reporte(request, 'empresas', 'pdf', {}, empresas.count(), time.time() - tiempo_inicio)
    return _build_response(buffer, 'pdf', 'empresas')


@login_required
def generar_reporte_empresas_excel(request):
    """Genera reporte Excel de empresas."""
    tiempo_inicio = time.time()
    empresas      = Empresa.objects.all().order_by('nombre')
    buffer        = ExcelReportGenerator().generate_empresas_report(empresas)
    registrar_reporte(request, 'empresas', 'excel', {}, empresas.count(), time.time() - tiempo_inicio)
    return _build_response(buffer, 'excel', 'empresas')


@login_required
def generar_reporte_programas_pdf(request):
    """Genera reporte PDF de programas de formación."""
    tiempo_inicio = time.time()
    programas     = Programa.objects.select_related('area').filter(activo=True).order_by('nombre')
    buffer        = PDFReportGenerator().generate_programas_report(programas)
    registrar_reporte(request, 'programas', 'pdf', {}, programas.count(), time.time() - tiempo_inicio)
    return _build_response(buffer, 'pdf', 'programas')


@login_required
def generar_reporte_programas_excel(request):
    """Genera reporte Excel de programas de formación."""
    tiempo_inicio = time.time()
    programas     = Programa.objects.select_related('area').filter(activo=True).order_by('nombre')
    buffer        = ExcelReportGenerator().generate_programas_report(programas)
    registrar_reporte(request, 'programas', 'excel', {}, programas.count(), time.time() - tiempo_inicio)
    return _build_response(buffer, 'excel', 'programas')


@login_required
def generar_reporte_instructores_pdf(request):
    """Genera reporte PDF de instructores con columna Disponibilidad."""
    tiempo_inicio = time.time()
    instructores  = Instructor.objects.prefetch_related('especialidad').all().order_by('nombre')
    buffer        = PDFReportGenerator().generate_instructores_report(instructores)
    registrar_reporte(request, 'instructores', 'pdf', {}, instructores.count(), time.time() - tiempo_inicio)
    return _build_response(buffer, 'pdf', 'instructores')


@login_required
def generar_reporte_instructores_excel(request):
    """Genera reporte Excel de instructores con columna Disponibilidad."""
    tiempo_inicio = time.time()
    instructores  = Instructor.objects.prefetch_related('especialidad').all().order_by('nombre')
    buffer        = ExcelReportGenerator().generate_instructores_report(instructores)
    registrar_reporte(request, 'instructores', 'excel', {}, instructores.count(), time.time() - tiempo_inicio)
    return _build_response(buffer, 'excel', 'instructores')


@login_required
def generar_reporte_consolidado_pdf(request):
    """Genera reporte consolidado PDF de todo el sistema."""
    tiempo_inicio = time.time()
    solicitudes   = Solicitud.objects.select_related('empresa', 'programa', 'programa__area', 'instructor_asignado').all()
    empresas      = Empresa.objects.all()
    programas     = Programa.objects.select_related('area').all()
    instructores  = Instructor.objects.prefetch_related('especialidad').all()
    buffer        = PDFReportGenerator().generate_consolidated_report(solicitudes, empresas, programas, instructores)
    total         = solicitudes.count() + empresas.count() + programas.count() + instructores.count()
    registrar_reporte(request, 'consolidado', 'pdf', {}, total, time.time() - tiempo_inicio)
    return _build_response(buffer, 'pdf', 'reporte_consolidado')


@login_required
def generar_reporte_consolidado_excel(request):
    """Genera reporte consolidado Excel de todo el sistema (5 hojas)."""
    tiempo_inicio = time.time()
    solicitudes   = Solicitud.objects.select_related('empresa', 'programa', 'programa__area', 'instructor_asignado').all()
    empresas      = Empresa.objects.all()
    programas     = Programa.objects.select_related('area').all()
    instructores  = Instructor.objects.prefetch_related('especialidad').all()
    buffer        = ExcelReportGenerator().generate_consolidated_report(solicitudes, empresas, programas, instructores)
    total         = solicitudes.count() + empresas.count() + programas.count() + instructores.count()
    registrar_reporte(request, 'consolidado', 'excel', {}, total, time.time() - tiempo_inicio)
    return _build_response(buffer, 'excel', 'reporte_consolidado')


@puede_ver_requerido
def historial_reportes(request):
    """Historial de generación de reportes con paginación y filtros."""
    from .models import Reporte

    user             = request.user
    es_administrador = user.is_superuser or user.groups.filter(name='Administrador')
    es_coordinador   = user.groups.filter(name='Coordinador').exists()

    logs = Reporte.objects.select_related('generado_por').order_by('-fecha_generacion')

    if not es_administrador and not es_coordinador:
        logs = logs.filter(generado_por=user)

    tipo_filter    = request.GET.get('tipo', '')
    formato_filter = request.GET.get('formato', '')
    usuario_filter = request.GET.get('usuario', '')
    rango_filter   = request.GET.get('rango', '')
    search         = request.GET.get('search', '')

    # ── Filtros del historial ─────────────────
    hoy = timezone.now().date()

    filtros_historial = [
        (tipo_filter,
         lambda qs: qs.filter(tipo=tipo_filter)),
        (formato_filter,
         lambda qs: qs.filter(formato=formato_filter)),
        (usuario_filter and (es_administrador or es_coordinador),
         lambda qs: qs.filter(generado_por_id=usuario_filter)),
        (search,
         lambda qs: qs.filter(
             Q(generado_por__username__icontains=search)   |
             Q(generado_por__first_name__icontains=search) |
             Q(generado_por__last_name__icontains=search)
         )),
    ]

    for condicion, aplicar in filtros_historial:
        if condicion:
            logs = aplicar(logs)

    # ── Filtro de rango ───────────────────────
    rangos_historial = {
        'hoy':         lambda qs: qs.filter(fecha_generacion__date=hoy),
        'ayer':        lambda qs: qs.filter(fecha_generacion__date=hoy - timedelta(days=1)),
        'esta_semana': lambda qs: qs.filter(fecha_generacion__date__gte=hoy - timedelta(days=hoy.weekday())),
        'este_mes':    lambda qs: qs.filter(fecha_generacion__year=hoy.year, fecha_generacion__month=hoy.month),
        'ultimos_30':  lambda qs: qs.filter(fecha_generacion__date__gte=hoy - timedelta(days=30)),
    }

    if rango_filter in rangos_historial:
        logs = rangos_historial[rango_filter](logs)

    page_obj = Paginator(logs, 25).get_page(request.GET.get('page', 1))

    usuarios_disponibles = []
    if es_administrador or es_coordinador:
        usuarios_disponibles = Reporte.objects.values(
            'generado_por__id', 'generado_por__username',
            'generado_por__first_name', 'generado_por__last_name',
        ).distinct().order_by('generado_por__username')

    context = {
        'page_obj':              page_obj,
        'logs':                  page_obj.object_list,
        'stats': {
            'total':    logs.count(),
            'por_tipo': list(logs.values('tipo').annotate(count=Count('id')).order_by('tipo')),
        },
        'es_administrador':      es_administrador,
        'es_coordinador':        es_coordinador,
        'tipo_filter':           tipo_filter,
        'formato_filter':        formato_filter,
        'usuario_filter':        usuario_filter,
        'rango_filter':          rango_filter,
        'search':                search,
        'usuarios_disponibles':  usuarios_disponibles,
        'tipos_reporte':         Reporte.TIPO_CHOICES,
        'formatos_reporte':      Reporte.FORMATO_CHOICES,
    }
    return render(request, 'reportes/historial_reportes.html', context)