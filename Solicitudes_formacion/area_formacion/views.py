from django.shortcuts import render,redirect,get_object_or_404
from django.contrib import messages
from .models import Programa, Area
from django.db.models import Count, Q

# Create your views here.
def listar_areas(request):
    """Vista para listar todas las areas"""
    #Obtener parametros de busqyeda y filtro
    search = request.GET.get('search','')
    activo = request.GET.get('activo','')
    #Consulta base con anotaciones (contar programas por area)
    areas = Area.objects.annotate(
        total_programas=Count('programa')
    ) 
    #Aplicar filtros
    if search:
        areas = areas.filter(
            Q(nombre__icontains=search)|
            Q(descripcion__icontains=search)
            )
        if activo:
            areas = areas.filter(activo=activo=='true')
        #Ordenar por nombre
        areas = areas.order_by('nombre')
        
        context={
            'areas':areas,
            'search':search,
            'activo_filter':activo,
        }
        return render(request,'area_formacion/areas/listar_areas.html',context)
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
    return render(request,'area_formacion/areas/detalle_area.html',context)

def crear_area(request):
    """vista para crear una nueva area"""
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        descripcion = request.POST.get('descripcion','')
        activo = request.POST.get('activo')=='on'
        #Validaciones
        if not nombre:
            messages.error(request,'El nombre es obligatorio')
            return render(request,'area_formacion/areas/crear_area.html')

        #verificar si ya existe un  area con ese nombre
        if Area.objects.filter(nombre__iexact=nombre).exists():
            messages.error(request,f'Ya existe un area con el nombre "{nombre}"')
            return render(request,'area_formacion/areas/crear_area.html',{
                'nombre':nombre,
                'descripcion':descripcion
            })
        try:
        #crear el  area
            area = Area.objects.create(
                nombre=nombre,
                descripcion=descripcion,
                activo=activo
            )
            messages.success(request,f'Area"{area.nombre}"creada exitosamente')
            return redirect('detalle_area',area_id=area.id)
        except Exception as e:
            messages.error(request,f'Error al crear el  area:{str(e)}')
        #GET request
        return render(request,'area_formacion/areas/crear_area.html')

def editar_area(request,area_id):
    """vista para editar un  area existente"""
    area = get_object_or_404(Area, id=area_id)
    
    if request.method=='POST':
        nombre = request.POST.get('nombre')
        descripcion = request.POST.get('descripcion','')
        activo = request.POST.get('activo')=='on'
        
        #Validaciones
        if not nombre:
            messages.error(request,'El nombre es obligatorio')
            return render(request,'area_formacion/areas/editar_area.html',{'area':area})
        #verificar si ya existe otra area con ese nombre
        if area.objects.filter(nombre__iexact=nombre).exclude(id=area_id).exists():
            messages.error(request,f'Ya existe otra area con el  nombre "{nombre}"')
            return render(request,'area_formacion/areas/editar_area.html',{'area':area})
        
        try:
            #actualiza el  area
            area.nombre = nombre
            area.descripcion= descripcion
            area.activo = activo
            area.save()
            messages.success(request,f'Area"{area.nombre}"actualizada exitosamente')
            return redirect('detalle_area',area_id=area.id)
        except Exception as e:
            messages.error(request,f'Error al  actualizar el  area:{str(e)}')
def eliminar_area(request,area_id):
    """vista para eliminar un  area"""
    area= get_object_or_404(Area,id=area_id)
    #contar cuantos programas tienen 
    total_programas = area.programas.count()
    programas_activos = area.programas.filter(activo=True).count()
    if request.method == 'POST':
        #en lugar d eeliminar solo  se desactivan
        area.activo =False
        area.save()
        #Tambien desactivar todos los programas de esta area
        if request.POST.get('desactivar_programas')=='on':
            area.programas.update(activo=False)
            messages.success(request,f'Area"{area.nombre}") y sus {total_programas} programas desactivados exitosamente')
        else:
            messages.success(request,f'Area"{area.nombre}"desactivada')
        return redirect('listar_areas')
    context={
        'area':area,
        'total_programas':total_programas,
        'programas_activos':programas_activos
    }
    return render(request,'area_formacion/areas/eliminar_area.html',context)