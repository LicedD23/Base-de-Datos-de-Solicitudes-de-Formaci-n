# instructores/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Instructor
from programas.models import Programa
from django.db.models import Count, Q


def listar_instructores(request):
    """Vista para listar todos los instructores"""
    search = request.GET.get('search', '')
    especialidad_id = request.GET.get('especialidad', '')
    activo = request.GET.get('activo', '')
    
    # Consulta base con anotaciones (contar solicitudes asignadas)
    instructores = Instructor.objects.prefetch_related('especialidad').annotate(
        total_solicitudes=Count('solicitud')
    )
    
    # Aplicar filtros
    if search:
        instructores = instructores.filter(
            Q(nombre__icontains=search) |
            Q(correo__icontains=search) |
            Q(telefono__icontains=search)
        )
    
    if especialidad_id:
        instructores = instructores.filter(especialidad__id=especialidad_id)
    
    if activo:
        instructores = instructores.filter(activo=(activo == 'true'))
    
    # Ordenar por nombre
    instructores = instructores.order_by('nombre')
    
    # Obtener todas las especialidades (programas) para el filtro
    especialidades = Programa.objects.filter(activo=True).order_by('nombre')
    
    # Calcular estadísticas
    total_instructores = instructores.count()
    instructores_activos = instructores.filter(activo=True).count()
    total_solicitudes = sum(instructor.total_solicitudes for instructor in instructores)
    
    context = {
        'instructores': instructores,
        'especialidades': especialidades,
        'search': search,
        'especialidad_filter': especialidad_id,
        'activo_filter': activo,
        'total_instructores': total_instructores,
        'instructores_activos': instructores_activos,
        'total_solicitudes': total_solicitudes,
    }
    return render(request, 'instructores/listar_instructores.html', context)


def detalle_instructor(request, instructor_id):
    """Vista para el detalle de un instructor"""
    instructor = get_object_or_404(
        Instructor.objects.prefetch_related('especialidad').annotate(
            total_solicitudes=Count('solicitud')
        ),
        id=instructor_id
    )
    
    # Obtener todas las solicitudes asignadas a este instructor
    solicitudes = instructor.solicitud_set.select_related(
        'empresa',
        'programa__area'
    ).order_by('-fecha_recepcion')
    
    # Separar por estado
    solicitudes_activas = solicitudes.exclude(estado='FINALIZADA')
    solicitudes_finalizadas = solicitudes.filter(estado='FINALIZADA')
    
    #Obtener especialidades del instructor
    especialidades = instructor.especialidad.all()
    
    context = {
        'instructor': instructor,
        'especialidades': especialidades,
        'solicitudes_activas': solicitudes_activas,
        'solicitudes_finalizadas': solicitudes_finalizadas,
        'total_solicitudes': solicitudes.count(),
    }
    return render(request, 'instructores/detalle_instructor.html',context)

def crear_instructor(request):
    """Vista para crear un nuevo instructor"""
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        telefono = request.POST.get('telefono')
        correo = request.POST.get('correo')
        activo = request.POST.get('activo') == 'on'
        especialidades_ids = request.POST.getlist('especialidades')
        
        #Validaciones
        if not all([nombre, telefono, correo]):
            messages.error(request, '⚠️ El nombre, telefono y correo son obligatorios')
            
            programas = Programa.objects.filter(activo=True).order_by('area__nombre', 'nombre')
            return render(request, 'instructores/crear_instructor.html', {
                'programas': programas,
                'nombre': nombre,
                'telefono': telefono,
                'correo': correo,
            })
        #validar que tenga al menos una especialidad
        if not especialidades_ids:
            messages.error(request,'⚠️ Debe seleccionar al menos una especialidad')
            programas = Programa.objects.filter(activo=True).order_by('area__nombre', 'nombre')
            return render(request, 'instructores/crear_instructor.html', {
                'programas': programas,
                'nombre': nombre,
                'telefono': telefono,
                'correo': correo,
            })
        #Verificar si ya existe un instructor con ese correo
        if Instructor.objects.filter(correo__iexact=correo).exists():
            messages.error(request,f' ❌ Ya existe un instructor con el correo "{correo}"')
            programas = programas = Programa.objects.filter(activo=True).order_by('area__nombre', 'nombre')
            return render(request, 'instructores/crear_instructor.html', {
                'programas': programas,
                'nombre': nombre,
                'telefono': telefono,
                'correo': correo,
            })
        
        try:
            #Crear el instructor
            instructor = Instructor.objects.create(
                nombre=nombre,
                telefono=telefono,
                correo=correo,
                activo=activo
            )
            
            #Asignar especialidades (relación ManyToMany)
            instructor.especialidad.set(especialidades_ids)
            
            messages.success(request, f'Instructor "{instructor.nombre}" creado exitosamente! Ya esta disponible en el  sistema.')
            return redirect('instructores:listar_instructores')
        except Exception as e:
            messages.error(request,f' ❌ Error al  crear el instructor: {str(e)}')
            
        #GET request
    programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
    return render(request, 'instructores/crear_instructor.html',{'programas': programas})
    
def editar_instructor(request, instructor_id):
    """Vista para editar un instructor existente"""
    instructor = get_object_or_404(Instructor, id=instructor_id)
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        telefono = request.POST.get('telefono')
        correo = request.POST.get('correo')
        activo = request.POST.get('activo') == 'on'
        especialidades_ids = request.POST.getlist('especialidades')
        
        # Validaciones
        if not all([nombre, telefono, correo]):
            messages.error(request, '⚠️ El nombre, teléfono y correo son obligatorios')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            especialidades_instructor = instructor.especialidad.values_list('id', flat=True)
            return render(request, 'instructores/editar_instructor.html', {
                'instructor': instructor,
                'programas': programas,
                'especialidades_instructor': list(especialidades_instructor),
            })
        
        # Validar que tenga al menos una especialidad
        if not especialidades_ids:
            messages.error(request, ' ⚠️ Debe seleccionar al menos una especialidad')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            especialidades_instructor = instructor.especialidad.values_list('id', flat=True)
            return render(request, 'instructores/editar_instructor.html', {
                'instructor': instructor,
                'programas': programas,
                'especialidades_instructor': list(especialidades_instructor),
            })
        
        # Verificar si ya existe otro instructor con ese correo
        if Instructor.objects.filter(correo__iexact=correo).exclude(id=instructor_id).exists():
            messages.error(request, f'❌ Ya existe otro instructor con el correo "{correo}"')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            especialidades_instructor = instructor.especialidad.values_list('id', flat=True)
            return render(request, 'instructores/editar_instructor.html', {
                'instructor': instructor,
                'programas': programas,
                'especialidades_instructor': list(especialidades_instructor),
            })
        
        try:
            # Actualizar el instructor
            instructor.nombre = nombre
            instructor.telefono = telefono
            instructor.correo = correo
            instructor.activo = activo
            instructor.save()
            
            # Actualizar especialidades
            instructor.especialidad.set(especialidades_ids)
            
            messages.success(request, f'✅ Instructor "{instructor.nombre}" actualizado exitosamente')
            return redirect('instructores:detalle_instructor', instructor_id=instructor.id)
        except Exception as e:
            messages.error(request, f'❌ Error al actualizar el instructor: {str(e)} actualizado exitosamente')
        
    # GET request
    programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
    especialidades_instructor = instructor.especialidad.values_list('id', flat=True)
    
    context = {
        'instructor': instructor,
        'programas': programas,
        'especialidades_instructor': list(especialidades_instructor),
    }
    return render(request, 'instructores/editar_instructor.html', context)

def desactivar_instructor(request, instructor_id):
    """Vista para desactivar un instructor"""
    instructor = get_object_or_404(Instructor, id=instructor_id)
    
    # Contar solicitudes activas asignadas
    solicitudes_activas = instructor.solicitud_set.exclude(estado='FINALIZADA').count()
    
    if request.method == 'POST':
        # Verificar si tiene solicitudes activas
        if solicitudes_activas > 0:
            reasignar = request.POST.get('reasignar')
            if reasignar == 'on':
                # Desasignar instructor de solicitudes activas
                instructor.solicitud_set.exclude(estado='FINALIZADA').update(instructor_asignado=None)
                
                messages.warning(
                    request,
                    f'{solicitudes_activas} solicitud(es) activa(s) fueron desasignadas del instructor'
                )
            else:
                # Si no marca la opción, no puede desactivar
                messages.error(
                    request,
                    'Debes confirmar la desasignación de las solicitudes activas para poder desactivar al instructor'
                )
                context = {
                    'instructor': instructor,
                    'solicitudes_activas': solicitudes_activas,
                }
                return render(request, 'instructores/desactivar_instructor.html', context)
        
        # Desactivar el instructor
        instructor.activo = False
        instructor.save()
        
        messages.success(request, f'Instructor "{instructor.nombre}" desactivado exitosamente')
        return redirect('instructores:listar_instructores')
    
    # GET request
    context = {
        'instructor': instructor,
        'solicitudes_activas': solicitudes_activas,
    }
    return render(request, 'instructores/desactivar_instructor.html', context)
    
            
    
            
            
                
                
            
        
            
            
            
        
        
        
        