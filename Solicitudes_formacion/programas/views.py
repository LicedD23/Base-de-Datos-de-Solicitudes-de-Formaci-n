# programas/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Count, Q

from .models import Programa, Area
from core.management.decorators import puede_ver_requerido, puede_editar_requerido


# ─────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────

def _get_areas():
    """Retorna las áreas activas ordenadas por nombre."""
    return Area.objects.filter(activo=True).order_by('nombre')


def _render_con_error(request, template, context, mensaje):
    """Agrega un mensaje de error y renderiza el template dado."""
    messages.error(request, mensaje)
    return render(request, template, context)


def _validar_programa(codigo, nombre, area_id, duracion_horas=None, exclude_id=None):
    """
    Valida los campos del programa.
    Retorna el mensaje de error como string, o None si todo es válido.
    """
    # Validar duración si se proporcionó
    duracion_error = None
    if duracion_horas:
        try:
            horas = int(duracion_horas)
            if horas < 40:
                duracion_error = '❌ La duración mínima permitida es de 40 horas.'
            elif horas > 480:
                duracion_error = '❌ La duración máxima permitida es de 480 horas.'
        except (ValueError, TypeError):
            duracion_error = '❌ La duración debe ser un número entero válido.'

    validaciones = [
        (not nombre or not area_id,
         '❌ El nombre y el área son obligatorios.'),
        (not codigo,
         '❌ El código del programa es obligatorio.'),
        (not codigo.isdigit(),
         '❌ El código solo puede contener números. No se permiten letras ni caracteres especiales.'),
        (
            Programa.objects.filter(codigo=codigo).exclude(id=exclude_id).exists()
            if exclude_id
            else Programa.objects.filter(codigo=codigo).exists(),
            f'❌ Ya existe un programa con el código "{codigo}". Por favor, usa otro código.'
        ),
        (duracion_error is not None, duracion_error or ''),
    ]

    for condicion, mensaje in validaciones:
        if condicion:
            return mensaje
    return None


def _parsear_campos_post(request):
    """Lee y retorna los campos del formulario de programa desde POST."""
    return {
        'nombre':         request.POST.get('nombre', '').strip(),
        'codigo':         request.POST.get('codigo', '').strip(),
        'area_id':        request.POST.get('area'),
        'descripcion':    request.POST.get('descripcion', ''),
        'duracion_horas': request.POST.get('duracion_horas', '').strip(),
        'activo':         request.POST.get('activo') == 'on',
    }


# ─────────────────────────────────────────────
# Vistas
# ─────────────────────────────────────────────

@puede_ver_requerido
def listar_programas(request):
    """Vista para listar todos los programas."""
    search      = request.GET.get('search', '')
    area_id     = request.GET.get('area', '')
    activo      = request.GET.get('activo', '')
    programa_id = request.GET.get('programa', '')

    programas = Programa.objects.select_related('area').annotate(
        total_solicitudes=Count('solicitud')
    )

    # ── Filtros ───────────────────────────────
    filtros = [
        (search,      lambda qs: qs.filter(
            Q(nombre__icontains=search)      |
            Q(codigo__icontains=search)      |
            Q(descripcion__icontains=search)
        )),
        (area_id,     lambda qs: qs.filter(area_id=area_id)),
        (activo,      lambda qs: qs.filter(activo=activo == 'true')),
        (programa_id, lambda qs: qs.filter(id=programa_id)),
    ]

    for condicion, aplicar in filtros:
        if condicion:
            programas = aplicar(programas)

    programas = programas.order_by('area__nombre', 'nombre')

    context = {
        'programas':          programas,
        'areas':              _get_areas(),
        'todos_programas':    Programa.objects.all().order_by('nombre'),
        'search':             search,
        'area_filter':        area_id,
        'activo_filter':      activo,
        'total_programas':    Programa.objects.count(),
        'programas_activos':  Programa.objects.filter(activo=True).count(),
        'total_areas':        _get_areas().count(),
    }
    return render(request, 'programas/listar_programas.html', context)


@puede_ver_requerido
def detalle_programa(request, programa_id):
    """Vista para el detalle de un programa."""
    programa = get_object_or_404(
        Programa.objects.select_related('area').annotate(
            total_solicitudes=Count('solicitud')
        ),
        id=programa_id,
    )

    context = {
        'programa':              programa,
        'solicitudes_recientes': programa.solicitud_set.select_related(
                                     'empresa', 'instructor_asignado'
                                 ).order_by('-fecha_recepcion')[:5],
        'instructores':          programa.instructores.filter(activo=True),
    }
    return render(request, 'programas/detalle_programa.html', context)


@puede_editar_requerido
def crear_programa(request):
    """Vista para crear un nuevo programa."""
    template  = 'programas/crear_programa.html'
    ctx_base  = {'areas': _get_areas()}

    if request.method == 'POST':
        campos = _parsear_campos_post(request)
        error  = _validar_programa(
            campos['codigo'],
            campos['nombre'],
            campos['area_id'],
            duracion_horas=campos['duracion_horas'],
        )

        if error:
            return _render_con_error(request, template, ctx_base, error)

        try:
            area     = Area.objects.get(id=campos['area_id'])
            programa = Programa.objects.create(
                nombre=campos['nombre'],
                codigo=campos['codigo'],
                area=area,
                descripcion=campos['descripcion'],
                duracion_horas=int(campos['duracion_horas']) if campos['duracion_horas'] else None,
                activo=campos['activo'],
            )
            messages.success(request, f'✅ Programa "{programa.nombre}" creado exitosamente.')
            return redirect('programas:listar_programas')

        except Area.DoesNotExist:
            return _render_con_error(request, template, ctx_base, '❌ El área seleccionada no existe.')
        except Exception as e:
            return _render_con_error(request, template, ctx_base, f'❌ Error al crear el programa: {str(e)}')

    return render(request, template, ctx_base)


@puede_editar_requerido
def editar_programa(request, programa_id):
    """Vista para editar un programa existente."""
    programa  = get_object_or_404(Programa, id=programa_id)
    template  = 'programas/editar_programa.html'
    ctx_base  = {'programa': programa, 'areas': _get_areas()}

    if request.method == 'POST':
        campos = _parsear_campos_post(request)
        error  = _validar_programa(
            campos['codigo'],
            campos['nombre'],
            campos['area_id'],
            duracion_horas=campos['duracion_horas'],
            exclude_id=programa_id,
        )

        if error:
            return _render_con_error(request, template, ctx_base, error)

        try:
            programa.nombre        = campos['nombre']
            programa.codigo        = campos['codigo']
            programa.area          = Area.objects.get(id=campos['area_id'])
            programa.descripcion   = campos['descripcion']
            programa.duracion_horas = int(campos['duracion_horas']) if campos['duracion_horas'] else None
            programa.activo        = campos['activo']
            programa.save()

            messages.success(request, f'✅ Programa "{programa.nombre}" actualizado exitosamente.')
            return redirect('programas:detalle_programa', programa_id=programa.id)

        except Area.DoesNotExist:
            return _render_con_error(request, template, ctx_base, '❌ El área seleccionada no existe.')
        except Exception as e:
            return _render_con_error(request, template, ctx_base, f'❌ Error al actualizar el programa: {str(e)}')

    return render(request, template, ctx_base)


@puede_editar_requerido
def desactivar_programa(request, programa_id):
    """Vista para desactivar un programa."""
    programa = get_object_or_404(Programa, id=programa_id)
    template = 'programas/desactivar_programa.html'
    ctx      = {
        'programa':           programa,
        'total_solicitudes':  programa.solicitud_set.count(),
        'solicitudes_activas': programa.solicitud_set.filter(
                                   estado__in=['pendiente', 'aprobada']
                               ).count(),
    }

    if request.method == 'POST':
        programa.activo = False
        programa.save()
        messages.success(request, f'✅ Programa "{programa.nombre}" desactivado exitosamente.')
        return redirect('programas:listar_programas')

    return render(request, template, ctx)


@puede_editar_requerido
def eliminar_programa(request, programa_id):
    """Vista para eliminar permanentemente un programa."""
    programa          = get_object_or_404(Programa, id=programa_id)
    total_solicitudes = programa.solicitud_set.count()
    template          = 'programas/eliminar_programa.html'
    ctx               = {'programa': programa, 'total_solicitudes': total_solicitudes}

    if request.method == 'POST':
        accion = request.POST.get('accion_solicitudes')

        if accion == 'cancelar':
            messages.warning(request, f'⚠️ Eliminación cancelada. El programa "{programa.nombre}" no se eliminó.')
            return redirect('programas:detalle_programa', programa_id=programa.id)

        if total_solicitudes > 0 and accion != 'eliminar':
            return _render_con_error(
                request, template, ctx,
                '❌ Debes seleccionar qué hacer con las solicitudes asociadas.',
            )

        nombre_programa = programa.nombre
        if total_solicitudes > 0:
            programa.solicitud_set.all().delete()

        programa.delete()

        msg = (
            f'✅ Programa "{nombre_programa}" y sus {total_solicitudes} solicitud(es) eliminados permanentemente.'
            if total_solicitudes > 0
            else f'✅ Programa "{nombre_programa}" eliminado exitosamente.'
        )
        messages.success(request, msg)
        return redirect('programas:listar_programas')

    return render(request, template, ctx)