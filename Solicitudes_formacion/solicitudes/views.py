from django.shortcuts import render
from django.db.models import Q, Count
from .models import Solicitud
from programas.models import Programa
from empresas.models import Empresa

# Create your views here.
def listar_solicitudes(request):
    """Vista para listar todas las solicitudes de formacion"""
    search= request.GET.get('search','')
    estado= request.GET.get('estado','')
    programa_id= request.GET.get('programa','')
    empresa_id= request.GET.get('empresa','')
    # Consulta base con relaciones
    solicitudes= Solicitud.objects.select_related(
        'empresa',
        'programa',
        'programa__area',
        'instructor_asignado',  
    ).all()
    #Aplicar filtros
    if search:
        solicitudes= solicitudes.filter(
            Q(empresa__nombre__icontains=search) |
            Q(programa__nombre__icontains=search)|
            Q(instructor_asignado_nombre_icontains=search)
        )
        
    if estado:
        solicitudes = solicitudes.filter(estado=estado)
    if programa_id:
        solicitudes = solicitudes.filter(programa_id=programa_id)
    if empresa_id:
        solicitudes = solicitudes.filter(empresa_id = empresa_id)
    
    #Ordenar por fecha de recepcion (mas recientes primero)
    solicitudes = solicitudes.order_by('-fecha_recepcion')
    
    #obtener datos para los filtros
    programas=  Programa.objects.filter(activo=True).select_related('area').order_by('nombre')
    empresas= Empresa.objects.all().order_by('nombre')
    
    #Calcular estadisticas
    total_solicitudes=solicitudes.count()
    solicitudes_recibidas=solicitudes.filter(estado='RECIBIDA').count()
    solicitudes_respondidas=solicitudes.filter(estado='RESPONDIDA').count()
    solicitudes_atendidas=solicitudes.filter(estado='ATENDIDA').count()
    solicitudes_finalizadas=solicitudes.filter(estado='FINALIZADA').count()
    
    #Estadisticas por estado
    stats_por_estado={
        'RECIBIDA':solicitudes_recibidas,
        'RESPONDIDA':solicitudes_respondidas,
        'ATENDIDA':solicitudes_atendidas,
        'FINALIZADA':solicitudes_finalizadas,
    }
    context={
        'solicitudes':solicitudes,
        'programas':programas,
        'empresas':empresas,
        'search':search,
        'estado_filter':estado,
        'programa_filter':programa_id,
        'empresa_filter':empresa_id,
        'total_solicitudes':total_solicitudes,
        'solicitudes_recibidas':solicitudes_recibidas,
        'solicitudes_respondidas':solicitudes_atendidas,
        'solicitudes_atendidas':solicitudes_atendidas,
        'solicitudes_finalizadas':solicitudes_finalizadas,
        'stats_por_estado':stats_por_estado,
        'ESTADO_CHOICES':Solicitud.ESTADO_CHOICES,     
    }
    return render(request, 'solicitudes/listar_solicitudes.html', context)
    
    
        
        
    
