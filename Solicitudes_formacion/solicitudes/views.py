from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from .email_handler import EmailSolicitudHandler
from django.db.models import Q, Count
from .models import Solicitud
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
from programas.models import Programa
from empresas.models import Empresa
from instructores.models import Instructor
import re
# Create your views here.

def listar_solicitudes(request):
    """Vista para listar todas las solicitudes de formacion"""
    search = request.GET.get('search', '')
    estado = request.GET.get('estado', '')
    programa_id = request.GET.get('programa', '')
    empresa_id = request.GET.get('empresa', '')
    periodo_filter = request.GET.get('periodo', '')  # ⭐ NUEVO: obtener filtro de período
    
    # Consulta base con relaciones
    solicitudes = Solicitud.objects.select_related(
        'empresa',
        'programa',
        'programa__area',
        'instructor_asignado',  
    ).all()
    
    # Aplicar filtros
    if search:
        solicitudes = solicitudes.filter(
            Q(empresa__nombre__icontains=search) |
            Q(programa__nombre__icontains=search) |
            Q(instructor_asignado__nombre__icontains=search)
        )
        
    if estado:
        solicitudes = solicitudes.filter(estado=estado)
    if programa_id:
        solicitudes = solicitudes.filter(programa_id=programa_id)
    if empresa_id:
        solicitudes = solicitudes.filter(empresa_id=empresa_id)
    
    # ⭐ NUEVO: Aplicar filtro de período
    if periodo_filter:
        hoy = timezone.now().date()
        
        if periodo_filter == 'hoy':
            solicitudes = solicitudes.filter(fecha_recepcion=hoy)
        elif periodo_filter == 'semana':
            hace_semana = hoy - timedelta(days=7)
            solicitudes = solicitudes.filter(fecha_recepcion__gte=hace_semana)
        elif periodo_filter == 'mes':
            hace_mes = hoy - timedelta(days=30)
            solicitudes = solicitudes.filter(fecha_recepcion__gte=hace_mes)
        elif periodo_filter == 'trimestre':
            hace_trimestre = hoy - timedelta(days=90)
            solicitudes = solicitudes.filter(fecha_recepcion__gte=hace_trimestre)
    
    # Ordenar por fecha de recepcion (mas recientes primero)
    solicitudes = solicitudes.order_by('-fecha_recepcion')
    
    # Obtener datos para los filtros
    programas = Programa.objects.filter(activo=True).select_related('area').order_by('nombre')
    empresas = Empresa.objects.all().order_by('nombre')
    
    # Calcular estadisticas
    total_solicitudes = solicitudes.count()
    solicitudes_recibidas = solicitudes.filter(estado='RECIBIDA').count()
    solicitudes_respondidas = solicitudes.filter(estado='RESPONDIDA').count()
    solicitudes_atendidas = solicitudes.filter(estado='ATENDIDA').count()
    solicitudes_finalizadas = solicitudes.filter(estado='FINALIZADA').count()
    
    # Estadisticas por estado
    stats_por_estado = {
        'RECIBIDA': solicitudes_recibidas,
        'RESPONDIDA': solicitudes_respondidas,
        'ATENDIDA': solicitudes_atendidas,
        'FINALIZADA': solicitudes_finalizadas,
    }
    
    context = {
        'solicitudes': solicitudes,
        'programas': programas,
        'empresas': empresas,
        'search': search,
        'estado_filter': estado,
        'programa_filter': programa_id,
        'empresa_filter': empresa_id,
        'periodo_filter': periodo_filter,  # ⭐ NUEVO: pasar filtro al template
        'total_solicitudes': total_solicitudes,
        'solicitudes_recibidas': solicitudes_recibidas,
        'solicitudes_respondidas': solicitudes_respondidas,
        'solicitudes_atendidas': solicitudes_atendidas,
        'solicitudes_finalizadas': solicitudes_finalizadas,
        'stats_por_estado': stats_por_estado,
        'ESTADOS_CHOICES': Solicitud.ESTADO_CHOICES,  # ⭐ NOTA: Corregí el nombre
    }
    return render(request, 'solicitudes/listar_solicitudes.html', context)


def es_admin(user):
    """Verifica si el usuario es admin"""
    return user.is_staff or user.is_superuser


@login_required
@user_passes_test(es_admin)
def panel_correos(request):
    """Panel de administracion de correos"""
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'procesar':
            try:
                handler = EmailSolicitudHandler()
                solicitudes_creadas = handler.procesar_correos()
                
                if solicitudes_creadas:
                    messages.success(
                        request,
                        f'✅ {len(solicitudes_creadas)} correo(s) procesados exitosamente. '
                        f'Se crearon {len(solicitudes_creadas)} solicitud(es).'
                    )
                else:
                    messages.warning(
                        request,
                        '⚠️ No se encontraron correos nuevos para procesar.'
                    )
            except Exception as e:
                messages.error(
                    request,
                    f'❌ Error procesando correos: {str(e)}'
                )
        return redirect('solicitudes:panel_correos')
    
    # Estadisticas
    hoy = timezone.now().date()
    hace_7_dias = hoy - timedelta(days=7)
    
    context = {
        'solicitudes_hoy': Solicitud.objects.filter(
            fecha_recepcion__date=hoy
        ).count(),
        'solicitudes_semana': Solicitud.objects.filter(
            fecha_recepcion__date__gte=hace_7_dias
        ).count(),
        'ultimas_solicitudes': Solicitud.objects.select_related(
            'empresa', 'programa'
        ).order_by('-fecha_recepcion')[:10],
    }
    
    return render(request, 'solicitudes/panel_correos.html', context)


@login_required
@user_passes_test(es_admin)
def probar_conexion_email(request):
    """Prueba la conexion al servidor de correo"""
    from django.http import JsonResponse
    
    try:
        handler = EmailSolicitudHandler()
        mail = handler.conectar_email()
        
        if mail:
            # Obtener info adicional
            status, mailbox_data = mail.select('INBOX')
            mail.logout()
            
            return JsonResponse({
                'success': True,
                'message': f'✅ Conexión exitosa al servidor de correo\n'
                            f'Usuario: {handler.email_account}\n'
                            f'Servidor: {handler.imap_server}:{handler.imap_port}'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': '❌ No se pudo conectar al servidor de correo.\n'
                            'Verifica EMAIL_HOST_USER y EMAIL_HOST_PASSWORD en settings.py'
            })
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'message': f'❌ Error: {str(e)}\n\n{traceback.format_exc()}'
        })

def detalle_solicitud(request, solicitud_id):
    """Vista para el detalle de una solicitud"""
    solicitud = get_object_or_404(
        Solicitud.objects.select_related(
            'empresa',
            'programa',
            'programa__area',
            'instructor_asignado'
        ),
        id=solicitud_id
    )
    
    
    
    context = {
        'solicitud': solicitud,
    }
    
    return render(request, 'solicitudes/detalle_solicitud.html', context)
        
def editar_solicitud(request, solicitud_id):
    """Vista para editar una solicitud existente"""
    solicitud = get_object_or_404(
        Solicitud.objects.select_related(
            'empresa',
            'programa',
            'programa__area',
            'instructor_asignado'
        ),
        id=solicitud_id
    )
    
    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            estado = request.POST.get('estado')
            instructor_id = request.POST.get('instructor_asignado')
            observaciones = request.POST.get('observaciones')
            numero_aprendices = request.POST.get('numero_aprendices')
            
            # Validar campos requeridos
            if not estado:
                messages.error(request, '❌ El estado es obligatorio')
                return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
            
            # 🔥 NUEVA VALIDACIÓN: Verificar flujo de estados
            if estado != solicitud.estado:
                if not solicitud.puede_cambiar_a_estado(estado):
                    messages.error(
                        request,
                        f'❌ No puedes cambiar de "{solicitud.get_estado_display()}" a "{dict(Solicitud.ESTADO_CHOICES)[estado]}"'
                    )
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
            
            # 🔥 VALIDACIÓN: ATENDIDA requiere instructor
            if estado == 'ATENDIDA' and not instructor_id and not solicitud.instructor_asignado:
                messages.error(request, '❌ Debes asignar un instructor para marcar como ATENDIDA')
                return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
            
            # 🔥 VALIDACIÓN: FINALIZADA requiere que haya estado ATENDIDA
            if estado == 'FINALIZADA' and not solicitud.fecha_atencion:
                messages.error(request, '❌ La solicitud debe estar ATENDIDA antes de finalizarla')
                return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
            
            # Actualizar campos básicos
            solicitud.estado = estado
            solicitud.observaciones = observaciones
            
            # Actualizar número de aprendices si se proporcionó
            if numero_aprendices:
                try:
                    solicitud.numero_aprendices = int(numero_aprendices)
                except ValueError:
                    messages.warning(request, '⚠️ Número de Aprendices no válido, se mantuvo el valor anterior')
            
            # 🔥 LÓGICA PRINCIPAL: Asignar instructor y cambiar a ATENDIDA automáticamente
            instructor_anterior = solicitud.instructor_asignado
            
            if instructor_id:
                try:
                    instructor = Instructor.objects.get(id=instructor_id, activo=True)
                    solicitud.instructor_asignado = instructor
                    
                
                    if solicitud.estado != 'FINALIZADA':
                        solicitud.estado = 'ATENDIDA'
                        if not solicitud.fecha_atencion:
                            solicitud.fecha_atencion = timezone.now()
                        
                        messages.success(
                            request,
                            f'✅ Instructor "{instructor.nombre}" asignado. Estado cambiado automáticamente a ATENDIDA'
                        )
                    
                except Instructor.DoesNotExist:
                    messages.warning(request, '⚠️ Instructor no encontrado')
            else:
                # Si se quita el instructor
                solicitud.instructor_asignado = None
                if instructor_anterior:
                    messages.info(request, f'ℹ️ Instructor "{instructor_anterior.nombre}" removido')
            
            # Actualizar fechas según el estado
            now = timezone.now()
            
            if estado == 'RESPONDIDA' and not solicitud.fecha_respuesta:
                solicitud.fecha_respuesta = now
            
            if estado == 'ATENDIDA' and not solicitud.fecha_atencion:
                solicitud.fecha_atencion = now
            
            if estado == 'FINALIZADA' and not solicitud.fecha_finalizacion:
                solicitud.fecha_finalizacion = now
            
            # Guardar cambios
            solicitud.save()
            
            messages.success(
                request,
                f'✅ Solicitud #{solicitud.id} actualizada exitosamente'
            )
            return redirect('solicitudes:detalle_solicitud', solicitud_id=solicitud.id)
            
        except Exception as e:
            messages.error(
                request,
                f'❌ Error al actualizar la solicitud: {str(e)}'
            )
            return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
    
    # GET request - mostrar formulario
    # Obtener todos los instructores activos para el dropdown
    instructores = Instructor.objects.filter(activo=True).order_by('nombre')
    
    # Obtener instructores especializados en el programa de la solicitud
    instructores_especializados = instructores.filter(
        especialidad=solicitud.programa
    )
    
    # Obtener todos los programas activos (por si se quiere cambiar)
    programas = Programa.objects.filter(activo=True).select_related('area').order_by('nombre')
    
    context = {
        'solicitud': solicitud,
        'instructores': instructores,
        'instructores_especializados': instructores_especializados,
        'programas': programas,
        'ESTADO_CHOICES': Solicitud.ESTADO_CHOICES,
    }
    return render(request, 'solicitudes/editar_solicitud.html', context)
                    
        
            
def enviar_respuesta(request, solicitud_id):
    """Vista para enviar correo de respuesta y cambiar estado a RESPONDIDA"""
    solicitud = get_object_or_404(
        Solicitud.objects.select_related(
            'empresa',
            'programa',
            'programa__area'
        ),
        id=solicitud_id    
    )
    
    if request.method == 'POST':
        try:
            asunto = request.POST.get('asunto')
            mensaje = request.POST.get('mensaje')
            
            # Validar campos
            if not asunto or not mensaje:
                messages.error(request, '❌ El asunto y el mensaje son obligatorios')
                return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)
            
            # Enviar correo
            from django.core.mail import send_mail 
            from django.conf import settings
            
            send_mail(
                subject=asunto,
                message=mensaje,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[solicitud.empresa.correo],
                fail_silently=False,
            )
            
            # 🔥 MEJORA: Solo cambiar a RESPONDIDA si está en RECIBIDA
            if solicitud.estado == 'RECIBIDA':
                solicitud.estado = "RESPONDIDA"
                solicitud.fecha_respuesta = timezone.now()
                solicitud.save()
                
                messages.success(
                    request,
                    f'✅ Correo enviado exitosamente a {solicitud.empresa.correo}. Estado actualizado a RESPONDIDA'
                )
            else:
                # Si ya estaba RESPONDIDA, ATENDIDA o FINALIZADA, solo enviar correo
                messages.success(
                    request,
                    f'✅ Correo enviado exitosamente a {solicitud.empresa.correo}'
                )
            
            return redirect('solicitudes:detalle_solicitud', solicitud_id=solicitud.id)
        
        except Exception as e:
            messages.error(request, f'❌ Error al enviar el correo: {str(e)}')
            return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)
    
    # GET request - mostrar formulario 
    context = {
        'solicitud': solicitud,
    }
    return render(request, 'solicitudes/enviar_respuesta.html', context)
@login_required
@user_passes_test(es_admin)
def procesar_correos_ajax(request):
    """Procesa correos y retorna logs en tiempo real"""
    if request.method == 'POST':
        import io
        import sys
        import json
        
        # Capturar la salida estándar
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output
        
        try:
            handler = EmailSolicitudHandler()
            solicitudes_creadas = handler.procesar_correos()
            
            # Restaurar stdout
            sys.stdout = old_stdout
            output = captured_output.getvalue()
            
            # Parsear el output en logs estructurados
            logs = [] 
            lines = output.split('\n')
            
            for line in lines:
                if not line.strip():
                    continue
                    
                log_entry = {'message': line.strip()}
                
                # Clasificar tipo de log
                if '=' * 50 in line or '-' * 50 in line:
                    log_entry['type'] = 'separator'
                elif 'INICIANDO' in line or 'PROCESANDO' in line or 'CORREO' in line:
                    log_entry['type'] = 'section'
                elif 'Conectado exitosamente' in line:
                    log_entry['type'] = 'success'
                elif 'Correos no leídos encontrados' in line:
                    log_entry['type'] = 'info'
                    match = re.search(r'(\d+)', line)
                    if match:
                        log_entry['count'] = int(match.group(1))
                elif 'Empresa:' in line or 'nombre' in line.lower():
                    log_entry['type'] = 'empresa'
                elif 'Contacto:' in line:
                    log_entry['type'] = 'info'
                elif 'Email:' in line or 'correo' in line.lower():
                    log_entry['type'] = 'info'
                elif 'Programa:' in line:
                    log_entry['type'] = 'programa'
                elif 'Solicitud creada' in line or '#' in line:
                    log_entry['type'] = 'success'
                    match = re.search(r'#(\d+)', line)
                    if match:
                        log_entry['solicitud_id'] = int(match.group(1))
                elif 'Respuesta enviada' in line:
                    log_entry['type'] = 'success'
                elif 'ERROR' in line or 'Error' in line:
                    log_entry['type'] = 'error'
                elif 'No encontrado' in line or 'no encontrado' in line.lower():
                    log_entry['type'] = 'warning'
                elif 'Buscando' in line or 'Encontrado' in line:
                    log_entry['type'] = 'info'
                elif 'Creando' in line:
                    log_entry['type'] = 'info'
                elif 'RESUMEN' in line:
                    log_entry['type'] = 'section'
                else:
                    log_entry['type'] = 'info'
                
                logs.append(log_entry)
            
            # Información de las solicitudes creadas
            solicitudes_data = []
            for solicitud in solicitudes_creadas:
                solicitudes_data.append({
                    'id': solicitud.id,
                    'empresa': solicitud.empresa.nombre,
                    'programa': solicitud.programa.nombre,
                    'estado': solicitud.get_estado_display(),
                    'fecha': solicitud.fecha_recepcion.strftime('%d/%m/%Y %H:%M')
                })
            
            return JsonResponse({
                'success': True,
                'solicitudes_count': len(solicitudes_creadas),
                'solicitudes': solicitudes_data,
                'logs': logs,
                'raw_output': output   
            })
            
        except Exception as e:
            sys.stdout = old_stdout
            import traceback
            error_trace = traceback.format_exc()
            
            return JsonResponse({
                'success': False,
                'error': str(e),
                'traceback': error_trace,
                'logs': [
                    {'type': 'error', 'message': f'❌ ERROR: {str(e)}'},
                    {'type': 'error', 'message': error_trace}
                ]
            }, status=500)
    
    return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)