from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Area
from programas.models import Programa
from django.db.models import Count, Q
from core.management.decorators import puede_ver_requerido, puede_editar_requerido


@puede_ver_requerido
def listar_areas(request):
    """Vista para listar todas las áreas"""
    search  = request.GET.get('search', '')
    activo  = request.GET.get('activo', '')
    area_id = request.GET.get('area_id', '')

    todas_areas = Area.objects.all().order_by('nombre')
    areas = Area.objects.annotate(total_programas=Count('programas'))

    # ✅ BUG CORREGIDO: el dict con claves string vacías colisionaba cuando
    # search y activo eran '' al mismo tiempo (misma clave falsy).
    # Se usa lista de tuplas para mantener el orden y evitar colisiones.
    filtros = [
        (search,   Q(nombre__icontains=search) | Q(descripcion__icontains=search)),
        (area_id,  Q(id=area_id)),
        (activo,   Q(activo=(activo == 'true'))),
    ]
    for valor, condicion in filtros:
        if valor:
            areas = areas.filter(condicion)

    areas = areas.order_by('nombre')

    area_seleccionada = None
    if area_id:
        try:
            area_seleccionada = Area.objects.get(id=area_id)
        except Area.DoesNotExist:
            pass

    context = {
        'areas':             areas,
        'todas_areas':       todas_areas,
        'search':            search,
        'activo_filter':     activo,
        'area_filter':       area_id,
        'area_seleccionada': area_seleccionada,
        'total_areas':       areas.count(),
        'areas_activas':     areas.filter(activo=True).count(),
        'total_programas':   Programa.objects.filter(area__in=areas).count(),
    }
    return render(request, 'area_formacion/listar_areas.html', context)


@puede_ver_requerido
def detalle_area(request, area_id):
    """Vista para el detalle de un área"""
    area = get_object_or_404(
        Area.objects.annotate(total_programas=Count('programas')),
        id=area_id
    )
    programas = area.programas.annotate(
        total_solicitudes=Count('solicitud')
    ).order_by('nombre')

    context = {
        'area':                area,
        'programas_activos':   programas.filter(activo=True),
        'programas_inactivos': programas.filter(activo=False),
    }
    return render(request, 'area_formacion/detalle_area.html', context)


@puede_editar_requerido
def crear_area(request):
    """Vista para crear una nueva área"""
    if request.method != 'POST':
        return render(request, 'area_formacion/crear_area.html')

    nombre      = request.POST.get('nombre')
    descripcion = request.POST.get('descripcion', '')
    activo      = request.POST.get('activo') == 'on'

    # ✅ BUG CORREGIDO: la segunda validación consultaba la BD incluso cuando
    # nombre era None/vacío, lo que causaba un error de SQL.
    # Se separan: primero se valida que exista, luego que no esté duplicado.
    if not nombre:
        messages.error(request, '⚠️ El nombre es obligatorio')
        return render(request, 'area_formacion/crear_area.html', {
            'nombre': nombre, 'descripcion': descripcion
        })

    if Area.objects.filter(nombre__iexact=nombre).exists():
        messages.error(request, f'❌ Ya existe un área con el nombre "{nombre}"')
        return render(request, 'area_formacion/crear_area.html', {
            'nombre': nombre, 'descripcion': descripcion
        })

    try:
        area = Area.objects.create(nombre=nombre, descripcion=descripcion, activo=activo)
        messages.success(
            request,
            f'✅ ¡Área "{area.nombre}" creada exitosamente! Ya está disponible en el listado de áreas.'
        )
        return redirect('area_formacion:listar_areas')
    except Exception as e:
        messages.error(request, f'❌ Error al crear el área: {str(e)}')
        return render(request, 'area_formacion/crear_area.html', {
            'nombre': nombre, 'descripcion': descripcion
        })


@puede_editar_requerido
def editar_area(request, area_id):
    """Vista para editar un área existente"""
    area = get_object_or_404(Area, id=area_id)

    if request.method != 'POST':
        return render(request, 'area_formacion/editar_area.html', {'area': area})

    nombre      = request.POST.get('nombre')
    descripcion = request.POST.get('descripcion', '')
    activo      = request.POST.get('activo') == 'on'

    # ✅ Mismo criterio que crear_area: validaciones separadas y en orden
    if not nombre:
        messages.error(request, '⚠️ El nombre es obligatorio')
        return render(request, 'area_formacion/editar_area.html', {'area': area})

    if Area.objects.filter(nombre__iexact=nombre).exclude(id=area_id).exists():
        messages.error(request, f'❌ Ya existe otra área con el nombre "{nombre}"')
        return render(request, 'area_formacion/editar_area.html', {'area': area})

    try:
        area.nombre      = nombre
        area.descripcion = descripcion
        area.activo      = activo
        area.save()
        messages.success(
            request,
            f'✅ ¡Área "{area.nombre}" actualizada exitosamente! Los cambios ya están disponibles en el sistema.'
        )
        return redirect('area_formacion:detalle_area', area_id=area.id)
    except Exception as e:
        messages.error(request, f'❌ Error al actualizar el área: {str(e)}')
        return render(request, 'area_formacion/editar_area.html', {'area': area})


@puede_editar_requerido
def desactivar_area(request, area_id):
    """Vista para desactivar un área y opcionalmente sus programas"""
    area = get_object_or_404(Area, id=area_id)

    if request.method == 'POST':
        area.activo = False
        area.save()

        if request.POST.get('desactivar_programas') == 'on':
            cantidad = area.programas.filter(activo=True).update(activo=False)
            messages.success(
                request,
                f'Área "{area.nombre}" y sus {cantidad} programas activos desactivados exitosamente'
            )
        else:
            messages.success(request, f'Área "{area.nombre}" desactivada exitosamente')

        return redirect('area_formacion:listar_areas')

    context = {
        'area':              area,
        'total_programas':   area.programas.count(),
        'programas_activos': area.programas.filter(activo=True).count(),
    }
    return render(request, 'area_formacion/desactivar_area.html', context)


@puede_editar_requerido
def eliminar_area(request, area_id):
    """Vista para eliminar permanentemente un área"""
    area            = get_object_or_404(Area, id=area_id)
    total_programas = area.programas.count()

    if request.method != 'POST':
        return render(request, 'area_formacion/eliminar_area.html', {
            'area': area, 'total_programas': total_programas
        })

    if total_programas > 0:
        accion = request.POST.get('accion_programas')

        if accion == 'cancelar':
            messages.warning(
                request,
                f'⚠️ Eliminación cancelada. El área "{area.nombre}" no se eliminó'
            )
            return redirect('area_formacion:detalle_area', area_id=area.id)

        if accion == 'eliminar':
            nombre = area.nombre
            area.programas.all().delete()
            area.delete()
            messages.success(
                request,
                f'✅ Área "{nombre}" y sus {total_programas} programas eliminados permanentemente'
            )
            return redirect('area_formacion:listar_areas')

        # Ninguna acción válida seleccionada
        messages.error(request, '❌ Debes seleccionar qué hacer con los programas asociados')
        return render(request, 'area_formacion/eliminar_area.html', {
            'area': area, 'total_programas': total_programas
        })

    # Sin programas asociados: eliminar directamente
    nombre = area.nombre
    area.delete()
    messages.success(request, f'✅ Área "{nombre}" eliminada exitosamente')
    return redirect('area_formacion:listar_areas')