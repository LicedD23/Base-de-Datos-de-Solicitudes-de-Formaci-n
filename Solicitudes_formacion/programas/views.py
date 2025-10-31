from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Programa, Area
from django.db.models import Count, Q


def listar_programas(request):
    """vistas para listar todos los programas"""
    # Obtener parametros de busqueda y filtros
    search = request.GET.get('search', '')
    area_id = request.GET.get('area', '')
    activo = request.GET.get('activo', '')
    
    # Consultar base con anotaciones (contar solicitudes solicitadas)
    programas = Programa.objects.select_related('area').annotate(
        total_solicitudes=Count('solicitud')   
    )
    
    # Aplicar filtros
    if search:
        programas = programas.filter(
            Q(nombre__icontains=search) | 
            Q(descripcion__icontains=search)
        )
    if area_id:
        programas = programas.filter(area_id=area_id)
    if activo:
        programas = programas.filter(activo=activo =='true')
    
    # Ordenar por area y nombre
    programas = programas.order_by('area__nombre','nombre')
    
    # Obtener todas las areas para el filtro
    areas = Area.objects.filter(activo=True).order_by('nombre')
    
    # Calcular estadísticas
    total_programas = Programa.objects.count()
    programas_activos = Programa.objects.filter(activo=True).count()
    total_areas = areas.count()
    
    context = {
        'programas': programas,
        'areas': areas,
        'search': search,
        'area_filter': area_id,
        'activo_filter': activo,
        'total_programas': total_programas,
        'programas_activos': programas_activos,
        'total_areas': total_areas,
    }
    return render(request, 'programas/listar_programas.html', context)
def detalle_programa(request,programa_id):
    """Vista para el  detalle de un programa"""
    programa = get_object_or_404(
        Programa.objects.select_related('area').annotate(
            total_solicitudes=Count('solicitud')
        ),
        id=programa_id
    )
    # obtener ultimas 5 solicitudes  de este programa
    solicitudes_recientes = programa.solicitud_set.select_related(
        'empresa', 'instructor_asignado'
    ).order_by('-fecha_recepcion')[:5]
    
    #obtener instructores que pueden  dar este programa
    instructores = programa.instructores.filter(activo=True)
    
    context ={
        'programa': programa,
        'solicitudes_recientes': solicitudes_recientes,
        'instructores':instructores,   
    }
    return render(request,'programas/detalle_programa.html',context)
    
def crear_programa(request):
    """vista para crear un nuevo programa"""
    areas = Area.objects.filter(activo=True).order_by('nombre')  # Inicializa areas
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        area_id = request.POST.get('area')
        descripcion = request.POST.get('descripcion', '')
        duracion_horas = request.POST.get('duracion_horas', '')
        activo = request.POST.get('activo') == 'on'
        
        # validaciones
        if not nombre or not area_id:
            messages.error(request, 'El nombre y el área son obligatorios.')
            return render(request, 'programas/crear_programa.html', {'areas': areas})
        
        try:
            area = Area.objects.get(id=area_id)
            # Crear Programa
            programa = Programa.objects.create(
                nombre=nombre,
                area=area,
                descripcion=descripcion,
                duracion_horas=int(duracion_horas) if duracion_horas else None,
                activo=activo
            )
            messages.success(request, f'Programa "{programa.nombre}" creado exitosamente')
            return redirect('detalle_programa', programa_id=programa.id)
        except Area.DoesNotExist:
            messages.error(request, 'El área seleccionada no existe')
        except Exception as e:
            messages.error(request, f'Error al crear el programa: {str(e)}')

    return render(request, 'programas/crear_programa.html', {'areas': areas})
            
def editar_programa(request, programa_id):
    """vista para editar un programa existente"""
    programa = get_object_or_404(Programa, id=programa_id)
    
    # IMPORTANTE: Inicializar areas ANTES del if
    areas = Area.objects.filter(activo=True).order_by('nombre')
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        area_id = request.POST.get('area')
        descripcion = request.POST.get('descripcion', '')
        duracion_horas = request.POST.get('duracion_horas', '')
        activo = request.POST.get('activo') == 'on'
        
        # validaciones 
        if not nombre or not area_id:
            messages.error(request, "El nombre y el área son obligatorios")
            return render(request, 'programas/editar_programa.html', {
                'programa': programa,
                'areas': areas
            })
        
        try:
            area = Area.objects.get(id=area_id)
            
            # Actualizar el programa
            programa.nombre = nombre
            programa.area = area
            programa.descripcion = descripcion
            programa.duracion_horas = int(duracion_horas) if duracion_horas else None
            programa.activo = activo
            programa.save()
            
            messages.success(request, f'Programa "{programa.nombre}" actualizado exitosamente')
            return redirect('programas:detalle_programa', programa_id=programa.id)
        
        except Area.DoesNotExist:
            messages.error(request, 'El área seleccionada no existe')
        except Exception as e:
            messages.error(request, f'Error al actualizar el programa: {str(e)}')
    
    # GET request - retornar el contexto con areas
    return render(request, 'programas/editar_programa.html', {
        'programa': programa,
        'areas': areas
    })
def desactivar_programa(request, programa_id):
    """Vista para desactivar un programa"""
    programa = get_object_or_404(Programa, id=programa_id)
    
    # Contar solicitudes asociadas al programa
    total_solicitudes = programa.solicitud_set.count()
    solicitudes_activas = programa.solicitud_set.filter(
        estado__in=['pendiente', 'aprobada']
    ).count()
    
    if request.method == 'POST':
        # En lugar de eliminar, solo se desactiva
        programa.activo = False
        programa.save()
        
        messages.success(
            request, 
            f'Programa "{programa.nombre}" desactivado exitosamente'
        )
        return redirect('programas:listar_programas')
    
    context = {
        'programa': programa,
        'total_solicitudes': total_solicitudes,
        'solicitudes_activas': solicitudes_activas,
    }
    return render(request, 'programas/desactivar_programa.html', context)
    
        
    
    

