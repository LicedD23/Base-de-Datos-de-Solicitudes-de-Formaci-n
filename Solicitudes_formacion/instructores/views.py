# instructores/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Instructor
from programas.models import Programa
from django.db.models import Count, Q
from core.management.decorators import puede_ver_requerido, puede_editar_requerido



@puede_ver_requerido
def listar_instructores(request):
    """Vista para listar todos los instructores"""
    search = request.GET.get('search', '')
    especialidad_id = request.GET.get('especialidad', '')
    activo = request.GET.get('activo', '')
    disponibilidad_filter = request.GET.get('disponibilidad', '')

    instructores = Instructor.objects.prefetch_related('especialidad').annotate(
        total_solicitudes=Count('solicitud')
    )

    if search:
        instructores = instructores.filter(
            Q(nombre__icontains=search) |
            Q(correo__icontains=search) |
            Q(telefono__icontains=search) |
            Q(cedula__icontains=search)
        )

    if especialidad_id:
        instructores = instructores.filter(especialidad__id=especialidad_id)

    if activo:
        instructores = instructores.filter(activo=(activo == 'true'))

    instructores = instructores.order_by('nombre')

    # ── Calcular disponibilidad de cada instructor ───────────────────────────
    from django.utils import timezone
    hoy = timezone.now().date()

    instructores_con_disponibilidad = []
    for instructor in instructores:
        solicitudes_programadas = instructor.solicitud_set.filter(
            fecha_atencion__isnull=False,
        ).exclude(estado='FINALIZADA')

        ocupado_hoy = False
        formaciones_activas = []

        for sol in solicitudes_programadas.select_related('empresa', 'programa'):
            fecha_inicio = sol.fecha_atencion.date()
            # ── Campo correcto: fecha_fin_formacion ──
            fecha_fin = sol.fecha_fin_formacion if sol.fecha_fin_formacion else None

            if fecha_inicio <= hoy and (fecha_fin is None or fecha_fin >= hoy):
                ocupado_hoy = True
                formaciones_activas.append(sol)

        proxima = None
        if not ocupado_hoy:
            proxima = instructor.solicitud_set.filter(
                fecha_atencion__isnull=False,
                fecha_atencion__date__gt=hoy,
            ).exclude(estado='FINALIZADA').order_by('fecha_atencion').first()

        instructores_con_disponibilidad.append({
            'instructor':          instructor,
            'ocupado':             ocupado_hoy,
            'formaciones_activas': formaciones_activas,
            'proxima':             proxima,
        })

    if disponibilidad_filter == 'libre':
        instructores_con_disponibilidad = [d for d in instructores_con_disponibilidad if not d['ocupado']]
    elif disponibilidad_filter == 'ocupado':
        instructores_con_disponibilidad = [d for d in instructores_con_disponibilidad if d['ocupado']]

    especialidades = Programa.objects.filter(activo=True).order_by('nombre')

    total_instructores   = len(instructores_con_disponibilidad)
    instructores_activos = sum(1 for d in instructores_con_disponibilidad if d['instructor'].activo)
    total_solicitudes    = sum(d['instructor'].total_solicitudes for d in instructores_con_disponibilidad)
    disponibles_hoy      = sum(1 for d in instructores_con_disponibilidad if not d['ocupado'] and d['instructor'].activo)
    ocupados_hoy         = sum(1 for d in instructores_con_disponibilidad if d['ocupado'])

    context = {
        'instructores_con_disponibilidad': instructores_con_disponibilidad,
        'especialidades':        especialidades,
        'search':                search,
        'especialidad_filter':   especialidad_id,
        'activo_filter':         activo,
        'disponibilidad_filter': disponibilidad_filter,
        'total_instructores':    total_instructores,
        'instructores_activos':  instructores_activos,
        'total_solicitudes':     total_solicitudes,
        'disponibles_hoy':       disponibles_hoy,
        'ocupados_hoy':          ocupados_hoy,
        'hoy':                   hoy,
    }
    return render(request, 'instructores/listar_instructores.html', context)



@puede_ver_requerido
def detalle_instructor(request, instructor_id):
    """Vista para el detalle de un instructor"""
    instructor = get_object_or_404(
        Instructor.objects.prefetch_related('especialidad').annotate(
            total_solicitudes=Count('solicitud')
        ),
        id=instructor_id
    )

    solicitudes = instructor.solicitud_set.select_related(
        'empresa',
        'programa__area'
    ).order_by('-fecha_recepcion')

    solicitudes_activas     = solicitudes.exclude(estado='FINALIZADA')
    solicitudes_finalizadas = solicitudes.filter(estado='FINALIZADA')

    from django.utils import timezone
    hoy = timezone.now().date()

    programaciones = solicitudes.filter(
        fecha_atencion__isnull=False
    ).order_by('fecha_atencion')

    programaciones_activas  = []
    programaciones_futuras  = []
    programaciones_pasadas  = []

    for sol in programaciones:
        fecha_inicio = sol.fecha_atencion.date() if sol.fecha_atencion else None
        # ── Campo correcto: fecha_fin_formacion ──
        fecha_fin = sol.fecha_fin_formacion if sol.fecha_fin_formacion else None

        if not fecha_inicio:
            continue

        if fecha_fin:
            if fecha_inicio <= hoy <= fecha_fin:
                programaciones_activas.append(sol)
            elif fecha_inicio > hoy:
                programaciones_futuras.append(sol)
            else:
                programaciones_pasadas.append(sol)
        else:
            # Sin fecha fin: si el inicio ya pasó → en curso
            if fecha_inicio <= hoy:
                programaciones_activas.append(sol)
            else:
                programaciones_futuras.append(sol)

    especialidades = instructor.especialidad.all()

    context = {
        'instructor':              instructor,
        'especialidades':          especialidades,
        'solicitudes_activas':     solicitudes_activas,
        'solicitudes_finalizadas': solicitudes_finalizadas,
        'total_solicitudes':       solicitudes.count(),
        'programaciones_activas':  programaciones_activas,
        'programaciones_futuras':  programaciones_futuras,
        'programaciones_pasadas':  programaciones_pasadas,
        'hoy':                     hoy,
    }
    return render(request, 'instructores/detalle_instructor.html', context)


@puede_editar_requerido
def crear_instructor(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        cedula = request.POST.get('cedula')
        telefono = request.POST.get('telefono')
        correo = request.POST.get('correo')
        activo = request.POST.get('activo') == 'on'
        especialidades_ids = request.POST.getlist('especialidades')

        if not all([nombre, cedula, telefono, correo]):
            messages.error(request, '⚠️ El nombre, cédula, teléfono y correo son obligatorios')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            return render(request, 'instructores/crear_instructor.html', {
                'programas': programas, 'nombre': nombre,
                'cedula': cedula, 'telefono': telefono, 'correo': correo,
            })

        if not especialidades_ids:
            messages.error(request, '⚠️ Debe seleccionar al menos una especialidad')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            return render(request, 'instructores/crear_instructor.html', {
                'programas': programas, 'nombre': nombre,
                'cedula': cedula, 'telefono': telefono, 'correo': correo,
            })

        if Instructor.objects.filter(correo__iexact=correo).exists():
            messages.error(request, f'❌ Ya existe un instructor con el correo "{correo}"')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            return render(request, 'instructores/crear_instructor.html', {
                'programas': programas, 'nombre': nombre,
                'cedula': cedula, 'telefono': telefono, 'correo': correo,
            })

        if Instructor.objects.filter(cedula=cedula).exists():
            messages.error(request, f'❌ Ya existe un instructor con la cédula "{cedula}"')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            return render(request, 'instructores/crear_instructor.html', {
                'programas': programas, 'nombre': nombre,
                'cedula': cedula, 'telefono': telefono, 'correo': correo,
            })

        try:
            instructor = Instructor.objects.create(
                nombre=nombre, cedula=cedula,
                telefono=telefono, correo=correo, activo=activo
            )
            instructor.especialidad.set(especialidades_ids)
            messages.success(request, f'✅ Instructor "{instructor.nombre}" creado exitosamente!')
            return redirect('instructores:listar_instructores')
        except Exception as e:
            messages.error(request, f'❌ Error al crear el instructor: {str(e)}')

    programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
    return render(request, 'instructores/crear_instructor.html', {'programas': programas})


@puede_editar_requerido
def editar_instructor(request, instructor_id):
    instructor = get_object_or_404(Instructor, id=instructor_id)

    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        cedula = request.POST.get('cedula')
        telefono = request.POST.get('telefono')
        correo = request.POST.get('correo')
        activo = request.POST.get('activo') == 'on'
        especialidades_ids = request.POST.getlist('especialidades')

        if not all([nombre, cedula, telefono, correo]):
            messages.error(request, '⚠️ El nombre, cédula, teléfono y correo son obligatorios')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            return render(request, 'instructores/editar_instructor.html', {
                'instructor': instructor, 'programas': programas,
                'especialidades_instructor': list(instructor.especialidad.values_list('id', flat=True)),
            })

        if not especialidades_ids:
            messages.error(request, '⚠️ Debe seleccionar al menos una especialidad')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            return render(request, 'instructores/editar_instructor.html', {
                'instructor': instructor, 'programas': programas,
                'especialidades_instructor': list(instructor.especialidad.values_list('id', flat=True)),
            })

        if Instructor.objects.filter(correo__iexact=correo).exclude(id=instructor_id).exists():
            messages.error(request, f'❌ Ya existe otro instructor con el correo "{correo}"')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            return render(request, 'instructores/editar_instructor.html', {
                'instructor': instructor, 'programas': programas,
                'especialidades_instructor': list(instructor.especialidad.values_list('id', flat=True)),
            })

        if Instructor.objects.filter(cedula=cedula).exclude(id=instructor_id).exists():
            messages.error(request, f'❌ Ya existe otro instructor con la cédula "{cedula}"')
            programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
            return render(request, 'instructores/editar_instructor.html', {
                'instructor': instructor, 'programas': programas,
                'especialidades_instructor': list(instructor.especialidad.values_list('id', flat=True)),
            })

        try:
            instructor.nombre = nombre
            instructor.cedula = cedula
            instructor.telefono = telefono
            instructor.correo = correo
            instructor.activo = activo
            instructor.save()
            instructor.especialidad.set(especialidades_ids)
            messages.success(request, f'✅ Instructor "{instructor.nombre}" actualizado exitosamente')
            return redirect('instructores:detalle_instructor', instructor_id=instructor.id)
        except Exception as e:
            messages.error(request, f'❌ Error al actualizar el instructor: {str(e)}')

    programas = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
    especialidades_instructor = instructor.especialidad.values_list('id', flat=True)
    return render(request, 'instructores/editar_instructor.html', {
        'instructor': instructor,
        'programas': programas,
        'especialidades_instructor': list(especialidades_instructor),
    })


@puede_editar_requerido
def desactivar_instructor(request, instructor_id):
    """Vista para desactivar un instructor"""
    instructor = get_object_or_404(Instructor, id=instructor_id)
    solicitudes_activas = instructor.solicitud_set.exclude(estado='FINALIZADA').count()

    if request.method == 'POST':
        if solicitudes_activas > 0:
            reasignar = request.POST.get('reasignar')
            if reasignar == 'on':
                instructor.solicitud_set.exclude(estado='FINALIZADA').update(instructor_asignado=None)
                messages.warning(request, f'{solicitudes_activas} solicitud(es) activa(s) fueron desasignadas del instructor')
            else:
                messages.error(request, 'Debes confirmar la desasignación de las solicitudes activas')
                return render(request, 'instructores/desactivar_instructor.html', {
                    'instructor': instructor, 'solicitudes_activas': solicitudes_activas,
                })

        instructor.activo = False
        instructor.save()
        messages.success(request, f'Instructor "{instructor.nombre}" desactivado exitosamente')
        return redirect('instructores:listar_instructores')

    return render(request, 'instructores/desactivar_instructor.html', {
        'instructor': instructor, 'solicitudes_activas': solicitudes_activas,
    })


@puede_editar_requerido
def eliminar_instructor(request, instructor_id):
    """Vista para eliminar permanentemente el instructor"""
    instructor = get_object_or_404(Instructor, id=instructor_id)
    total_solicitudes = instructor.solicitud_set.count()

    if request.method == 'POST':
        if total_solicitudes > 0:
            accion_solicitudes = request.POST.get('accion_solicitudes')
            if accion_solicitudes == 'desasignar':
                nombre_instructor = instructor.nombre
                instructor.solicitud_set.update(instructor_asignado=None)
                instructor.delete()
                messages.success(request, f'✅ Instructor "{nombre_instructor}" eliminado y {total_solicitudes} solicitud(es) desasignadas')
            elif accion_solicitudes == 'cancelar':
                messages.warning(request, f'⚠️ Eliminación cancelada.')
                return redirect('instructores:detalle_instructor', instructor_id=instructor.id)
            else:
                messages.error(request, '❌ Debes seleccionar qué hacer con las solicitudes asociadas')
                return render(request, 'instructores/eliminar_instructor.html', {
                    'instructor': instructor, 'total_solicitudes': total_solicitudes
                })
        else:
            nombre_instructor = instructor.nombre
            instructor.delete()
            messages.success(request, f'✅ Instructor "{nombre_instructor}" eliminado exitosamente')

        return redirect('instructores:listar_instructores')

    return render(request, 'instructores/eliminar_instructor.html', {
        'instructor': instructor, 'total_solicitudes': total_solicitudes,
    })

COLORES_CALENDARIO = [
    '#2e7d32', '#1565c0', '#6a1b9a', '#c62828',
    '#ef6c00', '#00838f', '#4527a0', '#558b2f',
    '#ad1457', '#0277bd',
]

@puede_ver_requerido
def calendario_instructores(request):
    import json
    from datetime import timedelta
    from django.utils import timezone
    from solicitudes.models import Solicitud

    hoy = timezone.now().date()
    instructores_activos = Instructor.objects.filter(activo=True).order_by('nombre')

    eventos = []
    leyenda = []

    for idx, instructor in enumerate(instructores_activos):
        color = COLORES_CALENDARIO[idx % len(COLORES_CALENDARIO)]

        solicitudes = instructor.solicitud_set.filter(
            fecha_atencion__isnull=False,
        ).exclude(estado='FINALIZADA').select_related('empresa', 'programa')

        for sol in solicitudes:
            fecha_inicio = sol.fecha_atencion.date()
            fecha_fin = None
            if sol.fecha_fin_formacion:
                fecha_fin = (sol.fecha_fin_formacion + timedelta(days=1)).isoformat()

            eventos.append({
                'id':    sol.id,
                'title': instructor.nombre,
                'start': fecha_inicio.isoformat(),
                'end':   fecha_fin,
                'color': color,
                'extendedProps': {
                    'instructor_id': instructor.id,
                    'instructor':    instructor.nombre,
                    'empresa':       sol.empresa.nombre,
                    'programa':      sol.programa.nombre,
                    'estado':        sol.get_estado_display(),
                    'solicitud_id':  sol.id,
                    'fecha_inicio':  fecha_inicio.isoformat(),
                    'fecha_fin':     sol.fecha_fin_formacion.isoformat() if sol.fecha_fin_formacion else None,
                },
            })

        leyenda.append({
            'id':     instructor.id,
            'nombre': instructor.nombre,
            'color':  color,
            'total':  solicitudes.count(),
        })

    ocupados_hoy = 0
    for instructor in instructores_activos:
        for sol in instructor.solicitud_set.filter(
            fecha_atencion__isnull=False
        ).exclude(estado='FINALIZADA'):
            inicio = sol.fecha_atencion.date()
            fin    = sol.fecha_fin_formacion
            if inicio <= hoy and (fin is None or fin >= hoy):
                ocupados_hoy += 1
                break

    context = {
        'eventos_json':         json.dumps(eventos, ensure_ascii=False),
        'leyenda_instructores':  leyenda,
        'total_instructores':   instructores_activos.count(),
        'ocupados_hoy':         ocupados_hoy,
        'total_formaciones':    Solicitud.objects.filter(
                                    fecha_atencion__isnull=False
                                ).exclude(estado='FINALIZADA').count(),
        'sin_fecha_fin':        Solicitud.objects.filter(
                                    fecha_atencion__isnull=False,
                                    fecha_fin_formacion__isnull=True,
                                ).exclude(estado='FINALIZADA').count(),
    }
    return render(request, 'instructores/calendario_instructores.html', context)