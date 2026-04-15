from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Empresa
from django.db.models import Q, Count
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.utils import timezone as django_timezone
from core.management.decorators import puede_ver_requerido, puede_editar_requerido


# ─────────────────────────────────────────────
# Rangos de fecha disponibles para filtros
# ─────────────────────────────────────────────

def obtener_rango_fechas(rango_fecha):
    """Retorna (inicio, fin) según el rango solicitado."""
    hoy    = django_timezone.now()
    inicio = None
    fin    = hoy

    if rango_fecha == 'hoy':
        inicio = hoy.replace(hour=0, minute=0, second=0, microsecond=0)

    elif rango_fecha == 'ayer':
        ayer   = hoy - timedelta(days=1)
        inicio = ayer.replace(hour=0,  minute=0,  second=0,  microsecond=0)
        fin    = ayer.replace(hour=23, minute=59, second=59, microsecond=999999)

    elif rango_fecha == 'esta_semana':
        inicio = (hoy - timedelta(days=hoy.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    elif rango_fecha == 'semana_pasada':
        inicio = (hoy - timedelta(days=hoy.weekday() + 7)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        fin = (inicio + timedelta(days=6)).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

    elif rango_fecha == 'este_mes':
        inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    elif rango_fecha == 'mes_pasado':
        ultimo_dia_mes_pasado = hoy.replace(day=1) - timedelta(days=1)
        inicio = ultimo_dia_mes_pasado.replace(day=1, hour=0,  minute=0,  second=0,  microsecond=0)
        fin    = ultimo_dia_mes_pasado.replace(       hour=23, minute=59, second=59, microsecond=999999)

    elif rango_fecha == 'ultimos_7_dias':
        inicio = (hoy - timedelta(days=7)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    elif rango_fecha == 'ultimos_30_dias':
        inicio = (hoy - timedelta(days=30)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    elif rango_fecha == 'este_año':
        inicio = hoy.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    return inicio, fin


# ─────────────────────────────────────────────
# Vistas
# ─────────────────────────────────────────────

@puede_ver_requerido
def listar_empresas(request):
    """Vista para listar todas las empresas con filtros."""
    search           = request.GET.get('search', '')
    municipio        = request.GET.get('municipio', '')
    min_trabajadores = request.GET.get('min_trabajadores', '')
    rango_fecha      = request.GET.get('rango_fecha', '')

    empresas = Empresa.objects.annotate(total_solicitudes=Count('solicitud'))

    # Filtro de búsqueda general
    if search:
        empresas = empresas.filter(
            Q(nombre__icontains=search)  |
            Q(nit__icontains=search)     |
            Q(contacto__icontains=search)|
            Q(correo__icontains=search)
        )

    # Filtro por municipio
    if municipio:
        empresas = empresas.filter(municipio__icontains=municipio)

    # Filtro por número mínimo de trabajadores
    if min_trabajadores:
        try:
            empresas = empresas.filter(numero_trabajadores__gte=int(min_trabajadores))
        except ValueError:
            pass

    # Filtro por rango de fecha
    if rango_fecha:
        fecha_inicio, fecha_fin = obtener_rango_fechas(rango_fecha)
        if fecha_inicio:
            empresas = empresas.filter(fecha_registro__gte=fecha_inicio)
        if fecha_fin:
            empresas = empresas.filter(fecha_registro__lte=fecha_fin)

    empresas = empresas.order_by('nombre')

    municipios = Empresa.objects.exclude(
        municipio__isnull=True
    ).exclude(municipio='').values_list('municipio', flat=True).distinct().order_by('municipio')

    context = {
        'empresas':               empresas,
        'municipios':             municipios,
        'search':                 search,
        'municipio_filter':       municipio,
        'min_trabajadores_filter': min_trabajadores,
        'rango_fecha':            rango_fecha,
        'total_empresas':         empresas.count(),
        'total_solicitudes':      sum(e.total_solicitudes for e in empresas),
    }
    return render(request, 'empresas/listar_empresas.html', context)


def _validar_empresa(post, empresa_id=None):
    """
    Valida los campos del formulario de empresa (crear y editar).
    Retorna (datos_limpios, lista_de_errores).
    empresa_id se pasa solo al editar para excluir la empresa actual
    en las validaciones de unicidad.
    """
    nombre              = post.get('nombre',              '').strip()
    nit                 = post.get('nit',                 '').strip()
    contacto            = post.get('contacto',            '').strip()
    correo              = post.get('correo',              '').strip()
    telefono            = post.get('telefono',            '').strip()
    municipio           = post.get('municipio',           '').strip()
    direccion           = post.get('direccion',           '').strip()
    numero_trabajadores = post.get('numero_trabajadores', '').strip()

    errores = []

    # ── Nombre ──────────────────────────────────────────────────────────────
    if not nombre:
        errores.append('⚠️ El nombre de la empresa es obligatorio')
    elif len(nombre) < 3:
        errores.append('⚠️ El nombre debe tener al menos 3 caracteres')
    else:
        qs_nombre = Empresa.objects.filter(nombre__iexact=nombre)
        if empresa_id:
            qs_nombre = qs_nombre.exclude(id=empresa_id)
        if qs_nombre.exists():
            errores.append(f'❌ Ya existe una empresa con el nombre "{nombre}"')

    # ── NIT ─────────────────────────────────────────────────────────────────
    if not nit:
        errores.append('⚠️ El NIT de la empresa es obligatorio')
    else:
        nit_limpio = nit.replace(' ', '').replace('-', '')
        if not nit_limpio.isdigit():
            errores.append('❌ El NIT solo debe contener números')
        elif len(nit_limpio) < 9 or len(nit_limpio) > 10:
            errores.append('❌ El NIT debe tener entre 9 y 10 dígitos')
        else:
            qs_nit = Empresa.objects.filter(nit=nit_limpio)
            if empresa_id:
                qs_nit = qs_nit.exclude(id=empresa_id)
            if qs_nit.exists():
                errores.append(f'❌ Ya existe una empresa con el NIT "{nit}"')
            else:
                nit = nit_limpio

    # ── Contacto ─────────────────────────────────────────────────────────────
    if not contacto:
        errores.append('⚠️ La persona de contacto es obligatoria')
    elif len(contacto) < 3:
        errores.append('⚠️ El nombre de contacto debe tener al menos 3 caracteres')

    # ── Correo ───────────────────────────────────────────────────────────────
    if not correo:
        errores.append('⚠️ El correo electrónico es obligatorio')
    elif '@' not in correo or '.' not in correo:
        errores.append('❌ El correo electrónico no es válido')

    # ── Teléfono ─────────────────────────────────────────────────────────────
    if not telefono:
        errores.append('⚠️ El teléfono es obligatorio')
    else:
        tel_limpio = telefono.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not tel_limpio.isdigit():
            errores.append('❌ El teléfono solo debe contener números')
        elif len(tel_limpio) < 7 or len(tel_limpio) > 13:
            errores.append('❌ El teléfono debe tener entre 7 y 13 dígitos')
        else:
            telefono = tel_limpio

    # ── Municipio ────────────────────────────────────────────────────────────
    if not municipio:
        errores.append('⚠️ El municipio es obligatorio')
    elif len(municipio) < 3:
        errores.append('⚠️ El municipio debe tener al menos 3 caracteres')

    # ── Dirección ────────────────────────────────────────────────────────────
    if not direccion:
        errores.append('⚠️ La dirección es obligatoria')
    elif len(direccion) < 5:
        errores.append('⚠️ La dirección debe tener al menos 5 caracteres')

    # ── Número de trabajadores ────────────────────────────────────────────────
    num_trabajadores_int = None
    if not numero_trabajadores:
        errores.append('⚠️ El número de trabajadores es obligatorio')
    else:
        try:
            num_trabajadores_int = int(numero_trabajadores)
            if num_trabajadores_int < 20:
                errores.append('❌ El número de trabajadores debe ser mínimo 20')
        except ValueError:
            errores.append('❌ El número de trabajadores debe ser un número válido')

    datos = {
        'nombre':                 nombre,
        'nit':                    nit,
        'contacto':               contacto,
        'correo':                 correo,
        'telefono':               telefono,
        'municipio':              municipio,
        'direccion':              direccion,
        'numero_trabajadores':    numero_trabajadores,
        'numero_trabajadores_int': num_trabajadores_int,
    }
    return datos, errores


def _contexto_formulario(datos):
    """Retorna el contexto con los datos del formulario para repintar en caso de error."""
    return {
        'nombre':              datos['nombre'],
        'nit':                 datos['nit'],
        'contacto':            datos['contacto'],
        'correo':              datos['correo'],
        'telefono':            datos['telefono'],
        'municipio':           datos['municipio'],
        'direccion':           datos['direccion'],
        'numero_trabajadores': datos['numero_trabajadores'],
    }


@puede_editar_requerido
@require_http_methods(["GET", "POST"])
def crear_empresa(request):
    """Vista para crear una nueva empresa."""
    if request.method != 'POST':
        return render(request, 'empresas/crear_empresa.html')

    datos, errores = _validar_empresa(request.POST)

    if errores:
        for error in errores:
            messages.error(request, error)
        return render(request, 'empresas/crear_empresa.html', _contexto_formulario(datos))

    try:
        with transaction.atomic():
            empresa = Empresa.objects.create(
                nombre              = datos['nombre'],
                nit                 = datos['nit'],
                contacto            = datos['contacto'],
                correo              = datos['correo'],
                telefono            = datos['telefono'],
                municipio           = datos['municipio'],
                direccion           = datos['direccion'],
                numero_trabajadores = datos['numero_trabajadores_int'] or 0,
            )
        messages.success(request, f'✅ ¡Empresa "{empresa.nombre}" creada exitosamente!')
        return redirect('empresas:listar_empresas')

    except Exception as e:
        messages.error(request, f'❌ Error al crear la empresa: {str(e)}')
        return render(request, 'empresas/crear_empresa.html', _contexto_formulario(datos))


@puede_editar_requerido
@require_http_methods(["GET", "POST"])
def editar_empresa(request, empresa_id):
    """Vista para editar una empresa existente."""
    empresa = get_object_or_404(Empresa, id=empresa_id)

    if request.method != 'POST':
        return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})

    datos, errores = _validar_empresa(request.POST, empresa_id=empresa_id)
    activo         = request.POST.get('activo') == 'on'

    if errores:
        for error in errores:
            messages.error(request, error)
        return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})

    try:
        with transaction.atomic():
            empresa.nombre              = datos['nombre']
            empresa.nit                 = datos['nit']
            empresa.contacto            = datos['contacto']
            empresa.correo              = datos['correo']
            empresa.telefono            = datos['telefono']
            empresa.municipio           = datos['municipio']
            empresa.direccion           = datos['direccion']
            empresa.numero_trabajadores = datos['numero_trabajadores_int'] or 0
            empresa.activo              = activo
            empresa.save()
        messages.success(request, f'✅ ¡Empresa "{empresa.nombre}" actualizada exitosamente!')
        return redirect('empresas:detalle_empresa', empresa_id=empresa.id)

    except Exception as e:
        messages.error(request, f'❌ Error al actualizar la empresa: {str(e)}')
        return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})


@puede_ver_requerido
def detalle_empresa(request, empresa_id):
    """Vista para el detalle de una empresa."""
    empresa = get_object_or_404(
        Empresa.objects.annotate(total_solicitudes=Count('solicitud')),
        id=empresa_id
    )
    solicitudes = empresa.solicitud_set.select_related(
        'programa', 'instructor_asignado'
    ).order_by('-fecha_recepcion')

    context = {
        'empresa':                 empresa,
        'solicitudes_activas':     solicitudes.exclude(estado='FINALIZADA'),
        'solicitudes_finalizadas': solicitudes.filter(estado='FINALIZADA'),
        'total_solicitudes':       solicitudes.count(),
    }
    return render(request, 'empresas/detalle_empresa.html', context)


@puede_editar_requerido
@require_http_methods(["GET", "POST"])
def desactivar_empresa(request, empresa_id):
    """Vista para desactivar una empresa."""
    empresa = get_object_or_404(Empresa, id=empresa_id)

    if request.method == 'POST':
        if not empresa.activo:
            messages.warning(request, f'⚠️ La empresa "{empresa.nombre}" ya está desactivada')
            return redirect('empresas:listar_empresas')

        with transaction.atomic():
            empresa.activo = False
            empresa.save()

        messages.success(request, f'✅ Empresa "{empresa.nombre}" desactivada exitosamente')
        return redirect('empresas:listar_empresas')

    context = {
        'empresa':            empresa,
        'tiene_dependencias': empresa.solicitud_set.exclude(estado='FINALIZADA').exists(),
    }
    return render(request, 'empresas/desactivar_empresa.html', context)


@puede_editar_requerido
@require_http_methods(["GET", "POST"])
def eliminar_empresa(request, empresa_id):
    """Vista para eliminar permanentemente una empresa."""
    empresa           = get_object_or_404(Empresa, id=empresa_id)
    total_solicitudes = empresa.solicitud_set.count()

    if request.method != 'POST':
        return render(request, 'empresas/eliminar_empresa.html', {
            'empresa': empresa, 'total_solicitudes': total_solicitudes
        })

    if total_solicitudes > 0:
        accion = request.POST.get('accion_solicitudes')

        if accion == 'cancelar':
            messages.warning(request, '⚠️ Eliminación cancelada.')
            return redirect('empresas:detalle_empresa', empresa_id=empresa.id)

        if accion == 'eliminar':
            nombre = empresa.nombre
            with transaction.atomic():
                empresa.solicitud_set.all().delete()
                empresa.delete()
            messages.success(
                request,
                f'✅ Empresa "{nombre}" y sus {total_solicitudes} solicitud(es) eliminadas permanentemente'
            )
            return redirect('empresas:listar_empresas')

        # Ninguna acción válida seleccionada
        messages.error(request, '❌ Debes seleccionar qué hacer con las solicitudes asociadas')
        return render(request, 'empresas/eliminar_empresa.html', {
            'empresa': empresa, 'total_solicitudes': total_solicitudes
        })

    # Sin solicitudes: eliminar directamente
    nombre = empresa.nombre
    with transaction.atomic():
        empresa.delete()
    messages.success(request, f'✅ Empresa "{nombre}" eliminada exitosamente')
    return redirect('empresas:listar_empresas')