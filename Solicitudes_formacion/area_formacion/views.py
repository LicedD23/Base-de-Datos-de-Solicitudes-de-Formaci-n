from django.shortcuts import render,redirect,get_object_or_404
from django.contrib import messages
from .models import Area 
from programas.models import Programa
from django.db.models import Count, Q

# Create your views here.


def listar_areas(request):
    """Vista para listar todas las áreas"""
    search = request.GET.get('search', '')
    activo = request.GET.get('activo', '')
    area_id = request.GET.get('area_id','')
    
    # Obtener TODAS las areas para el desplegable(sin filtrar)
    todas_areas = Area.objects.all().order_by('nombre')
    # Consulta base con anotaciones
    areas = Area.objects.annotate(
        total_programas=Count('programas')
    )

    # Aplicar filtros
    if search:
        areas = areas.filter(
            Q(nombre__icontains=search) |
            Q(descripcion__icontains=search)
        )
    if area_id:
        areas = areas.filter(id=area_id)
    if activo:
        areas = areas.filter(activo=(activo == 'true'))

    # Ordenar por nombre
    areas = areas.order_by('nombre')

    # Calcular estadísticas
    total_areas = areas.count()
    areas_activas = areas.filter(activo=True).count()
    
    
    # O si quieres contar solo los programas de las áreas filtradas:
    total_programas = Programa.objects.filter(area__in=areas).count()
    #Obtener el  area seleccionada para mostrar en  el  badge
    area_seleccionada =None
    if area_id:
        try:
            area_seleccionada = Area.objects.get(id=area_id)
        except Area.DoesNotExist:
            pass

    context = {
        'areas': areas,
        'todas_areas':todas_areas,
        'search': search,
        'activo_filter': activo,
        'area_filter': area_id,
        'area_seleccionada': area_seleccionada,
        'total_areas': total_areas,
        'areas_activas': areas_activas,
        'total_programas': total_programas,
    }
    return render(request, 'area_formacion/listar_areas.html', context)


def detalle_area(request,area_id):
    """Vista para el  detalle de un  area"""
    area=get_object_or_404(
        Area.objects.annotate(
            total_programas=Count('programas')
        ),
        id=area_id   
    )
    #Obtener todos los programas de esta area
    programas = area.programas.annotate(
        total_solicitudes=Count('solicitud')
    ).order_by('nombre')
    #Separar programas activos e inactivos
    programas_activos = programas.filter(activo=True)
    programas_inactivos = programas.filter(activo=False)
    
    context={
        'area':area,
        'programas_activos':programas_activos,
        'programas_inactivos':programas_inactivos,
    }
    return render(request,'area_formacion/detalle_area.html',context)

def crear_area(request):
    """Vista para crear una nueva area"""
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        descripcion = request.POST.get('descripcion', '')
        activo = request.POST.get('activo') == 'on'
        
        # Validaciones
        if not nombre:
            messages.error(request, '⚠️ El nombre es obligatorio')  # 👈 Agrega emoji
            return render(request, 'area_formacion/crear_area.html')

        # Verificar si ya existe un area con ese nombre
        if Area.objects.filter(nombre__iexact=nombre).exists():
            messages.error(request, f'❌ Ya existe un área con el nombre "{nombre}"')  # 👈 Agrega emoji
            return render(request, 'area_formacion/crear_area.html', {
                'nombre': nombre,
                'descripcion': descripcion
            })
        
        try:
            # Crear el area
            area = Area.objects.create(
                nombre=nombre,
                descripcion=descripcion,
                activo=activo
            )
            messages.success(
                request, 
                f'✅ ¡Área "{area.nombre}" creada exitosamente! Ya está disponible en el listado de áreas.'
            )
            return redirect('area_formacion:listar_areas')
        except Exception as e:
            messages.error(request, f'❌ Error al crear el área: {str(e)}')  # 👈 Agrega emoji
            return render(request, 'area_formacion/crear_area.html', {
                'nombre': nombre,
                'descripcion': descripcion
            })
    
    return render(request, 'area_formacion/crear_area.html')
            
def editar_area(request, area_id):
    """Vista para editar un area existente"""
    area = get_object_or_404(Area, id=area_id)
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        descripcion = request.POST.get('descripcion', '')
        activo = request.POST.get('activo') == 'on'
        
        if not nombre:
            messages.error(request, '⚠️ El nombre es obligatorio')
            return render(request, 'area_formacion/editar_area.html', {'area': area})
        
        if Area.objects.filter(nombre__iexact=nombre).exclude(id=area_id).exists():
            messages.error(request, f'❌ Ya existe otra área con el nombre "{nombre}"')
            return render(request, 'area_formacion/editar_area.html', {'area': area})
        
        try:
            area.nombre = nombre
            area.descripcion = descripcion
            area.activo = activo
            area.save()
            
            # 🎯 MENSAJE MEJORADO:
            messages.success(
                request, 
                f'✅ ¡Área "{area.nombre}" actualizada exitosamente! Los cambios ya están disponibles en el sistema.'
            )
            return redirect('area_formacion:detalle_area', area_id=area.id)
        except Exception as e:
            messages.error(request, f'❌ Error al actualizar el área: {str(e)}')
            return render(request, 'area_formacion/editar_area.html', {'area': area})
    
    return render(request, 'area_formacion/editar_area.html', {'area': area})

def desactivar_area(request, area_id):
    """Vista para desactivar un área y opcionalmente sus programas"""
    area = get_object_or_404(Area, id=area_id)
    
    # Contar cuántos programas tiene
    total_programas = area.programas.count()
    programas_activos = area.programas.filter(activo=True).count()
    
    if request.method == 'POST':
        # Desactivar el área en lugar de eliminar
        area.activo = False
        area.save()
        
        # También desactivar todos los programas de esta área si se marca la opción
        if request.POST.get('desactivar_programas') == 'on':
            programas_desactivados = area.programas.filter(activo=True).update(activo=False)
            messages.success(
                request, 
                f'Área "{area.nombre}" y sus {programas_desactivados} programas activos desactivados exitosamente'
            )
        else:
            messages.success(request, f'Área "{area.nombre}" desactivada exitosamente')
        
        return redirect('area_formacion:listar_areas')
    
    context = {
        'area': area,
        'total_programas': total_programas,
        'programas_activos': programas_activos
    }
    return render(request, 'area_formacion/desactivar_area.html', context)