from datetime import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Empresa
from django.db.models import Q, Count
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.http import require_http_methods
from django.db import transaction


def listar_empresas(request):
    """Vista para listar todas las empresas"""
    search = request.GET.get('search', '')
    municipio = request.GET.get('municipio', '')
    min_trabajadores = request.GET.get('min_trabajadores', '')
    
    # Consulta base con anotaciones (contar solicitudes por empresa)
    empresas = Empresa.objects.annotate(
        total_solicitudes=Count('solicitud')
    )
    
    # Aplicar filtros
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
    
    # Ordenar por nombre
    empresas = empresas.order_by('nombre')
    
    # Obtener lista de municipios únicos para el filtro (excluir vacíos)
    municipios = Empresa.objects.exclude(
        municipio__isnull=True
    ).exclude(
        municipio=''
    ).values_list('municipio', flat=True).distinct().order_by('municipio')
    
    # Calcular estadísticas
    total_empresas = empresas.count()
    total_solicitudes = sum(empresa.total_solicitudes for empresa in empresas)
    
    context = {
        'empresas': empresas,
        'municipios': municipios,
        'search': search,
        'municipio_filter': municipio,
        'min_trabajadores_filter': min_trabajadores,
        'total_empresas': total_empresas,
        'total_solicitudes': total_solicitudes,
    }
    return render(request, 'empresas/listar_empresas.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def crear_empresa(request):
    """Vista para crear una nueva empresa"""
    
    if request.method == 'POST':
        # Obtener datos del formulario
        nombre = request.POST.get('nombre', '').strip()
        nit = request.POST.get('nit', '').strip()
        contacto = request.POST.get('contacto', '').strip()
        correo = request.POST.get('correo', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        municipio = request.POST.get('municipio', '').strip()
        direccion = request.POST.get('direccion', '').strip()
        numero_trabajadores = request.POST.get('numero_trabajadores', '').strip()
        
        # Validaciones
        errores = []
        
        # Validar nombre (obligatorio)
        if not nombre:
            errores.append('⚠️ El nombre de la empresa es obligatorio')  # ✅ EMOJI
        elif len(nombre) < 3:
            errores.append('⚠️ El nombre debe tener al menos 3 caracteres')  # ✅ EMOJI
        elif Empresa.objects.filter(nombre__iexact=nombre).exists():
            errores.append(f'❌ Ya existe una empresa con el nombre "{nombre}"')  # ✅ EMOJI
        
        # Validar NIT (opcional, pero si se proporciona debe ser válido)
        if nit:
            nit_limpio = nit.replace(' ', '').replace('-', '')
            if not nit_limpio.isdigit():
                errores.append('❌ El NIT solo debe contener números')  # ✅ EMOJI
            elif len(nit_limpio) < 9:
                errores.append('❌ El NIT debe tener al menos 9 dígitos')  # ✅ EMOJI
            elif Empresa.objects.filter(nit=nit_limpio).exists():
                errores.append(f'❌ Ya existe una empresa con el NIT "{nit}"')  # ✅ EMOJI
            else:
                nit = nit_limpio
        
        # Validar correo (opcional, pero si se proporciona debe ser válido)
        if correo:
            if '@' not in correo or '.' not in correo:
                errores.append('❌ El correo electrónico no es válido')  # ✅ EMOJI
        
        # Validar teléfono (opcional, pero si se proporciona debe ser válido)
        if telefono:
            telefono_limpio = telefono.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not telefono_limpio.isdigit():
                errores.append('❌ El teléfono solo debe contener números')  # ✅ EMOJI
            elif len(telefono_limpio) < 7:
                errores.append('❌ El teléfono debe tener al menos 7 dígitos')  # ✅ EMOJI
            else:
                telefono = telefono_limpio
        
        # Validar número de trabajadores (opcional)
        if numero_trabajadores:
            try:
                num_trabajadores = int(numero_trabajadores)
                if num_trabajadores < 1:
                    errores.append('❌ El número de trabajadores debe ser mayor a 0')  # ✅ EMOJI
            except ValueError:
                errores.append('❌ El número de trabajadores debe ser un número válido')  # ✅ EMOJI
        
        # Si hay errores, mostrarlos y devolver el formulario
        if errores:
            for error in errores:
                messages.error(request, error)
            
            context = {
                'nombre': nombre,
                'nit': nit,
                'contacto': contacto,
                'correo': correo,
                'telefono': telefono,
                'municipio': municipio,
                'direccion': direccion,
                'numero_trabajadores': numero_trabajadores,
            }
            return render(request, 'empresas/crear_empresa.html', context)
        
        # Crear la empresa
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
            
            # ✅ MENSAJE MEJORADO:
            messages.success(
                request, 
                f'✅ ¡Empresa "{empresa.nombre}" creada exitosamente! Ya está disponible en el sistema.'
            )
            return redirect('empresas:listar_empresas')  # 👈 Redirige al listado
            
        except Exception as e:
            messages.error(request, f'❌ Error al crear la empresa: {str(e)}')  # ✅ EMOJI
            
            context = {
                'nombre': nombre,
                'nit': nit,
                'contacto': contacto,
                'correo': correo,
                'telefono': telefono,
                'municipio': municipio,
                'direccion': direccion,
                'numero_trabajadores': numero_trabajadores,
            }
            return render(request, 'empresas/crear_empresa.html', context)
    
    # GET request - mostrar formulario vacío
    return render(request, 'empresas/crear_empresa.html')


@login_required
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
        
        # Validaciones
        errores = []
        
        # Validar nombre (obligatorio)
        if not nombre:
            errores.append('⚠️ El nombre de la empresa es obligatorio')  # ✅ EMOJI
        elif len(nombre) < 3:
            errores.append('⚠️ El nombre debe tener al menos 3 caracteres')  # ✅ EMOJI
        elif Empresa.objects.filter(nombre__iexact=nombre).exclude(id=empresa_id).exists():
            errores.append(f'❌ Ya existe otra empresa con el nombre "{nombre}"')  # ✅ EMOJI
        
        # Validar NIT (opcional, pero si se proporciona debe ser válido)
        if nit:
            nit_limpio = nit.replace(' ', '').replace('-', '')
            if not nit_limpio.isdigit():
                errores.append('❌ El NIT solo debe contener números')  # ✅ EMOJI
            elif len(nit_limpio) < 9:
                errores.append('❌ El NIT debe tener al menos 9 dígitos')  # ✅ EMOJI
            elif Empresa.objects.filter(nit=nit_limpio).exclude(id=empresa_id).exists():
                errores.append(f'❌ Ya existe otra empresa con el NIT "{nit}"')  # ✅ EMOJI
            else:
                nit = nit_limpio
        
        # Validar correo (opcional, pero si se proporciona debe ser válido)
        if correo:
            if '@' not in correo or '.' not in correo:
                errores.append('❌ El correo electrónico no es válido')  # ✅ EMOJI
        
        # Validar teléfono (opcional, pero si se proporciona debe ser válido)
        if telefono:
            telefono_limpio = telefono.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not telefono_limpio.isdigit():
                errores.append('❌ El teléfono solo debe contener números')  # ✅ EMOJI
            elif len(telefono_limpio) < 7:
                errores.append('❌ El teléfono debe tener al menos 7 dígitos')  # ✅ EMOJI
            else:
                telefono = telefono_limpio
        
        # Validar número de trabajadores (opcional)
        if numero_trabajadores:
            try:
                num_trabajadores = int(numero_trabajadores)
                if num_trabajadores < 1:
                    errores.append('❌ El número de trabajadores debe ser mayor a 0')  # ✅ EMOJI
            except ValueError:
                errores.append('❌ El número de trabajadores debe ser un número válido')  # ✅ EMOJI
        
        # Si hay errores, mostrarlos
        if errores:
            for error in errores:
                messages.error(request, error)
            return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})
        
        # Actualizar la empresa
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
            
            # ✅ MENSAJE MEJORADO:
            messages.success(
                request, 
                f'✅ ¡Empresa "{empresa.nombre}" actualizada exitosamente! Los cambios ya están disponibles en el sistema.'
            )
            return redirect('empresas:detalle_empresa', empresa_id=empresa.id)
            
        except Exception as e:
            messages.error(request, f'❌ Error al actualizar la empresa: {str(e)}')  # ✅ EMOJI
            return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})
    
    return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})

def detalle_empresa(request, empresa_id):
    """Vista para el detalle de una empresa"""
    empresa = get_object_or_404(
        Empresa.objects.annotate(
            total_solicitudes=Count('solicitud')
        ),
        id=empresa_id
    )

    # Obtener todas las solicitudes de esta empresa
    solicitudes = empresa.solicitud_set.select_related(
        'programa',
        'instructor_asignado'
    ).order_by('-fecha_recepcion')

    # Separar por estado
    solicitudes_activas = solicitudes.exclude(estado='FINALIZADA')
    solicitudes_finalizadas = solicitudes.filter(estado='FINALIZADA')

    # Imprimir conteos para depuración
    print("Total de solicitudes:", solicitudes.count())
    print("Solicitudes activas:", solicitudes_activas.count())
    print("Solicitudes finalizadas:", solicitudes_finalizadas.count())

    context = {
        'empresa': empresa,
        'solicitudes_activas': solicitudes_activas,
        'solicitudes_finalizadas': solicitudes_finalizadas,
        'total_solicitudes': solicitudes.count(),
    }
    return render(request, 'empresas/detalle_empresa.html', context)
@login_required
@permission_required('empresas.delete_empresa', raise_exception=True)
@require_http_methods(["GET", "POST"])
def desactivar_empresa(request, empresa_id):
    """Vista para desactivar una empresa"""
    empresa = get_object_or_404(Empresa, id=empresa_id)
    
    if request.method == 'POST':
        # Verificar si ya está desactivada
        if not empresa.activo:
            messages.warning(request, f'⚠️ La empresa "{empresa.nombre}" ya está desactivada')  # ✅ EMOJI
            return redirect('empresas:listar_empresas')
        
        # Usar transacción para garantizar atomicidad
        with transaction.atomic():
            empresa.activo = False
            empresa.save()
        
        # ✅ MENSAJE MEJORADO:
        messages.success(request, f'✅ Empresa "{empresa.nombre}" desactivada exitosamente')
        return redirect('empresas:listar_empresas')
    
    # Calcular dependencias directamente aquí
    tiene_dependencias = empresa.solicitud_set.exclude(estado='FINALIZADA').exists()
    
    context = {
        'empresa': empresa,
        'tiene_dependencias': tiene_dependencias,
    }
    return render(request, 'empresas/desactivar_empresa.html', context)