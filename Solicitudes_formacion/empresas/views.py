from datetime import timezone, datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Empresa
from django.db.models import Q, Count
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.utils import timezone as django_timezone
from core.management.decorators import puede_ver_requerido, puede_editar_requerido

# ✅ SIN decorador — esta es una función auxiliar, no una vista
def obtener_rango_fechas(rango_fecha):
    """
    Retorna las fechas de inicio y fin según el rango seleccionado
    """
    hoy = django_timezone.now()
    inicio = None
    fin = hoy
    
    if rango_fecha == 'hoy':
        inicio = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
    
    elif rango_fecha == 'ayer':
        ayer = hoy - timedelta(days=1)
        inicio = ayer.replace(hour=0, minute=0, second=0, microsecond=0)
        fin = ayer.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    elif rango_fecha == 'esta_semana':
        inicio = hoy - timedelta(days=hoy.weekday())
        inicio = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
    
    elif rango_fecha == 'semana_pasada':
        inicio = hoy - timedelta(days=hoy.weekday() + 7)
        inicio = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
        fin = inicio + timedelta(days=6)
        fin = fin.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    elif rango_fecha == 'este_mes':
        inicio = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    elif rango_fecha == 'mes_pasado':
        primer_dia_este_mes = hoy.replace(day=1)
        ultimo_dia_mes_pasado = primer_dia_este_mes - timedelta(days=1)
        inicio = ultimo_dia_mes_pasado.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fin = ultimo_dia_mes_pasado.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    elif rango_fecha == 'ultimos_7_dias':
        inicio = hoy - timedelta(days=7)
        inicio = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
    
    elif rango_fecha == 'ultimos_30_dias':
        inicio = hoy - timedelta(days=30)
        inicio = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
    
    elif rango_fecha == 'este_año':
        inicio = hoy.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    
    return inicio, fin


@puede_ver_requerido
def listar_empresas(request):
    """Vista para listar todas las empresas"""
    search = request.GET.get('search', '')
    municipio = request.GET.get('municipio', '')
    min_trabajadores = request.GET.get('min_trabajadores', '')
    rango_fecha = request.GET.get('rango_fecha', '')
    
    empresas = Empresa.objects.annotate(
        total_solicitudes=Count('solicitud')
    )
    
    if search:
        empresas = empresas.filter(
            Q(nombre__icontains=search) |
            Q(nit__icontains=search) |
            Q(contacto__icontains=search) |
            Q(correo__icontains=search)
        )
    
    if municipio:
        empresas = empresas.filter(municipio__icontains=municipio)
    
    if min_trabajadores:
        try:
            empresas = empresas.filter(numero_trabajadores__gte=int(min_trabajadores))
        except ValueError:
            pass
    
    if rango_fecha:
        fecha_inicio, fecha_fin = obtener_rango_fechas(rango_fecha)
        if fecha_inicio:
            empresas = empresas.filter(fecha_registro__gte=fecha_inicio)
        if fecha_fin:
            empresas = empresas.filter(fecha_registro__lte=fecha_fin)
    
    empresas = empresas.order_by('nombre')
    
    municipios = Empresa.objects.exclude(
        municipio__isnull=True
    ).exclude(
        municipio=''
    ).values_list('municipio', flat=True).distinct().order_by('municipio')
    
    total_empresas = empresas.count()
    total_solicitudes = sum(empresa.total_solicitudes for empresa in empresas)
    
    context = {
        'empresas': empresas,
        'municipios': municipios,
        'search': search,
        'municipio_filter': municipio,
        'min_trabajadores_filter': min_trabajadores,
        'rango_fecha': rango_fecha,
        'total_empresas': total_empresas,
        'total_solicitudes': total_solicitudes,
    }
    return render(request, 'empresas/listar_empresas.html', context)


@puede_editar_requerido
@require_http_methods(["GET", "POST"])
def crear_empresa(request):
    """Vista para crear una nueva empresa"""
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        nit = request.POST.get('nit', '').strip()
        contacto = request.POST.get('contacto', '').strip()
        correo = request.POST.get('correo', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        municipio = request.POST.get('municipio', '').strip()
        direccion = request.POST.get('direccion', '').strip()
        numero_trabajadores = request.POST.get('numero_trabajadores', '').strip()
        
        errores = []
        
        if not nombre:
            errores.append('⚠️ El nombre de la empresa es obligatorio')
        elif len(nombre) < 3:
            errores.append('⚠️ El nombre debe tener al menos 3 caracteres')
        elif Empresa.objects.filter(nombre__iexact=nombre).exists():
            errores.append(f'❌ Ya existe una empresa con el nombre "{nombre}"')
        
        if nit:
            nit_limpio = nit.replace(' ', '').replace('-', '')
            if not nit_limpio.isdigit():
                errores.append('❌ El NIT solo debe contener números')
            elif len(nit_limpio) < 9:
                errores.append('❌ El NIT debe tener al menos 9 dígitos')
            elif Empresa.objects.filter(nit=nit_limpio).exists():
                errores.append(f'❌ Ya existe una empresa con el NIT "{nit}"')
            else:
                nit = nit_limpio
        
        if correo:
            if '@' not in correo or '.' not in correo:
                errores.append('❌ El correo electrónico no es válido')
        
        if telefono:
            telefono_limpio = telefono.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not telefono_limpio.isdigit():
                errores.append('❌ El teléfono solo debe contener números')
            elif len(telefono_limpio) < 7:
                errores.append('❌ El teléfono debe tener al menos 7 dígitos')
            else:
                telefono = telefono_limpio
        
        if numero_trabajadores:
            try:
                num_trabajadores = int(numero_trabajadores)
                if num_trabajadores < 1:
                    errores.append('❌ El número de trabajadores debe ser mayor a 0')
            except ValueError:
                errores.append('❌ El número de trabajadores debe ser un número válido')
        
        if errores:
            for error in errores:
                messages.error(request, error)
            context = {
                'nombre': nombre, 'nit': nit, 'contacto': contacto,
                'correo': correo, 'telefono': telefono, 'municipio': municipio,
                'direccion': direccion, 'numero_trabajadores': numero_trabajadores,
            }
            return render(request, 'empresas/crear_empresa.html', context)
        
        try:
            with transaction.atomic():
                empresa = Empresa.objects.create(
                    nombre=nombre,
                    nit=nit if nit else '',
                    contacto=contacto if contacto else '',
                    correo=correo if correo else '',
                    telefono=telefono if telefono else '',
                    municipio=municipio if municipio else '',
                    direccion=direccion if direccion else '',
                    numero_trabajadores=int(numero_trabajadores) if numero_trabajadores else 0,
                )
            messages.success(request, f'✅ ¡Empresa "{empresa.nombre}" creada exitosamente!')
            return redirect('empresas:listar_empresas')
            
        except Exception as e:
            messages.error(request, f'❌ Error al crear la empresa: {str(e)}')
            context = {
                'nombre': nombre, 'nit': nit, 'contacto': contacto,
                'correo': correo, 'telefono': telefono, 'municipio': municipio,
                'direccion': direccion, 'numero_trabajadores': numero_trabajadores,
            }
            return render(request, 'empresas/crear_empresa.html', context)
    
    return render(request, 'empresas/crear_empresa.html')


@puede_editar_requerido
@require_http_methods(["GET", "POST"])
def editar_empresa(request, empresa_id):
    """Vista para editar una empresa"""
    empresa = get_object_or_404(Empresa, id=empresa_id)
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        nit = request.POST.get('nit', '').strip()
        contacto = request.POST.get('contacto', '').strip()
        correo = request.POST.get('correo', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        municipio = request.POST.get('municipio', '').strip()
        direccion = request.POST.get('direccion', '').strip()
        numero_trabajadores = request.POST.get('numero_trabajadores', '').strip()
        activo = request.POST.get('activo') == 'on'
        
        errores = []
        
        if not nombre:
            errores.append('⚠️ El nombre de la empresa es obligatorio')
        elif len(nombre) < 3:
            errores.append('⚠️ El nombre debe tener al menos 3 caracteres')
        elif Empresa.objects.filter(nombre__iexact=nombre).exclude(id=empresa_id).exists():
            errores.append(f'❌ Ya existe otra empresa con el nombre "{nombre}"')
        
        if nit:
            nit_limpio = nit.replace(' ', '').replace('-', '')
            if not nit_limpio.isdigit():
                errores.append('❌ El NIT solo debe contener números')
            elif len(nit_limpio) < 9:
                errores.append('❌ El NIT debe tener al menos 9 dígitos')
            elif Empresa.objects.filter(nit=nit_limpio).exclude(id=empresa_id).exists():
                errores.append(f'❌ Ya existe otra empresa con el NIT "{nit}"')
            else:
                nit = nit_limpio
        
        if correo:
            if '@' not in correo or '.' not in correo:
                errores.append('❌ El correo electrónico no es válido')
        
        if telefono:
            telefono_limpio = telefono.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not telefono_limpio.isdigit():
                errores.append('❌ El teléfono solo debe contener números')
            elif len(telefono_limpio) < 7:
                errores.append('❌ El teléfono debe tener al menos 7 dígitos')
            else:
                telefono = telefono_limpio
        
        if numero_trabajadores:
            try:
                num_trabajadores = int(numero_trabajadores)
                if num_trabajadores < 1:
                    errores.append('❌ El número de trabajadores debe ser mayor a 0')
            except ValueError:
                errores.append('❌ El número de trabajadores debe ser un número válido')
        
        if errores:
            for error in errores:
                messages.error(request, error)
            return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})
        
        try:
            with transaction.atomic():
                empresa.nombre = nombre
                empresa.nit = nit if nit else ''
                empresa.contacto = contacto if contacto else ''
                empresa.correo = correo if correo else ''
                empresa.telefono = telefono if telefono else ''
                empresa.municipio = municipio if municipio else ''
                empresa.direccion = direccion if direccion else ''
                empresa.numero_trabajadores = int(numero_trabajadores) if numero_trabajadores else 0
                empresa.activo = activo
                empresa.save()
            messages.success(request, f'✅ ¡Empresa "{empresa.nombre}" actualizada exitosamente!')
            return redirect('empresas:detalle_empresa', empresa_id=empresa.id)
            
        except Exception as e:
            messages.error(request, f'❌ Error al actualizar la empresa: {str(e)}')
            return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})
    
    return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})


@puede_ver_requerido
def detalle_empresa(request, empresa_id):
    """Vista para el detalle de una empresa"""
    empresa = get_object_or_404(
        Empresa.objects.annotate(total_solicitudes=Count('solicitud')),
        id=empresa_id
    )
    solicitudes = empresa.solicitud_set.select_related(
        'programa', 'instructor_asignado'
    ).order_by('-fecha_recepcion')

    context = {
        'empresa': empresa,
        'solicitudes_activas': solicitudes.exclude(estado='FINALIZADA'),
        'solicitudes_finalizadas': solicitudes.filter(estado='FINALIZADA'),
        'total_solicitudes': solicitudes.count(),
    }
    return render(request, 'empresas/detalle_empresa.html', context)


@puede_editar_requerido
@require_http_methods(["GET", "POST"])
def desactivar_empresa(request, empresa_id):
    """Vista para desactivar una empresa"""
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
        'empresa': empresa,
        'tiene_dependencias': empresa.solicitud_set.exclude(estado='FINALIZADA').exists(),
    }
    return render(request, 'empresas/desactivar_empresa.html', context)


@puede_editar_requerido
@require_http_methods(["GET", "POST"])
def eliminar_empresa(request, empresa_id):
    """Vista para eliminar permanentemente una empresa"""
    empresa = get_object_or_404(Empresa, id=empresa_id)
    total_solicitudes = empresa.solicitud_set.count()
    
    if request.method == 'POST':
        if total_solicitudes > 0:
            accion_solicitudes = request.POST.get('accion_solicitudes')
            
            if accion_solicitudes == 'eliminar':
                nombre_empresa = empresa.nombre
                with transaction.atomic():
                    empresa.solicitud_set.all().delete()
                    empresa.delete()
                messages.success(
                    request,
                    f'✅ Empresa "{nombre_empresa}" y sus {total_solicitudes} solicitud(es) eliminadas permanentemente'
                )
            elif accion_solicitudes == 'cancelar':
                messages.warning(request, f'⚠️ Eliminación cancelada.')
                return redirect('empresas:detalle_empresa', empresa_id=empresa.id)
            else:
                messages.error(request, '❌ Debes seleccionar qué hacer con las solicitudes asociadas')
                return render(request, 'empresas/eliminar_empresa.html', {
                    'empresa': empresa, 'total_solicitudes': total_solicitudes
                })
        else:
            nombre_empresa = empresa.nombre
            with transaction.atomic():
                empresa.delete()
            messages.success(request, f'✅ Empresa "{nombre_empresa}" eliminada exitosamente')
        
        return redirect('empresas:listar_empresas')
    
    return render(request, 'empresas/eliminar_empresa.html', {
        'empresa': empresa,
        'total_solicitudes': total_solicitudes,
    })