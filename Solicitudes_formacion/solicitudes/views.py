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
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.db import IntegrityError, transaction
from core.management.decorators import puede_ver_requerido, puede_editar_requerido, admin_requerido


# ---------------------------------------------------------------------------
# LISTAR SOLICITUDES
# ---------------------------------------------------------------------------

@puede_ver_requerido
def listar_solicitudes(request):
    """Vista para listar todas las solicitudes de formacion."""
    search       = request.GET.get('search', '')
    estado       = request.GET.get('estado', '')
    programa_id  = request.GET.get('programa', '')
    empresa_id   = request.GET.get('empresa', '')
    periodo_filter = request.GET.get('periodo', '')

    solicitudes = Solicitud.objects.select_related(
        'empresa',
        'programa',
        'programa__area',
        'instructor_asignado',
    ).all()

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

    if periodo_filter:
        hoy = timezone.now().date()
        if periodo_filter == 'hoy':
            solicitudes = solicitudes.filter(fecha_recepcion=hoy)
        elif periodo_filter == 'semana':
            solicitudes = solicitudes.filter(fecha_recepcion__gte=hoy - timedelta(days=7))
        elif periodo_filter == 'mes':
            solicitudes = solicitudes.filter(fecha_recepcion__gte=hoy - timedelta(days=30))
        elif periodo_filter == 'trimestre':
            solicitudes = solicitudes.filter(fecha_recepcion__gte=hoy - timedelta(days=90))

    solicitudes = solicitudes.order_by('-fecha_recepcion')

    programas = Programa.objects.filter(activo=True).select_related('area').order_by('nombre')
    empresas  = Empresa.objects.all().order_by('nombre')

    total_solicitudes        = solicitudes.count()
    solicitudes_recibidas    = solicitudes.filter(estado='RECIBIDA').count()
    solicitudes_atendidas    = solicitudes.filter(estado='ATENDIDA').count()
    solicitudes_respondidas  = solicitudes.filter(estado='RESPONDIDA').count()
    solicitudes_finalizadas  = solicitudes.filter(estado='FINALIZADA').count()

    context = {
        'solicitudes':              solicitudes,
        'programas':                programas,
        'empresas':                 empresas,
        'search':                   search,
        'estado_filter':            estado,
        'programa_filter':          programa_id,
        'empresa_filter':           empresa_id,
        'periodo_filter':           periodo_filter,
        'total_solicitudes':        total_solicitudes,
        'solicitudes_recibidas':    solicitudes_recibidas,
        'solicitudes_atendidas':    solicitudes_atendidas,
        'solicitudes_respondidas':  solicitudes_respondidas,
        'solicitudes_finalizadas':  solicitudes_finalizadas,
        'stats_por_estado': {
            'RECIBIDA':   solicitudes_recibidas,
            'ATENDIDA':   solicitudes_atendidas,
            'RESPONDIDA': solicitudes_respondidas,
            'FINALIZADA': solicitudes_finalizadas,
        },
        'ESTADOS_CHOICES': Solicitud.ESTADO_CHOICES,
    }
    return render(request, 'solicitudes/listar_solicitudes.html', context)


# ---------------------------------------------------------------------------
# PANEL DE CORREOS
# ---------------------------------------------------------------------------

@puede_ver_requerido
def panel_correos(request):
    """Panel de administracion de correos."""
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
                    messages.warning(request, '⚠️ No se encontraron correos nuevos para procesar.')
            except Exception as e:
                messages.error(request, f'❌ Error procesando correos: {str(e)}')

        return redirect('solicitudes:panel_correos')

    hoy        = timezone.now().date()
    hace_7_dias = hoy - timedelta(days=7)

    context = {
        'solicitudes_hoy': Solicitud.objects.filter(fecha_recepcion__date=hoy).count(),
        'solicitudes_semana': Solicitud.objects.filter(fecha_recepcion__date__gte=hace_7_dias).count(),
        'ultimas_solicitudes': Solicitud.objects.select_related(
            'empresa', 'programa'
        ).order_by('-fecha_recepcion')[:10],
    }
    return render(request, 'solicitudes/panel_correos.html', context)


# ---------------------------------------------------------------------------
# PROBAR CONEXIÓN EMAIL
# ---------------------------------------------------------------------------

@puede_editar_requerido
def probar_conexion_email(request):
    """Prueba la conexion al servidor de correo."""
    try:
        handler = EmailSolicitudHandler()
        mail    = handler.conectar_email()

        if mail:
            mail.select('INBOX')
            mail.logout()
            return JsonResponse({
                'success': True,
                'message': (
                    f'✅ Conexión exitosa al servidor de correo\n'
                    f'Usuario: {handler.email_account}\n'
                    f'Servidor: {handler.imap_server}:{handler.imap_port}'
                ),
            })
        return JsonResponse({
            'success': False,
            'message': '❌ No se pudo conectar al servidor de correo.\n'
                       'Verifica EMAIL_HOST_USER y EMAIL_HOST_PASSWORD en settings.py',
        })
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'message': f'❌ Error: {str(e)}\n\n{traceback.format_exc()}',
        })


# ---------------------------------------------------------------------------
# DETALLE DE SOLICITUD
# ---------------------------------------------------------------------------

@puede_ver_requerido
def detalle_solicitud(request, solicitud_id):
    """Vista para el detalle de una solicitud."""
    solicitud = get_object_or_404(
        Solicitud.objects.select_related(
            'empresa',
            'programa',
            'programa__area',
            'instructor_asignado',
        ),
        id=solicitud_id,
    )
    return render(request, 'solicitudes/detalle_solicitud.html', {'solicitud': solicitud})


# ---------------------------------------------------------------------------
# EDITAR SOLICITUD
# ---------------------------------------------------------------------------

@puede_editar_requerido
def editar_solicitud(request, solicitud_id):
    """Vista para editar una solicitud existente CON MODO MIGRACIÓN."""
    solicitud = get_object_or_404(
        Solicitud.objects.select_related(
            'empresa', 'programa', 'programa__area', 'instructor_asignado',
        ).prefetch_related('documentos'),
        id=solicitud_id,
    )

    if request.method == 'POST':
        try:
            es_migracion = request.POST.get('es_migracion') == 'true'

            # ── Datos del formulario ─────────────────────────────────────
            estado             = request.POST.get('estado')
            instructor_id      = request.POST.get('instructor_asignado')
            observaciones      = request.POST.get('observaciones', '')
            numero_aprendices  = request.POST.get('numero_aprendices')
            nuevos_documentos_pdf   = request.FILES.getlist('documentos_pdf')
            eliminar_pdf            = request.POST.get('eliminar_pdf')
            documentos_a_eliminar   = request.POST.getlist('eliminar_documentos')

            if not estado and not es_migracion:
                messages.error(request, '❌ El estado es obligatorio')
                return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

            from datetime import datetime

            # ================================================================
            # MODO MIGRACIÓN — fechas y estado personalizados
            # ================================================================
            if es_migracion:
                # Fecha de Recepción (obligatoria)
                fecha_recepcion_str = request.POST.get('fecha_recepcion')
                if not fecha_recepcion_str:
                    messages.error(request, '❌ En modo migración, la fecha de recepción es obligatoria')
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

                try:
                    fecha_recepcion = timezone.make_aware(
                        datetime.strptime(fecha_recepcion_str, '%Y-%m-%dT%H:%M')
                    )
                    if fecha_recepcion > timezone.now():
                        messages.error(request, '❌ La fecha de recepción no puede ser futura')
                        return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
                except ValueError:
                    messages.error(request, '❌ Formato de fecha de recepción inválido')
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

                # Fecha de Atención (opcional)
                fecha_atencion = None
                fecha_atencion_str = request.POST.get('fecha_atencion')
                if fecha_atencion_str:
                    try:
                        fecha_atencion = timezone.make_aware(
                            datetime.strptime(fecha_atencion_str, '%Y-%m-%dT%H:%M')
                        )
                        if fecha_atencion > timezone.now():
                            messages.error(request, '❌ La fecha de atención no puede ser futura')
                            return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
                        if fecha_atencion < fecha_recepcion:
                            messages.error(request, '❌ La fecha de atención no puede ser anterior a la recepción')
                            return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
                    except ValueError:
                        messages.warning(request, '⚠️ Formato de fecha de atención inválido, se omitirá')

                # Fecha de Respuesta (opcional)
                fecha_respuesta = None
                fecha_respuesta_str = request.POST.get('fecha_respuesta')
                if fecha_respuesta_str:
                    try:
                        fecha_respuesta = timezone.make_aware(
                            datetime.strptime(fecha_respuesta_str, '%Y-%m-%dT%H:%M')
                        )
                        if fecha_respuesta > timezone.now():
                            messages.error(request, '❌ La fecha de respuesta no puede ser futura')
                            return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
                        fecha_minima_respuesta = fecha_atencion if fecha_atencion else fecha_recepcion
                        if fecha_respuesta < fecha_minima_respuesta:
                            messages.error(
                                request,
                                '❌ La fecha de respuesta no puede ser anterior a la atención'
                                ' (flujo: Recibida → Atendida → Respondida)'
                            )
                            return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
                    except ValueError:
                        messages.warning(request, '⚠️ Formato de fecha de respuesta inválido, se omitirá')

                # Fecha de Finalización (opcional)
                fecha_finalizacion = None
                fecha_finalizacion_str = request.POST.get('fecha_finalizacion')
                if fecha_finalizacion_str:
                    try:
                        fecha_finalizacion = timezone.make_aware(
                            datetime.strptime(fecha_finalizacion_str, '%Y-%m-%dT%H:%M')
                        )
                        if fecha_finalizacion > timezone.now():
                            messages.error(request, '❌ La fecha de finalización no puede ser futura')
                            return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
                        fecha_minima_fin = fecha_respuesta if fecha_respuesta else (
                            fecha_atencion if fecha_atencion else fecha_recepcion
                        )
                        if fecha_finalizacion < fecha_minima_fin:
                            messages.error(request, '❌ La fecha de finalización debe ser la más reciente')
                            return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
                    except ValueError:
                        messages.warning(request, '⚠️ Formato de fecha de finalización inválido, se omitirá')

                if fecha_finalizacion:
                    estado = 'FINALIZADA'
                elif fecha_respuesta:
                    estado = 'RESPONDIDA'
                elif fecha_atencion:
                    estado = 'ATENDIDA'
                else:
                    estado = 'RECIBIDA'

            # ================================================================
            # MODO NORMAL — validaciones del flujo real
            # ================================================================
            else:
                fecha_recepcion    = solicitud.fecha_recepcion
                fecha_atencion     = solicitud.fecha_atencion
                fecha_respuesta    = solicitud.fecha_respuesta
                fecha_finalizacion = solicitud.fecha_finalizacion

                if estado != solicitud.estado:
                    if not solicitud.puede_cambiar_a_estado(estado):
                        labels = dict(Solicitud.ESTADO_CHOICES)
                        messages.error(
                            request,
                            f'❌ No puedes cambiar de "{solicitud.get_estado_display()}" '
                            f'a "{labels.get(estado, estado)}". '
                            f'Flujo correcto: Recibida → Atendida → Respondida → Finalizada'
                        )
                        return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

                if estado == 'ATENDIDA' and not instructor_id and not solicitud.instructor_asignado:
                    messages.error(
                        request,
                        '❌ Debes asignar un instructor para marcar la solicitud como ATENDIDA'
                    )
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

                if estado == 'RESPONDIDA' and not solicitud.fecha_atencion:
                    messages.error(
                        request,
                        '❌ La solicitud debe estar ATENDIDA antes de marcarla como RESPONDIDA. '
                        'Asigna un instructor primero.'
                    )
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

                if estado == 'FINALIZADA' and not solicitud.fecha_respuesta:
                    messages.error(
                        request,
                        '❌ La solicitud debe estar RESPONDIDA (empresa notificada por correo) '
                        'antes de finalizarla.'
                    )
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

            # ── Validación de documentos ─────────────────────────────────
            documentos_actuales       = solicitud.documentos.count()
            documentos_a_eliminar_count = len(documentos_a_eliminar)
            nuevos_documentos_count     = len(nuevos_documentos_pdf)
            total_documentos = documentos_actuales - documentos_a_eliminar_count + nuevos_documentos_count

            if total_documentos > 5:
                messages.error(
                    request,
                    f'❌ Máximo 5 documentos permitidos. '
                    f'Tienes {documentos_actuales}, intentas agregar {nuevos_documentos_count} '
                    f'y eliminar {documentos_a_eliminar_count}. Total resultante: {total_documentos}'
                )
                return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

            for doc in nuevos_documentos_pdf:
                if not doc.name.lower().endswith('.pdf'):
                    messages.error(request, f'❌ {doc.name} no es un archivo PDF')
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
                if doc.size > 10 * 1024 * 1024:
                    messages.error(request, f'❌ {doc.name} supera 10MB')
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

            # ================================================================
            # TRANSACCIÓN ATÓMICA
            # ================================================================
            with transaction.atomic():
                solicitud.estado        = estado
                solicitud.observaciones = observaciones

                if es_migracion:
                    solicitud.fecha_recepcion    = fecha_recepcion
                    solicitud.fecha_atencion     = fecha_atencion
                    solicitud.fecha_respuesta    = fecha_respuesta
                    solicitud.fecha_finalizacion = fecha_finalizacion

                if numero_aprendices:
                    try:
                        solicitud.numero_aprendices = int(numero_aprendices)
                    except ValueError:
                        messages.warning(request, '⚠️ Número de aprendices no válido, se mantiene el valor anterior')

                instructor_anterior = solicitud.instructor_asignado

                if instructor_id:
                    try:
                        instructor = Instructor.objects.get(id=instructor_id, activo=True)
                        solicitud.instructor_asignado = instructor

                        if not es_migracion:
                            if solicitud.estado == 'RECIBIDA':
                                solicitud.estado = 'ATENDIDA'
                                if not solicitud.fecha_atencion:
                                    solicitud.fecha_atencion = timezone.now()
                                messages.success(
                                    request,
                                    f'✅ Instructor "{instructor.nombre}" asignado. '
                                    f'Estado cambiado a ATENDIDA. '
                                    f'Siguiente paso: enviar respuesta a la empresa.'
                                )
                            else:
                                messages.success(request, f'✅ Instructor "{instructor.nombre}" asignado')
                        else:
                            messages.success(request, f'✅ Instructor "{instructor.nombre}" asignado')

                    except Instructor.DoesNotExist:
                        messages.warning(request, '⚠️ Instructor no encontrado')
                else:
                    solicitud.instructor_asignado = None
                    if instructor_anterior:
                        messages.info(request, f'ℹ️ Instructor "{instructor_anterior.nombre}" removido')

                from .models import DocumentoSolicitud
                import os

                if documentos_a_eliminar:
                    for doc_id in documentos_a_eliminar:
                        try:
                            documento = DocumentoSolicitud.objects.get(id=doc_id, solicitud=solicitud)
                            if documento.archivo and os.path.exists(documento.archivo.path):
                                os.remove(documento.archivo.path)
                            documento.delete()
                        except DocumentoSolicitud.DoesNotExist:
                            pass
                        except Exception as e:
                            print(f"⚠️ Error al eliminar documento {doc_id}: {str(e)}")

                    messages.success(request, f'✅ {len(documentos_a_eliminar)} documento(s) eliminado(s)')

                if nuevos_documentos_pdf:
                    for doc in nuevos_documentos_pdf:
                        DocumentoSolicitud.objects.create(
                            solicitud=solicitud,
                            archivo=doc,
                            nombre_archivo=doc.name,
                        )
                    messages.success(request, f'✅ {len(nuevos_documentos_pdf)} documento(s) agregado(s)')

                    primer_documento = solicitud.documentos.first()
                    if primer_documento:
                        solicitud.documento_pdf = primer_documento.archivo

                if eliminar_pdf == 'on':
                    if solicitud.documento_pdf:
                        try:
                            if os.path.exists(solicitud.documento_pdf.path):
                                os.remove(solicitud.documento_pdf.path)
                        except Exception:
                            pass
                        solicitud.documento_pdf = None
                        messages.info(request, 'ℹ️ Documento PDF principal eliminado')

                if not es_migracion:
                    now = timezone.now()
                    if estado == 'ATENDIDA' and not solicitud.fecha_atencion:
                        solicitud.fecha_atencion = now
                    if estado == 'RESPONDIDA' and not solicitud.fecha_respuesta:
                        solicitud.fecha_respuesta = now
                    if estado == 'FINALIZADA' and not solicitud.fecha_finalizacion:
                        solicitud.fecha_finalizacion = now

                solicitud.save()

            if es_migracion:
                messages.success(
                    request,
                    f'✅ Solicitud #{solicitud.id} actualizada en modo migración '
                    f'con estado: {solicitud.get_estado_display()}'
                )
            else:
                messages.success(request, f'✅ Solicitud #{solicitud.id} actualizada exitosamente')

            return redirect('solicitudes:detalle_solicitud', solicitud_id=solicitud.id)

        except Exception as e:
            messages.error(request, f'❌ Error al actualizar la solicitud: {str(e)}')
            import traceback
            traceback.print_exc()
            return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

    # ── GET: mostrar formulario ──────────────────────────────────────────────
    instructores               = Instructor.objects.filter(activo=True).order_by('nombre')
    instructores_especializados = instructores.filter(especialidad=solicitud.programa)
    programas                  = Programa.objects.filter(activo=True).select_related('area').order_by('nombre')

    from .models import DocumentoSolicitud
    documentos_actuales = DocumentoSolicitud.objects.filter(solicitud=solicitud).order_by('-fecha_subida')

    context = {
        'solicitud':                 solicitud,
        'instructores':              instructores,
        'instructores_especializados': instructores_especializados,
        'programas':                 programas,
        'ESTADO_CHOICES':            Solicitud.ESTADO_CHOICES,
        'documentos_actuales':       documentos_actuales,
        'ahora':                     timezone.now(),
    }
    return render(request, 'solicitudes/editar_solicitud.html', context)


# ---------------------------------------------------------------------------
# ENVIAR RESPUESTA
# Flujo: la solicitud debe estar ATENDIDA (con instructor) para poder enviar
# el correo y pasar a RESPONDIDA. Es el único punto donde ocurre esa transición.
# ---------------------------------------------------------------------------

@puede_editar_requerido
def enviar_respuesta(request, solicitud_id):
    """
    Envía correo de respuesta a la empresa y avanza el estado de
    ATENDIDA → RESPONDIDA.

    Requisitos obligatorios antes de enviar:
      1. La solicitud debe estar en estado ATENDIDA (no RECIBIDA).
      2. Debe tener un instructor asignado.
    """
    solicitud = get_object_or_404(
        Solicitud.objects.select_related(
            'empresa', 'programa', 'programa__area', 'instructor_asignado',
        ),
        id=solicitud_id,
    )

    if request.method == 'POST':
        try:
            # ================================================================
            # GUARDIA 1: el estado debe ser ATENDIDA, RESPONDIDA o FINALIZADA.
            # Si es RECIBIDA se bloquea el envío — el usuario debe asignar
            # instructor primero para que el sistema avance a ATENDIDA.
            # ================================================================
            if solicitud.estado == 'RECIBIDA':
                messages.error(
                    request,
                    '❌ No puedes enviar la respuesta: la solicitud está en estado RECIBIDA. '
                    'Debes asignar un instructor primero para que pase a ATENDIDA. '
                    'Flujo obligatorio: Recibida → Atendida → Respondida → Finalizada.'
                )
                return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

            # ================================================================
            # GUARDIA 2: aunque el estado sea ATENDIDA, debe haber instructor.
            # (Salvaguarda ante datos inconsistentes en BD.)
            # ================================================================
            if solicitud.estado == 'ATENDIDA' and not solicitud.instructor_asignado:
                messages.error(
                    request,
                    '❌ La solicitud está en estado ATENDIDA pero no tiene instructor asignado. '
                    'Asigna un instructor antes de enviar la respuesta.'
                )
                return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

            # ── A partir de aquí el estado es ATENDIDA (con instructor),
            #    RESPONDIDA o FINALIZADA — se puede enviar el correo ─────────

            asunto  = f"Respuesta a Solicitud #{solicitud.id} - {solicitud.programa.nombre}"
            mensaje = request.POST.get('mensaje')

            if not mensaje:
                messages.error(request, '❌ El mensaje es obligatorio')
                return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

            correo_destino = solicitud.correo_remitente or solicitud.empresa.correo

            if not correo_destino:
                messages.error(request, '❌ No hay correo de destino disponible')
                return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

            if '@ejemplo.com' in correo_destino.lower():
                messages.error(request, '❌ No se puede enviar correo a una dirección de ejemplo')
                return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

            from django.core.mail import send_mail
            from django.conf import settings

            send_mail(
                subject=asunto,
                message=mensaje,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[correo_destino],
                fail_silently=False,
            )

            # ── Transición de estado ─────────────────────────────────────
            if solicitud.estado == 'ATENDIDA':
                # Camino feliz: ATENDIDA → RESPONDIDA
                solicitud.estado          = 'RESPONDIDA'
                solicitud.fecha_respuesta = timezone.now()
                solicitud.save()
                messages.success(
                    request,
                    f'✅ Correo enviado a {correo_destino}. '
                    f'Estado actualizado a RESPONDIDA. '
                    f'Siguiente paso: finalizar la formación cuando concluya.'
                )
            else:
                # Reenvío de correo en estado RESPONDIDA o FINALIZADA
                messages.success(request, f'✅ Correo reenviado a {correo_destino}')

            return redirect('solicitudes:detalle_solicitud', solicitud_id=solicitud.id)

        except Exception as e:
            messages.error(request, f'❌ Error al enviar el correo: {str(e)}')
            return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

    # ── GET: preparar contexto del formulario ────────────────────────────────
    MESES = {
        1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril',
        5: 'mayo', 6: 'junio', 7: 'julio', 8: 'agosto',
        9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre',
    }

    fecha_inicio_texto = ''
    if solicitud.fecha_atencion:
        f = solicitud.fecha_atencion
        fecha_inicio_texto = f"{f.day} de {MESES[f.month]} de {f.year}"

    context = {
        'solicitud':          solicitud,
        'destinatario_email': solicitud.correo_remitente or solicitud.empresa.correo,
        'fecha_inicio_texto': fecha_inicio_texto,
    }
    return render(request, 'solicitudes/enviar_respuesta.html', context)


# ---------------------------------------------------------------------------
# PROCESAR CORREOS AJAX
# ---------------------------------------------------------------------------

@puede_editar_requerido
def procesar_correos_ajax(request):
    """Procesa correos y retorna logs en tiempo real."""
    if request.method == 'POST':
        import io
        import sys
        import json

        captured_output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output

        try:
            handler = EmailSolicitudHandler()
            solicitudes_creadas = handler.procesar_correos()

            sys.stdout = old_stdout
            output = captured_output.getvalue()

            logs = []
            for line in output.split('\n'):
                if not line.strip():
                    continue

                log_entry = {'message': line.strip()}

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

            solicitudes_data = [
                {
                    'id':      s.id,
                    'empresa': s.empresa.nombre,
                    'programa': s.programa.nombre,
                    'estado':  s.get_estado_display(),
                    'fecha':   s.fecha_recepcion.strftime('%d/%m/%Y %H:%M'),
                }
                for s in solicitudes_creadas
            ]

            return JsonResponse({
                'success':           True,
                'solicitudes_count': len(solicitudes_creadas),
                'solicitudes':       solicitudes_data,
                'logs':              logs,
                'raw_output':        output,
            })

        except Exception as e:
            sys.stdout = old_stdout
            import traceback
            error_trace = traceback.format_exc()
            return JsonResponse({
                'success':   False,
                'error':     str(e),
                'traceback': error_trace,
                'logs': [
                    {'type': 'error', 'message': f'❌ ERROR: {str(e)}'},
                    {'type': 'error', 'message': error_trace},
                ],
            }, status=500)

    return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)


# ---------------------------------------------------------------------------
# ELIMINAR SOLICITUD
# ---------------------------------------------------------------------------

@puede_editar_requerido
@require_http_methods(["GET", "POST"])
def eliminar_solicitud(request, solicitud_id):
    """Vista para eliminar permanentemente una solicitud."""
    solicitud = get_object_or_404(
        Solicitud.objects.select_related(
            'empresa', 'programa', 'programa__area', 'instructor_asignado',
        ),
        id=solicitud_id,
    )

    if request.method == 'POST':
        empresa_nombre   = solicitud.empresa.nombre
        programa_nombre  = solicitud.programa.nombre
        solicitud_id_str = solicitud.id

        if solicitud.estado == 'FINALIZADA':
            if request.POST.get('confirmar_finalizada') != 'confirmar':
                messages.warning(request, '⚠️ Debes confirmar la eliminación de una solicitud finalizada')
                return render(request, 'solicitudes/eliminar_solicitud.html', {'solicitud': solicitud})

        try:
            with transaction.atomic():
                if solicitud.documento_pdf:
                    import os
                    try:
                        if os.path.isfile(solicitud.documento_pdf.path):
                            os.remove(solicitud.documento_pdf.path)
                    except Exception as e:
                        print(f"⚠️ Error al eliminar el PDF: {str(e)}")

                solicitud.delete()

            messages.success(
                request,
                f'✅ Solicitud #{solicitud_id_str} de "{empresa_nombre}" '
                f'para el programa "{programa_nombre}" eliminada exitosamente'
            )
            return redirect('solicitudes:listar_solicitudes')

        except Exception as e:
            messages.error(request, f'❌ Error al eliminar la solicitud: {str(e)}')
            return render(request, 'solicitudes/eliminar_solicitud.html', {'solicitud': solicitud})

    return render(request, 'solicitudes/eliminar_solicitud.html', {'solicitud': solicitud})


# ---------------------------------------------------------------------------
# CREAR SOLICITUD
# ---------------------------------------------------------------------------

@puede_editar_requerido
def crear_solicitud(request):
    """Vista para crear una nueva solicitud manualmente CON MODO MIGRACIÓN."""

    if request.method == 'POST':
        try:
            es_migracion = request.POST.get('es_migracion') == 'true'

            empresa_id        = request.POST.get('empresa')
            programa_id       = request.POST.get('programa')
            correo_remitente  = request.POST.get('correo_remitente')
            numero_aprendices = request.POST.get('numero_aprendices')
            observaciones     = request.POST.get('observaciones', '')
            documentos_pdf    = request.FILES.getlist('documentos_pdf')

            if not empresa_id:
                messages.error(request, '❌ Debes seleccionar una empresa')
                return redirect('solicitudes:crear_solicitud')

            try:
                empresa = Empresa.objects.get(id=empresa_id)
            except Empresa.DoesNotExist:
                messages.error(request, '❌ La empresa seleccionada no existe')
                return redirect('solicitudes:crear_solicitud')

            if not programa_id:
                messages.error(request, '❌ Debes seleccionar un programa')
                return redirect('solicitudes:crear_solicitud')

            try:
                programa = Programa.objects.get(id=programa_id, activo=True)
            except Programa.DoesNotExist:
                messages.error(request, '❌ El programa seleccionado no existe o no está activo')
                return redirect('solicitudes:crear_solicitud')

            from datetime import datetime

            # ================================================================
            # MODO MIGRACIÓN — fechas y estado personalizados
            # ================================================================
            if es_migracion:
                fecha_recepcion_str = request.POST.get('fecha_recepcion')
                if not fecha_recepcion_str:
                    messages.error(request, '❌ En modo migración, la fecha de recepción es obligatoria')
                    return redirect('solicitudes:crear_solicitud')

                try:
                    fecha_recepcion = timezone.make_aware(
                        datetime.strptime(fecha_recepcion_str, '%Y-%m-%dT%H:%M')
                    )
                    if fecha_recepcion > timezone.now():
                        messages.error(request, '❌ La fecha de recepción no puede ser futura')
                        return redirect('solicitudes:crear_solicitud')
                except ValueError:
                    messages.error(request, '❌ Formato de fecha de recepción inválido')
                    return redirect('solicitudes:crear_solicitud')

                fecha_atencion = None
                fecha_atencion_str = request.POST.get('fecha_atencion')
                if fecha_atencion_str:
                    try:
                        fecha_atencion = timezone.make_aware(
                            datetime.strptime(fecha_atencion_str, '%Y-%m-%dT%H:%M')
                        )
                        if fecha_atencion > timezone.now():
                            messages.error(request, '❌ La fecha de atención no puede ser futura')
                            return redirect('solicitudes:crear_solicitud')
                        if fecha_atencion < fecha_recepcion:
                            messages.error(request, '❌ La fecha de atención no puede ser anterior a la recepción')
                            return redirect('solicitudes:crear_solicitud')
                    except ValueError:
                        messages.warning(request, '⚠️ Formato de fecha de atención inválido, se omitirá')

                fecha_respuesta = None
                fecha_respuesta_str = request.POST.get('fecha_respuesta')
                if fecha_respuesta_str:
                    try:
                        fecha_respuesta = timezone.make_aware(
                            datetime.strptime(fecha_respuesta_str, '%Y-%m-%dT%H:%M')
                        )
                        if fecha_respuesta > timezone.now():
                            messages.error(request, '❌ La fecha de respuesta no puede ser futura')
                            return redirect('solicitudes:crear_solicitud')
                        fecha_minima_respuesta = fecha_atencion if fecha_atencion else fecha_recepcion
                        if fecha_respuesta < fecha_minima_respuesta:
                            messages.error(
                                request,
                                '❌ La fecha de respuesta no puede ser anterior a la atención '
                                '(flujo: Recibida → Atendida → Respondida)'
                            )
                            return redirect('solicitudes:crear_solicitud')
                    except ValueError:
                        messages.warning(request, '⚠️ Formato de fecha de respuesta inválido, se omitirá')

                fecha_finalizacion = None
                fecha_finalizacion_str = request.POST.get('fecha_finalizacion')
                if fecha_finalizacion_str:
                    try:
                        fecha_finalizacion = timezone.make_aware(
                            datetime.strptime(fecha_finalizacion_str, '%Y-%m-%dT%H:%M')
                        )
                        if fecha_finalizacion > timezone.now():
                            messages.error(request, '❌ La fecha de finalización no puede ser futura')
                            return redirect('solicitudes:crear_solicitud')
                        fecha_minima_fin = fecha_respuesta if fecha_respuesta else (
                            fecha_atencion if fecha_atencion else fecha_recepcion
                        )
                        if fecha_finalizacion < fecha_minima_fin:
                            messages.error(request, '❌ La fecha de finalización debe ser la más reciente')
                            return redirect('solicitudes:crear_solicitud')
                    except ValueError:
                        messages.warning(request, '⚠️ Formato de fecha de finalización inválido, se omitirá')

                if fecha_finalizacion:
                    estado = 'FINALIZADA'
                elif fecha_respuesta:
                    estado = 'RESPONDIDA'
                elif fecha_atencion:
                    estado = 'ATENDIDA'
                else:
                    estado = 'RECIBIDA'

                instructor = None
                instructor_id = request.POST.get('instructor_asignado')
                if instructor_id:
                    try:
                        instructor = Instructor.objects.get(id=instructor_id, activo=True)
                    except Instructor.DoesNotExist:
                        messages.warning(request, '⚠️ Instructor no encontrado, se creará sin instructor')

            # ================================================================
            # MODO NORMAL — todo automático, estado inicial RECIBIDA
            # ================================================================
            else:
                fecha_recepcion    = timezone.now()
                fecha_atencion     = None
                fecha_respuesta    = None
                fecha_finalizacion = None
                estado             = 'RECIBIDA'
                instructor         = None

            if len(documentos_pdf) > 5:
                messages.error(request, '❌ Máximo 5 documentos PDF permitidos')
                return redirect('solicitudes:crear_solicitud')

            for doc in documentos_pdf:
                if not doc.name.lower().endswith('.pdf'):
                    messages.error(request, f'❌ {doc.name} no es un archivo PDF')
                    return redirect('solicitudes:crear_solicitud')
                if doc.size > 10 * 1024 * 1024:
                    messages.error(request, f'❌ {doc.name} supera 10MB')
                    return redirect('solicitudes:crear_solicitud')

            with transaction.atomic():
                nueva_solicitud = Solicitud(
                    empresa=empresa,
                    programa=programa,
                    correo_remitente=correo_remitente or None,
                    observaciones=observaciones,
                    estado=estado,
                    fecha_recepcion=fecha_recepcion,
                    fecha_atencion=fecha_atencion,
                    fecha_respuesta=fecha_respuesta,
                    fecha_finalizacion=fecha_finalizacion,
                )

                if numero_aprendices:
                    try:
                        nueva_solicitud.numero_aprendices = int(numero_aprendices)
                    except ValueError:
                        nueva_solicitud.numero_aprendices = 0

                if es_migracion and instructor:
                    nueva_solicitud.instructor_asignado = instructor

                if documentos_pdf:
                    nueva_solicitud.documento_pdf = documentos_pdf[0]

                nueva_solicitud.save()

                from .models import DocumentoSolicitud
                for doc in documentos_pdf:
                    DocumentoSolicitud.objects.create(
                        solicitud=nueva_solicitud,
                        archivo=doc,
                        nombre_archivo=doc.name,
                    )

            if es_migracion:
                msg = f'✅ Solicitud #{nueva_solicitud.id} migrada exitosamente'
                if estado != 'RECIBIDA':
                    msg += f' con estado: {nueva_solicitud.get_estado_display()}'
                if instructor:
                    msg += ' e instructor asignado'
            else:
                msg = f'✅ Solicitud #{nueva_solicitud.id} creada exitosamente para {empresa.nombre}'

            if documentos_pdf:
                msg += f' con {len(documentos_pdf)} documento(s)'

            messages.success(request, msg)
            return redirect('solicitudes:detalle_solicitud', solicitud_id=nueva_solicitud.id)

        except Exception as e:
            messages.error(request, f'❌ Error al crear la solicitud: {str(e)}')
            import traceback
            traceback.print_exc()
            return redirect('solicitudes:crear_solicitud')

    # ── GET: mostrar formulario ──────────────────────────────────────────────
    empresas     = Empresa.objects.all().order_by('nombre')
    programas    = Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre')
    instructores = Instructor.objects.filter(activo=True).order_by('nombre')

    context = {
        'empresas':    empresas,
        'programas':   programas,
        'instructores': instructores,
        'ahora':       timezone.now(),
    }
    return render(request, 'solicitudes/crear_solicitud.html', context)