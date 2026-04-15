# instructores/views.py
import json
from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone

from .models import Instructor
from programas.models import Programa
from solicitudes.models import Solicitud
from core.management.decorators import puede_ver_requerido, puede_editar_requerido


# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────

COLORES_CALENDARIO = [
    '#2e7d32', '#1565c0', '#6a1b9a', '#c62828',
    '#ef6c00', '#00838f', '#4527a0', '#558b2f',
    '#ad1457', '#0277bd',
]

CAMPOS_OBLIGATORIOS_INSTRUCTOR = ['nombre', 'cedula', 'telefono', 'correo']


# ─────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────

def _get_programas():
    """Retorna los programas activos ordenados por área y nombre."""
    return Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')


def _get_especialidades_filter():
    """Retorna programas activos para el filtro del listado."""
    return Programa.objects.filter(activo=True).order_by('nombre')


def _render_con_error(request, template, context, mensaje):
    """Agrega un mensaje de error y renderiza el template dado."""
    messages.error(request, mensaje)
    return render(request, template, context)


def _calcular_disponibilidad(instructor, hoy):
    """
    Calcula si un instructor está ocupado hoy y sus formaciones activas.
    Retorna (ocupado_hoy: bool, formaciones_activas: list, proxima: solicitud|None).
    """
    solicitudes_programadas = instructor.solicitud_set.filter(
        fecha_atencion__isnull=False,
    ).exclude(estado='FINALIZADA').select_related('empresa', 'programa')

    ocupado_hoy         = False
    formaciones_activas = []

    for sol in solicitudes_programadas:
        fecha_inicio = sol.fecha_atencion.date()
        fecha_fin    = sol.fecha_fin_formacion

        if fecha_inicio <= hoy and (fecha_fin is None or fecha_fin >= hoy):
            ocupado_hoy = True
            formaciones_activas.append(sol)

    proxima = None
    if not ocupado_hoy:
        proxima = instructor.solicitud_set.filter(
            fecha_atencion__isnull=False,
            fecha_atencion__date__gt=hoy,
        ).exclude(estado='FINALIZADA').order_by('fecha_atencion').first()

    return ocupado_hoy, formaciones_activas, proxima


def _clasificar_programacion(sol, hoy):
    """
    Clasifica una solicitud en activa, futura o pasada según sus fechas.
    Retorna una string: 'activa' | 'futura' | 'pasada' | None.
    """
    fecha_inicio = sol.fecha_atencion.date() if sol.fecha_atencion else None
    fecha_fin    = sol.fecha_fin_formacion

    if not fecha_inicio:
        return None

    if fecha_fin:
        if fecha_inicio <= hoy <= fecha_fin:
            return 'activa'
        if fecha_inicio > hoy:
            return 'futura'
        return 'pasada'

    # Sin fecha fin
    return 'activa' if fecha_inicio <= hoy else 'futura'


def _build_evento_calendario(sol, instructor, color):
    """Construye el dict de evento para FullCalendar a partir de una solicitud."""
    fecha_inicio = sol.fecha_atencion.date()
    fecha_fin    = (
        (sol.fecha_fin_formacion + timedelta(days=1)).isoformat()
        if sol.fecha_fin_formacion else None
    )
    return {
        'id':    sol.id,
        'title': instructor.nombre,
        'start': fecha_inicio.isoformat(),
        'end':   fecha_fin,
        'color': color,
        'extendedProps': {
            'instructor_id': instructor.id,
            'instructor':    instructor.nombre,
            'empresa':       sol.empresa.nombre,
            'programa':      sol.programa.nombre,
            'estado':        sol.get_estado_display(),
            'solicitud_id':  sol.id,
            'fecha_inicio':  fecha_inicio.isoformat(),
            'fecha_fin':     sol.fecha_fin_formacion.isoformat() if sol.fecha_fin_formacion else None,
        },
    }


def _instructor_ocupado_hoy(instructor, hoy):
    """Retorna True si el instructor tiene al menos una formación activa hoy."""
    for sol in instructor.solicitud_set.filter(
        fecha_atencion__isnull=False
    ).exclude(estado='FINALIZADA'):
        inicio = sol.fecha_atencion.date()
        fin    = sol.fecha_fin_formacion
        if inicio <= hoy and (fin is None or fin >= hoy):
            return True
    return False


def verificar_solapamiento_instructor(instructor, fecha_inicio, fecha_fin, excluir_solicitud_id=None):
    """
    Verifica si un instructor tiene un solapamiento de fechas con otra solicitud.

    Un solapamiento ocurre cuando el rango [fecha_inicio, fecha_fin] de la nueva
    asignación se cruza con el rango de cualquier solicitud existente del instructor.

    Casos de solapamiento (A = solicitud existente, B = nueva):
        A:  |---------|
        B:      |---------|   → B.inicio <= A.fin  AND  B.fin >= A.inicio

    Retorna (hay_conflicto: bool, solicitudes_en_conflicto: list[dict]).
    """
    if not fecha_inicio:
        return False, []

    qs = instructor.solicitud_set.filter(
        fecha_atencion__isnull=False,
    ).exclude(estado='FINALIZADA').select_related('empresa', 'programa')

    if excluir_solicitud_id:
        qs = qs.exclude(pk=excluir_solicitud_id)

    conflictos = []

    for sol in qs:
        sol_inicio = sol.fecha_atencion.date()
        sol_fin    = sol.fecha_fin_formacion  # puede ser None

        # Si la solicitud existente no tiene fecha fin, se considera "abierta"
        # (sin fin conocido), por lo que cualquier nueva asignación que empiece
        # desde sol_inicio en adelante entra en conflicto.
        if sol_fin is None:
            # Conflicto si la nueva asignación empieza en o después del inicio existente
            # O si la nueva asignación termina después del inicio existente.
            nueva_fin_efectiva = fecha_fin if fecha_fin else fecha_inicio
            if nueva_fin_efectiva >= sol_inicio:
                conflictos.append({
                    'solicitud':    sol,
                    'empresa':      sol.empresa.nombre,
                    'programa':     sol.programa.nombre,
                    'fecha_inicio': sol_inicio.strftime('%d/%m/%Y'),
                    'fecha_fin':    'Sin fecha fin definida',
                })
        else:
            # Solapamiento clásico: los rangos se cruzan
            nueva_fin_efectiva = fecha_fin if fecha_fin else fecha_inicio
            if fecha_inicio <= sol_fin and nueva_fin_efectiva >= sol_inicio:
                conflictos.append({
                    'solicitud':    sol,
                    'empresa':      sol.empresa.nombre,
                    'programa':     sol.programa.nombre,
                    'fecha_inicio': sol_inicio.strftime('%d/%m/%Y'),
                    'fecha_fin':    sol_fin.strftime('%d/%m/%Y'),
                })

    return len(conflictos) > 0, conflictos


# ─────────────────────────────────────────────
# Helpers de validación de campos numéricos
# ─────────────────────────────────────────────

def _validar_campo_numerico(valor, nombre_campo, max_digitos=13):
    """
    Valida que un campo sea solo dígitos y no supere max_digitos.
    Retorna (es_valido: bool, mensaje_error: str | None).
    """
    if not valor.isdigit():
        return False, f'❌ El {nombre_campo} debe contener solo números'
    if len(valor) > max_digitos:
        return False, f'❌ El {nombre_campo} no puede tener más de {max_digitos} dígitos'
    return True, None


# ─────────────────────────────────────────────
# Vistas
# ─────────────────────────────────────────────

@puede_ver_requerido
def listar_instructores(request):
    """Vista para listar todos los instructores."""
    search                = request.GET.get('search', '')
    especialidad_id       = request.GET.get('especialidad', '')
    activo                = request.GET.get('activo', '')
    disponibilidad_filter = request.GET.get('disponibilidad', '')

    instructores = Instructor.objects.prefetch_related('especialidad').annotate(
        total_solicitudes=Count('solicitud')
    )

    # ── Filtros de búsqueda ───────────────────
    if search:
        instructores = instructores.filter(
            Q(nombre__icontains=search)   |
            Q(correo__icontains=search)   |
            Q(telefono__icontains=search) |
            Q(cedula__icontains=search)
        )

    if especialidad_id:
        instructores = instructores.filter(especialidad__id=especialidad_id)

    if activo:
        instructores = instructores.filter(activo=(activo == 'true'))

    instructores = instructores.order_by('nombre')

    # ── Disponibilidad ────────────────────────
    hoy = timezone.now().date()

    instructores_con_disponibilidad = [
        {
            'instructor':          instructor,
            'ocupado':             ocupado,
            'formaciones_activas': formaciones,
            'proxima':             proxima,
        }
        for instructor in instructores
        for ocupado, formaciones, proxima in [_calcular_disponibilidad(instructor, hoy)]
    ]

    # ── Filtro de disponibilidad ──────────────
    filtros_disponibilidad = {
        'libre':   lambda d: not d['ocupado'],
        'ocupado': lambda d: d['ocupado'],
    }
    if disponibilidad_filter in filtros_disponibilidad:
        instructores_con_disponibilidad = [
            d for d in instructores_con_disponibilidad
            if filtros_disponibilidad[disponibilidad_filter](d)
        ]

    # ── Estadísticas ──────────────────────────
    context = {
        'instructores_con_disponibilidad': instructores_con_disponibilidad,
        'especialidades':        _get_especialidades_filter(),
        'search':                search,
        'especialidad_filter':   especialidad_id,
        'activo_filter':         activo,
        'disponibilidad_filter': disponibilidad_filter,
        'total_instructores':    len(instructores_con_disponibilidad),
        'instructores_activos':  sum(1 for d in instructores_con_disponibilidad if d['instructor'].activo),
        'total_solicitudes':     sum(d['instructor'].total_solicitudes for d in instructores_con_disponibilidad),
        'disponibles_hoy':       sum(1 for d in instructores_con_disponibilidad if not d['ocupado'] and d['instructor'].activo),
        'ocupados_hoy':          sum(1 for d in instructores_con_disponibilidad if d['ocupado']),
        'hoy':                   hoy,
    }
    return render(request, 'instructores/listar_instructores.html', context)


@puede_ver_requerido
def detalle_instructor(request, instructor_id):
    """Vista para el detalle de un instructor."""
    instructor = get_object_or_404(
        Instructor.objects.prefetch_related('especialidad').annotate(
            total_solicitudes=Count('solicitud')
        ),
        id=instructor_id,
    )

    solicitudes = instructor.solicitud_set.select_related(
        'empresa', 'programa__area'
    ).order_by('-fecha_recepcion')

    hoy = timezone.now().date()

    # ── Clasificar programaciones ─────────────
    programaciones_activas  = []
    programaciones_futuras  = []
    programaciones_pasadas  = []

    destinos = {
        'activa': programaciones_activas,
        'futura': programaciones_futuras,
        'pasada': programaciones_pasadas,
    }

    for sol in solicitudes.filter(fecha_atencion__isnull=False).order_by('fecha_atencion'):
        clasificacion = _clasificar_programacion(sol, hoy)
        if clasificacion:
            destinos[clasificacion].append(sol)

    context = {
        'instructor':              instructor,
        'especialidades':          instructor.especialidad.all(),
        'solicitudes_activas':     solicitudes.exclude(estado='FINALIZADA'),
        'solicitudes_finalizadas': solicitudes.filter(estado='FINALIZADA'),
        'total_solicitudes':       solicitudes.count(),
        'programaciones_activas':  programaciones_activas,
        'programaciones_futuras':  programaciones_futuras,
        'programaciones_pasadas':  programaciones_pasadas,
        'hoy':                     hoy,
    }
    return render(request, 'instructores/detalle_instructor.html', context)


@puede_editar_requerido
def crear_instructor(request):
    """Vista para crear un nuevo instructor."""
    template = 'instructores/crear_instructor.html'

    if request.method == 'POST':
        nombre             = request.POST.get('nombre', '').strip()
        cedula             = request.POST.get('cedula', '').strip()
        telefono           = request.POST.get('telefono', '').strip()
        correo             = request.POST.get('correo', '').strip()
        activo             = request.POST.get('activo') == 'on'
        especialidades_ids = request.POST.getlist('especialidades')

        ctx_error = {
            'programas': _get_programas(),
            'nombre':    nombre,
            'cedula':    cedula,
            'telefono':  telefono,
            'correo':    correo,
        }

        # ── Validar cédula ────────────────────
        cedula_valida, error_cedula = _validar_campo_numerico(cedula, 'número de cédula')
        # ── Validar teléfono ──────────────────
        telefono_valido, error_telefono = _validar_campo_numerico(telefono, 'número de teléfono')

        # ── Lista de validaciones ─────────────
        validaciones = [
            (not all([nombre, cedula, telefono, correo]),
             '⚠️ El nombre, cédula, teléfono y correo son obligatorios'),
            (not especialidades_ids,
             '⚠️ Debe seleccionar al menos una especialidad'),
            # Validaciones numéricas (cédula y teléfono)
            (not cedula_valida,  error_cedula),
            (not telefono_valido, error_telefono),
            # Unicidad
            (Instructor.objects.filter(correo__iexact=correo).exists(),
             f'❌ Ya existe un instructor con el correo "{correo}"'),
            (Instructor.objects.filter(cedula=cedula).exists(),
             f'❌ Ya existe un instructor con la cédula "{cedula}"'),
        ]

        for condicion, mensaje in validaciones:
            if condicion:
                return _render_con_error(request, template, ctx_error, mensaje)

        try:
            instructor = Instructor.objects.create(
                nombre=nombre, cedula=cedula,
                telefono=telefono, correo=correo, activo=activo,
            )
            instructor.especialidad.set(especialidades_ids)
            messages.success(request, f'✅ Instructor "{instructor.nombre}" creado exitosamente!')
            return redirect('instructores:listar_instructores')
        except Exception as e:
            messages.error(request, f'❌ Error al crear el instructor: {str(e)}')

    return render(request, template, {'programas': _get_programas()})


@puede_editar_requerido
def editar_instructor(request, instructor_id):
    """Vista para editar un instructor existente."""
    instructor = get_object_or_404(Instructor, id=instructor_id)
    template   = 'instructores/editar_instructor.html'

    if request.method == 'POST':
        nombre             = request.POST.get('nombre', '').strip()
        cedula             = request.POST.get('cedula', '').strip()
        telefono           = request.POST.get('telefono', '').strip()
        correo             = request.POST.get('correo', '').strip()
        activo             = request.POST.get('activo') == 'on'
        especialidades_ids = request.POST.getlist('especialidades')

        ctx_error = {
            'instructor':                instructor,
            'programas':                 _get_programas(),
            'especialidades_instructor': list(instructor.especialidad.values_list('id', flat=True)),
        }

        # ── Validar cédula ────────────────────
        cedula_valida, error_cedula = _validar_campo_numerico(cedula, 'número de cédula')
        # ── Validar teléfono ──────────────────
        telefono_valido, error_telefono = _validar_campo_numerico(telefono, 'número de teléfono')

        # ── Lista de validaciones ─────────────
        validaciones = [
            (not all([nombre, cedula, telefono, correo]),
             '⚠️ El nombre, cédula, teléfono y correo son obligatorios'),
            (not especialidades_ids,
             '⚠️ Debe seleccionar al menos una especialidad'),
            # Validaciones numéricas (cédula y teléfono)
            (not cedula_valida,  error_cedula),
            (not telefono_valido, error_telefono),
            # Unicidad (excluyendo el instructor actual)
            (Instructor.objects.filter(correo__iexact=correo).exclude(id=instructor_id).exists(),
             f'❌ Ya existe otro instructor con el correo "{correo}"'),
            (Instructor.objects.filter(cedula=cedula).exclude(id=instructor_id).exists(),
             f'❌ Ya existe otro instructor con la cédula "{cedula}"'),
        ]

        for condicion, mensaje in validaciones:
            if condicion:
                return _render_con_error(request, template, ctx_error, mensaje)

        try:
            instructor.nombre   = nombre
            instructor.cedula   = cedula
            instructor.telefono = telefono
            instructor.correo   = correo
            instructor.activo   = activo
            instructor.save()
            instructor.especialidad.set(especialidades_ids)
            messages.success(request, f'✅ Instructor "{instructor.nombre}" actualizado exitosamente')
            return redirect('instructores:detalle_instructor', instructor_id=instructor.id)
        except Exception as e:
            messages.error(request, f'❌ Error al actualizar el instructor: {str(e)}')

    return render(request, template, {
        'instructor':                instructor,
        'programas':                 _get_programas(),
        'especialidades_instructor': list(instructor.especialidad.values_list('id', flat=True)),
    })


@puede_editar_requerido
def desactivar_instructor(request, instructor_id):
    """Vista para desactivar un instructor."""
    instructor          = get_object_or_404(Instructor, id=instructor_id)
    solicitudes_activas = instructor.solicitud_set.exclude(estado='FINALIZADA').count()
    template            = 'instructores/desactivar_instructor.html'
    ctx                 = {'instructor': instructor, 'solicitudes_activas': solicitudes_activas}

    if request.method == 'POST':
        if solicitudes_activas > 0 and request.POST.get('reasignar') != 'on':
            return _render_con_error(
                request, template, ctx,
                'Debes confirmar la desasignación de las solicitudes activas',
            )

        if solicitudes_activas > 0:
            instructor.solicitud_set.exclude(estado='FINALIZADA').update(instructor_asignado=None)
            messages.warning(request, f'{solicitudes_activas} solicitud(es) activa(s) fueron desasignadas del instructor')

        instructor.activo = False
        instructor.save()
        messages.success(request, f'Instructor "{instructor.nombre}" desactivado exitosamente')
        return redirect('instructores:listar_instructores')

    return render(request, template, ctx)


@puede_editar_requerido
def eliminar_instructor(request, instructor_id):
    """Vista para eliminar permanentemente el instructor."""
    instructor        = get_object_or_404(Instructor, id=instructor_id)
    total_solicitudes = instructor.solicitud_set.count()
    template          = 'instructores/eliminar_instructor.html'
    ctx               = {'instructor': instructor, 'total_solicitudes': total_solicitudes}

    if request.method == 'POST':
        accion = request.POST.get('accion_solicitudes')

        if total_solicitudes > 0 and accion == 'cancelar':
            messages.warning(request, '⚠️ Eliminación cancelada.')
            return redirect('instructores:detalle_instructor', instructor_id=instructor.id)

        if total_solicitudes > 0 and accion != 'desasignar':
            return _render_con_error(
                request, template, ctx,
                '❌ Debes seleccionar qué hacer con las solicitudes asociadas',
            )

        nombre_instructor = instructor.nombre
        if total_solicitudes > 0:
            instructor.solicitud_set.update(instructor_asignado=None)
        instructor.delete()

        msg = (
            f'✅ Instructor "{nombre_instructor}" eliminado y {total_solicitudes} solicitud(es) desasignadas'
            if total_solicitudes > 0
            else f'✅ Instructor "{nombre_instructor}" eliminado exitosamente'
        )
        messages.success(request, msg)
        return redirect('instructores:listar_instructores')

    return render(request, template, ctx)


@puede_ver_requerido
def calendario_instructores(request):
    """Vista del calendario de instructores con eventos por FullCalendar."""
    hoy                  = timezone.now().date()
    instructores_activos = Instructor.objects.filter(activo=True).order_by('nombre')

    eventos = []
    leyenda = []

    for idx, instructor in enumerate(instructores_activos):
        color = COLORES_CALENDARIO[idx % len(COLORES_CALENDARIO)]

        solicitudes = instructor.solicitud_set.filter(
            fecha_atencion__isnull=False,
        ).exclude(estado='FINALIZADA').select_related('empresa', 'programa')

        eventos += [_build_evento_calendario(sol, instructor, color) for sol in solicitudes]

        leyenda.append({
            'id':     instructor.id,
            'nombre': instructor.nombre,
            'color':  color,
            'total':  solicitudes.count(),
        })

    ocupados_hoy = sum(
        1 for instructor in instructores_activos
        if _instructor_ocupado_hoy(instructor, hoy)
    )

    context = {
        'eventos_json':         json.dumps(eventos, ensure_ascii=False),
        'leyenda_instructores': leyenda,
        'total_instructores':   instructores_activos.count(),
        'ocupados_hoy':         ocupados_hoy,
        'total_formaciones':    Solicitud.objects.filter(
                                    fecha_atencion__isnull=False
                                ).exclude(estado='FINALIZADA').count(),
        'sin_fecha_fin':        Solicitud.objects.filter(
                                    fecha_atencion__isnull=False,
                                    fecha_fin_formacion__isnull=True,
                                ).exclude(estado='FINALIZADA').count(),
    }
    return render(request, 'instructores/calendario_instructores.html', context)