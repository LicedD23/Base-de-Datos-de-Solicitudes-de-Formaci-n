from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Empresa
from django.db.models import Q,Count

# Create your views here.
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
    
    # Obtener lista de municipios únicos para el filtro
    municipios = Empresa.objects.values_list('municipio', flat=True).distinct().order_by('municipio')
    
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
    return render(request,'empresas/listar_empresas.html',context)

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

def editar_empresa(request, empresa_id):
    """vista para editar una empresa"""
    empresa = get_object_or_404(Empresa, id=empresa_id)
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        contacto = request.POST.get('contacto')
        correo = request.POST.get('correo')
        telefono = request.POST.get('telefono')
        municipio = request.POST.get('municipio')
        direccion = request.POST.get('direccion')
        numero_trabajadores = request.POST.get('numero_trabajadores')
        
        if not nombre:
            messages.error(request, 'El nombre es obligatorio')
            return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})
        
        if Empresa.objects.filter(nombre__iexact=nombre).exclude(id=empresa_id).exists():
            messages.error(request, f'Ya existe otra empresa con el nombre "{nombre}"')
            return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})
        
        try:
            empresa.nombre = nombre
            empresa.contacto = contacto
            empresa.correo = correo
            empresa.telefono = telefono
            empresa.municipio = municipio
            empresa.direccion = direccion
            empresa.numero_trabajadores = numero_trabajadores
            empresa.save()
            messages.success(request, f'Empresa "{empresa.nombre}" actualizada exitosamente')
            return redirect('empresas:detalle_empresa', empresa_id=empresa.id)
        except Exception as e:
            messages.error(request, f'Error al actualizar la empresa: {str(e)}')
            return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})
    
    return render(request, 'empresas/editar_empresa.html', {'empresa': empresa})
    
            
        
        
    

        