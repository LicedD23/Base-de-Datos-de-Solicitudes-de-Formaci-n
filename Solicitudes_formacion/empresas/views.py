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

def detalle_empresa(request,empresa_id):
    """Vista para el  detalle de una empresa"""
    empresa= get_object_or_404(
        Empresa.objects.annotate(
            total_solicitudes=Count('solicitud')
        ),
        id=empresa_id
        )
        #Obtener todas las solicitudes de esta empresa
    solicitudes=empresa.solicitud_set.select_related(
        'programa_area',
        'instructor_asignado'
    ).order_by('-fecha_recepcion')
    
    #Separar por estado
    solicitudes_activas=solicitudes.exclude(estado='FINALIZADA')
    solicitudes_finalizadas=solicitudes.filter(estado='FINALIZADA')
    
    context={
        'empresa':empresa,
        'solicitudes_activas':solicitudes_activas,
        'solicitudes_finalizadas':solicitudes_finalizadas,
        'total_solicitudes':solicitudes.count(),
    }
    return render(request,'empresas_empresa.html',context)
            
        
        
    

        