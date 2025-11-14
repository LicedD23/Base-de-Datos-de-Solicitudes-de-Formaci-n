from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from .email_handler import EmailSolicitudHandler
from django.db.models import Q, Count
from .models import Solicitud
from django.utils import timezone
from datetime import timedelta
from programas.models import Programa
from empresas.models import Empresa
from instructores.models import Instructor

# Create your views here.
def listar_solicitudes(request):
    """Vista para listar todas las solicitudes de formacion"""
    search = request.GET.get('search', '')
    estado = request.GET.get('estado', '')
    programa_id = request.GET.get('programa', '')
    empresa_id = request.GET.get('empresa', '')
    
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
            Q(instructor_asignado__nombre__icontains=search)  # ✅ CORREGIDO: faltaba "__"
        )
        
    if estado:
        solicitudes = solicitudes.filter(estado=estado)
    if programa_id:
        solicitudes = solicitudes.filter(programa_id=programa_id)
    if empresa_id:
        solicitudes = solicitudes.filter(empresa_id=empresa_id)
    
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
        'total_solicitudes': total_solicitudes,
        'solicitudes_recibidas': solicitudes_recibidas,
        'solicitudes_respondidas': solicitudes_respondidas,
        'solicitudes_atendidas': solicitudes_atendidas,
        'solicitudes_finalizadas': solicitudes_finalizadas,
        'stats_por_estado': stats_por_estado,
        'ESTADO_CHOICES': Solicitud.ESTADO_CHOICES,     
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
    
    # Obtener instructores disponibles para asignación
    instructores_disponibles = Instructor.objects.filter(
        activo=True,
        especialidad=solicitud.programa
    ).order_by('nombre')
    
    context = {
        'solicitud': solicitud,
        'instructores_disponibles': instructores_disponibles,
    }
    
    return render(request, 'solicitudes/detalle_solicitud.html', context)
        
    