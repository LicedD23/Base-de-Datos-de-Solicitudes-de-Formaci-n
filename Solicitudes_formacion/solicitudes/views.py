"""
Vistas del módulo de solicitudes
Sistema de Gestión de Solicitudes SENA
"""

import io
import os
import re
import sys
import traceback
from datetime import timedelta, date, datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.db.models import Q, Count, Prefetch
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from empresas.models import Empresa
from instructores.models import Instructor
from instructores.views import verificar_solapamiento_instructor
from programas.models import Programa
from area_formacion.models import Area

from .email_handler import EmailSolicitudHandler
from .models import Solicitud, DocumentoSolicitud
from core.management.decorators import (
    puede_ver_requerido, puede_editar_requerido, admin_requerido
)


# =============================================================================
# CONSTANTES
# =============================================================================

# Nombres de los meses en español para formatear fechas en correos
MESES = {
    1: 'enero',    2: 'febrero',  3: 'marzo',    4: 'abril',
    5: 'mayo',     6: 'junio',    7: 'julio',     8: 'agosto',
    9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre',
}

# Límites para documentos PDF adjuntos
MAX_DOCUMENTOS  = 5
MAX_PDF_SIZE_MB = 10 * 1024 * 1024  # 10 MB en bytes


# =============================================================================
# HELPERS INTERNOS
# =============================================================================

def _get_queryset_solicitudes_base():
    """
    Retorna el queryset base de solicitudes con todos los select_related necesarios.
    Centralizado para no repetirlo en cada vista.
    """
    return Solicitud.objects.select_related(
        'empresa',
        'programa',
        'programa__area',
        'instructor_asignado',
    )


def _parsear_fecha(fecha_str, fmt='%Y-%m-%dT%H:%M'):
    """
    Convierte un string de fecha al formato dado en un datetime aware.
    Retorna el datetime o None si el string está vacío.
    Lanza ValueError si el formato no es válido.
    """
    if not fecha_str:
        return None
    return timezone.make_aware(datetime.strptime(fecha_str, fmt))


def _validar_documentos_pdf(documentos, documentos_actuales=0, documentos_a_eliminar=0):
    """
    Valida una lista de archivos PDF subidos por el usuario.
    Verifica extensión, tamaño y que el total no supere MAX_DOCUMENTOS.

    Retorna (es_valido: bool, mensaje_error: str | None).
    """
    total = documentos_actuales - documentos_a_eliminar + len(documentos)

    if total > MAX_DOCUMENTOS:
        return False, (
            f'❌ Máximo {MAX_DOCUMENTOS} documentos permitidos. '
            f'Total resultante: {total}'
        )

    for doc in documentos:
        if not doc.name.lower().endswith('.pdf'):
            return False, f'❌ {doc.name} no es un archivo PDF'
        if doc.size > MAX_PDF_SIZE_MB:
            return False, f'❌ {doc.name} supera 10MB'

    return True, None


def _validar_fechas_migracion(fecha_recepcion, fecha_atencion,
                               fecha_respuesta, fecha_finalizacion):
    """
    Valida que las fechas de migración cumplan el flujo correcto:
        recepcion ≤ atencion ≤ respuesta ≤ finalizacion
    y que ninguna sea futura.

    Retorna (es_valido: bool, mensaje_error: str | None).
    """
    ahora = timezone.now()

    validaciones = [
        (fecha_recepcion    and fecha_recepcion    > ahora,
         '❌ La fecha de recepción no puede ser futura'),
        (fecha_atencion     and fecha_atencion     > ahora,
         '❌ La fecha de atención no puede ser futura'),
        (fecha_atencion     and fecha_atencion     < fecha_recepcion,
         '❌ La fecha de atención no puede ser anterior a la recepción'),
        (fecha_respuesta    and fecha_respuesta    > ahora,
         '❌ La fecha de respuesta no puede ser futura'),
        (fecha_respuesta    and fecha_respuesta    < (fecha_atencion or fecha_recepcion),
         '❌ La fecha de respuesta no puede ser anterior a la atención'),
        (fecha_finalizacion and fecha_finalizacion > ahora,
         '❌ La fecha de finalización no puede ser futura'),
        (fecha_finalizacion and fecha_finalizacion < (
            fecha_respuesta or fecha_atencion or fecha_recepcion
        ), '❌ La fecha de finalización debe ser la más reciente'),
    ]

    for condicion, mensaje in validaciones:
        if condicion:
            return False, mensaje

    return True, None


def _deducir_estado_migracion(fecha_atencion, fecha_respuesta, fecha_finalizacion):
    """
    Deduce el estado de la solicitud según las fechas ingresadas en modo migración.
    Sigue el flujo: RECIBIDA → ATENDIDA → RESPONDIDA → FINALIZADA
    """
    if fecha_finalizacion:
        return 'FINALIZADA'
    if fecha_respuesta:
        return 'RESPONDIDA'
    if fecha_atencion:
        return 'ATENDIDA'
    return 'RECIBIDA'


def _calcular_disponibilidad_instructores(instructores, solicitud_actual=None):
    """
    Recibe un queryset de Instructor y devuelve una lista de dicts con
    información de disponibilidad de cada uno para hoy.

    Cada dict contiene:
        instructor          → objeto Instructor
        ocupado             → True si tiene formación activa hoy
        formaciones_activas → lista de solicitudes activas hoy
        proxima             → próxima solicitud futura (si no está ocupado)
        formaciones_json    → JSON serializable con todas las formaciones programadas
                              (para la validación de solapamiento en el frontend)

    El parámetro solicitud_actual excluye esa solicitud del cálculo,
    útil al editar para no contar la propia solicitud como ocupación.
    """
    hoy       = timezone.now().date()
    resultado = []

    for instructor in instructores:
        qs = instructor.solicitud_set.filter(
            fecha_atencion__isnull=False,
        ).exclude(estado='FINALIZADA')

        if solicitud_actual:
            qs = qs.exclude(pk=solicitud_actual.pk)

        ocupado_hoy         = False
        formaciones_activas = []
        formaciones_json    = []  # Para serialización al frontend

        for sol in qs.select_related('empresa', 'programa'):
            fecha_inicio = sol.fecha_atencion.date()
            fecha_fin    = sol.fecha_fin_formacion or (
                sol.fecha_finalizacion.date() if sol.fecha_finalizacion else None
            )

            if fecha_inicio <= hoy and (fecha_fin is None or fecha_fin >= hoy):
                ocupado_hoy = True
                formaciones_activas.append(sol)

            # Agregar al JSON para validación de solapamiento en frontend
            formaciones_json.append({
                'solicitud_id': sol.id,
                'empresa':      sol.empresa.nombre,
                'programa':     sol.programa.nombre,
                'fecha_inicio': fecha_inicio.isoformat(),
                'fecha_fin':    fecha_fin.isoformat() if fecha_fin else None,
            })

        proxima = None
        if not ocupado_hoy:
            proxima_qs = instructor.solicitud_set.filter(
                fecha_atencion__isnull=False,
                fecha_atencion__date__gt=hoy,
            ).exclude(estado='FINALIZADA')

            if solicitud_actual:
                proxima_qs = proxima_qs.exclude(pk=solicitud_actual.pk)

            proxima = proxima_qs.order_by('fecha_atencion').first()

        resultado.append({
            'instructor':          instructor,
            'ocupado':             ocupado_hoy,
            'formaciones_activas': formaciones_activas,
            'proxima':             proxima,
            'formaciones_json':    formaciones_json,
        })

    return resultado


def _guardar_documentos(solicitud, documentos_pdf):
    """
    Guarda una lista de archivos PDF como DocumentoSolicitud asociados a la solicitud.
    El primer documento también se asigna como documento_pdf principal.
    """
    for doc in documentos_pdf:
        DocumentoSolicitud.objects.create(
            solicitud=solicitud,
            archivo=doc,
            nombre_archivo=doc.name,
        )
    if documentos_pdf:
        solicitud.documento_pdf = documentos_pdf[0]
        solicitud.save(update_fields=['documento_pdf'])


def _eliminar_documentos(solicitud, ids_a_eliminar):
    """
    Elimina los DocumentoSolicitud con los IDs dados, incluyendo el archivo físico.
    Retorna el número de documentos eliminados.
    """
    eliminados = 0
    for doc_id in ids_a_eliminar:
        try:
            documento = DocumentoSolicitud.objects.get(id=doc_id, solicitud=solicitud)
            if documento.archivo and os.path.exists(documento.archivo.path):
                os.remove(documento.archivo.path)
            documento.delete()
            eliminados += 1
        except DocumentoSolicitud.DoesNotExist:
            pass
        except Exception as e:
            print(f"⚠️ Error al eliminar documento {doc_id}: {e}")
    return eliminados


# =============================================================================
# VISTAS
# =============================================================================

@puede_ver_requerido
def listar_solicitudes(request):
    """Vista para listar todas las solicitudes con filtros."""
    search          = request.GET.get('search', '')
    estado          = request.GET.get('estado', '')
    programa_id     = request.GET.get('programa', '')
    empresa_id      = request.GET.get('empresa', '')
    periodo_filter  = request.GET.get('periodo', '')

    solicitudes = _get_queryset_solicitudes_base().all()

    # ── Filtros de búsqueda ───────────────────────────────────────────────────
    if search:
        solicitudes = solicitudes.filter(
            Q(empresa__nombre__icontains=search)          |
            Q(programa__nombre__icontains=search)         |
            Q(instructor_asignado__nombre__icontains=search)
        )

    if estado:
        solicitudes = solicitudes.filter(estado=estado)
    if programa_id:
        solicitudes = solicitudes.filter(programa_id=programa_id)
    if empresa_id:
        solicitudes = solicitudes.filter(empresa_id=empresa_id)

    # ── Filtro de periodo ─────────────────────────────────────────────────────
    if periodo_filter:
        hoy = timezone.now().date()
        periodos = {
            'hoy':       lambda qs: qs.filter(fecha_recepcion=hoy),
            'semana':    lambda qs: qs.filter(fecha_recepcion__gte=hoy - timedelta(days=7)),
            'mes':       lambda qs: qs.filter(fecha_recepcion__gte=hoy - timedelta(days=30)),
            'trimestre': lambda qs: qs.filter(fecha_recepcion__gte=hoy - timedelta(days=90)),
        }
        if periodo_filter in periodos:
            solicitudes = periodos[periodo_filter](solicitudes)

    solicitudes = solicitudes.order_by('-fecha_recepcion')

    # ── Estadísticas ──────────────────────────────────────────────────────────
    stats = {
        'RECIBIDA':   solicitudes.filter(estado='RECIBIDA').count(),
        'ATENDIDA':   solicitudes.filter(estado='ATENDIDA').count(),
        'RESPONDIDA': solicitudes.filter(estado='RESPONDIDA').count(),
        'FINALIZADA': solicitudes.filter(estado='FINALIZADA').count(),
    }

    context = {
        'solicitudes':             solicitudes,
        'programas':               Programa.objects.filter(activo=True).select_related('area').order_by('nombre'),
        'empresas':                Empresa.objects.all().order_by('nombre'),
        'search':                  search,
        'estado_filter':           estado,
        'programa_filter':         programa_id,
        'empresa_filter':          empresa_id,
        'periodo_filter':          periodo_filter,
        'total_solicitudes':       solicitudes.count(),
        'solicitudes_recibidas':   stats['RECIBIDA'],
        'solicitudes_atendidas':   stats['ATENDIDA'],
        'solicitudes_respondidas': stats['RESPONDIDA'],
        'solicitudes_finalizadas': stats['FINALIZADA'],
        'stats_por_estado':        stats,
        'ESTADOS_CHOICES':         Solicitud.ESTADO_CHOICES,
    }
    return render(request, 'solicitudes/listar_solicitudes.html', context)


@puede_ver_requerido
def panel_correos(request):
    """Panel de administración de correos entrantes."""
    if request.method == 'POST':
        if request.POST.get('action') == 'procesar':
            try:
                handler             = EmailSolicitudHandler()
                solicitudes_creadas = handler.procesar_correos()

                if solicitudes_creadas:
                    messages.success(
                        request,
                        f'✅ {len(solicitudes_creadas)} correo(s) procesados. '
                        f'Se crearon {len(solicitudes_creadas)} solicitud(es).'
                    )
                else:
                    messages.warning(request, '⚠️ No se encontraron correos nuevos.')
            except Exception as e:
                messages.error(request, f'❌ Error procesando correos: {str(e)}')

        return redirect('solicitudes:panel_correos')

    hoy         = timezone.now().date()
    hace_7_dias = hoy - timedelta(days=7)

    context = {
        'solicitudes_hoy':    Solicitud.objects.filter(fecha_recepcion__date=hoy).count(),
        'solicitudes_semana': Solicitud.objects.filter(fecha_recepcion__date__gte=hace_7_dias).count(),
        'ultimas_solicitudes': Solicitud.objects.select_related(
            'empresa', 'programa'
        ).order_by('-fecha_recepcion')[:10],
    }
    return render(request, 'solicitudes/panel_correos.html', context)


@puede_editar_requerido
def probar_conexion_email(request):
    """Prueba la conexión al servidor IMAP y retorna el resultado como JSON."""
    try:
        handler = EmailSolicitudHandler()
        mail    = handler.conectar_email()

        if mail:
            mail.select('INBOX')
            mail.logout()
            return JsonResponse({
                'success': True,
                'message': (
                    f'✅ Conexión exitosa\n'
                    f'Usuario: {handler.email_account}\n'
                    f'Servidor: {handler.imap_server}:{handler.imap_port}'
                ),
            })

        return JsonResponse({
            'success': False,
            'message': '❌ No se pudo conectar. Verifica EMAIL_HOST_USER y EMAIL_HOST_PASSWORD.',
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'❌ Error: {str(e)}\n\n{traceback.format_exc()}',
        })


@puede_ver_requerido
def detalle_solicitud(request, solicitud_id):
    """Vista de solo lectura para ver el detalle completo de una solicitud."""
    solicitud = get_object_or_404(_get_queryset_solicitudes_base(), id=solicitud_id)
    return render(request, 'solicitudes/detalle_solicitud.html', {'solicitud': solicitud})


@puede_editar_requerido
def editar_solicitud(request, solicitud_id):
    """
    Vista para editar una solicitud existente.
    Soporta dos modos:
        - Normal:    solo permite avanzar en el flujo (RECIBIDA→ATENDIDA→RESPONDIDA→FINALIZADA)
        - Migración: permite ingresar fechas históricas para datos importados
    """
    solicitud = get_object_or_404(
        _get_queryset_solicitudes_base().prefetch_related('documentos'),
        id=solicitud_id,
    )

    if request.method == 'POST':
        try:
            es_migracion = request.POST.get('es_migracion') == 'true'

            # ── Leer campos básicos del formulario ────────────────────────────
            estado            = request.POST.get('estado')
            instructor_id     = request.POST.get('instructor_asignado')
            observaciones     = request.POST.get('observaciones', '')
            numero_aprendices = request.POST.get('numero_aprendices')
            nuevos_pdfs       = request.FILES.getlist('documentos_pdf')
            eliminar_pdf      = request.POST.get('eliminar_pdf')
            ids_a_eliminar    = request.POST.getlist('eliminar_documentos')

            # ── Fechas de programación (inicio y fin de formación) ─────────
            try:
                fecha_inicio_formacion = _parsear_fecha(
                    request.POST.get('fecha_inicio_formacion'), '%Y-%m-%d'
                )
            except ValueError:
                messages.warning(request, '⚠️ Fecha de inicio de formación inválida, se omitirá')
                fecha_inicio_formacion = None

            try:
                fecha_fin_formacion = _parsear_fecha(
                    request.POST.get('fecha_fin_formacion'), '%Y-%m-%d'
                )
            except ValueError:
                messages.warning(request, '⚠️ Fecha fin de formación inválida, se omitirá')
                fecha_fin_formacion = None

            # Validar que fin no sea anterior a inicio
            if fecha_inicio_formacion and fecha_fin_formacion:
                if fecha_fin_formacion < fecha_inicio_formacion:
                    messages.error(request, '❌ La fecha fin no puede ser anterior a la fecha de inicio')
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

            if not estado and not es_migracion:
                messages.error(request, '❌ El estado es obligatorio')
                return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

            # ── Validaciones específicas de cada modo ─────────────────────────
            if es_migracion:
                # En modo migración se leen y validan todas las fechas históricas
                try:
                    fecha_recepcion = _parsear_fecha(request.POST.get('fecha_recepcion'))
                    if not fecha_recepcion:
                        messages.error(request, '❌ La fecha de recepción es obligatoria en modo migración')
                        return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
                except ValueError:
                    messages.error(request, '❌ Formato de fecha de recepción inválido')
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

                try:
                    fecha_atencion     = _parsear_fecha(request.POST.get('fecha_atencion'))
                    fecha_respuesta    = _parsear_fecha(request.POST.get('fecha_respuesta'))
                    fecha_finalizacion = _parsear_fecha(request.POST.get('fecha_finalizacion'))
                except ValueError as e:
                    messages.warning(request, f'⚠️ Fecha inválida omitida: {e}')
                    fecha_atencion = fecha_respuesta = fecha_finalizacion = None

                es_valido, error = _validar_fechas_migracion(
                    fecha_recepcion, fecha_atencion, fecha_respuesta, fecha_finalizacion
                )
                if not es_valido:
                    messages.error(request, error)
                    return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

                # El estado se deduce automáticamente de las fechas ingresadas
                estado = _deducir_estado_migracion(fecha_atencion, fecha_respuesta, fecha_finalizacion)

            else:
                # En modo normal se conservan las fechas actuales de la solicitud
                fecha_recepcion    = solicitud.fecha_recepcion
                fecha_atencion     = solicitud.fecha_atencion
                fecha_respuesta    = solicitud.fecha_respuesta
                fecha_finalizacion = solicitud.fecha_finalizacion

                # Validar que el cambio de estado siga el flujo correcto
                if estado != solicitud.estado:
                    if not solicitud.puede_cambiar_a_estado(estado):
                        labels = dict(Solicitud.ESTADO_CHOICES)
                        messages.error(
                            request,
                            f'❌ No puedes cambiar de "{solicitud.get_estado_display()}" '
                            f'a "{labels.get(estado, estado)}". '
                            f'Flujo: Recibida → Atendida → Respondida → Finalizada'
                        )
                        return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

                # Validaciones de negocio según el estado destino
                validaciones_estado = [
                    (estado == 'ATENDIDA' and not instructor_id and not solicitud.instructor_asignado,
                     '❌ Debes asignar un instructor para marcar la solicitud como ATENDIDA'),
                    (estado == 'RESPONDIDA' and not solicitud.fecha_atencion,
                     '❌ La solicitud debe estar ATENDIDA antes de marcarla como RESPONDIDA'),
                    (estado == 'FINALIZADA' and not solicitud.fecha_respuesta,
                     '❌ La solicitud debe estar RESPONDIDA antes de finalizarla'),
                ]
                for condicion, mensaje in validaciones_estado:
                    if condicion:
                        messages.error(request, mensaje)
                        return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

            # ── Validar solapamiento de fechas del instructor ─────────────────
            # Solo aplica en modo normal (no migración) cuando hay instructor
            # asignado y fechas de formación definidas.
            if not es_migracion and instructor_id:
                # Calcular fechas efectivas de la nueva asignación
                nueva_fecha_inicio = (
                    fecha_inicio_formacion.date()
                    if fecha_inicio_formacion and hasattr(fecha_inicio_formacion, 'date')
                    else fecha_inicio_formacion
                )
                nueva_fecha_fin = (
                    fecha_fin_formacion.date()
                    if fecha_fin_formacion and hasattr(fecha_fin_formacion, 'date')
                    else fecha_fin_formacion
                )

                # Usar fecha de atención existente si no se ingresó una nueva
                if not nueva_fecha_inicio and solicitud.fecha_atencion:
                    nueva_fecha_inicio = solicitud.fecha_atencion.date()

                if nueva_fecha_inicio:
                    try:
                        instructor_candidato = Instructor.objects.get(id=instructor_id, activo=True)
                        hay_conflicto, conflictos = verificar_solapamiento_instructor(
                            instructor=instructor_candidato,
                            fecha_inicio=nueva_fecha_inicio,
                            fecha_fin=nueva_fecha_fin,
                            excluir_solicitud_id=solicitud.id,
                        )
                        if hay_conflicto:
                            detalle = ' | '.join(
                                f"{c['empresa']} ({c['fecha_inicio']} – {c['fecha_fin']})"
                                for c in conflictos
                            )
                            messages.error(
                                request,
                                f'❌ El instructor "{instructor_candidato.nombre}" ya tiene '
                                f'formaciones programadas que se solapan con las fechas indicadas: '
                                f'{detalle}. Elige otro instructor o ajusta las fechas.'
                            )
                            return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)
                    except Instructor.DoesNotExist:
                        pass  # Se maneja más adelante

            # ── Validar documentos PDF ────────────────────────────────────────
            es_valido, error = _validar_documentos_pdf(
                nuevos_pdfs,
                documentos_actuales=solicitud.documentos.count(),
                documentos_a_eliminar=len(ids_a_eliminar),
            )
            if not es_valido:
                messages.error(request, error)
                return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

            # ── Guardar cambios en una transacción atómica ────────────────────
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
                        messages.warning(request, '⚠️ Número de aprendices inválido, se mantiene el valor anterior')

                # ── Asignar o remover instructor ──────────────────────────────
                instructor_anterior = solicitud.instructor_asignado
                if instructor_id:
                    try:
                        instructor = Instructor.objects.get(id=instructor_id, activo=True)
                        solicitud.instructor_asignado = instructor
                        if not es_migracion and solicitud.estado == 'RECIBIDA':
                            solicitud.estado = 'ATENDIDA'
                            messages.success(
                                request,
                                f'✅ Instructor "{instructor.nombre}" asignado. '
                                f'Estado cambiado a ATENDIDA.'
                            )
                        else:
                            messages.success(request, f'✅ Instructor "{instructor.nombre}" asignado')
                    except Instructor.DoesNotExist:
                        messages.warning(request, '⚠️ Instructor no encontrado')
                else:
                    solicitud.instructor_asignado = None
                    if instructor_anterior:
                        messages.info(request, f'ℹ️ Instructor "{instructor_anterior.nombre}" removido')

                # ── Aplicar fechas de programación ────────────────────────────
                if fecha_inicio_formacion is not None:
                    solicitud.fecha_atencion = timezone.make_aware(
                        datetime.combine(fecha_inicio_formacion.date()
                        if hasattr(fecha_inicio_formacion, 'date') else fecha_inicio_formacion,
                        datetime.min.time())
                    )
                solicitud.fecha_fin_formacion = (
                    fecha_fin_formacion.date()
                    if fecha_fin_formacion and hasattr(fecha_fin_formacion, 'date')
                    else fecha_fin_formacion
                )

                # ── Auto-finalizar si la fecha fin ya se cumplió ──────────────
                hoy = timezone.now().date()
                if (
                    not es_migracion
                    and solicitud.fecha_fin_formacion
                    and solicitud.fecha_fin_formacion <= hoy
                    and solicitud.estado in ('ATENDIDA', 'RESPONDIDA')
                ):
                    solicitud.estado = 'FINALIZADA'
                    if not solicitud.fecha_finalizacion:
                        solicitud.fecha_finalizacion = timezone.now()
                    messages.success(request, '🎓 Solicitud finalizada automáticamente por fecha de formación cumplida.')

                # ── Gestionar documentos ──────────────────────────────────────
                if ids_a_eliminar:
                    eliminados = _eliminar_documentos(solicitud, ids_a_eliminar)
                    messages.success(request, f'✅ {eliminados} documento(s) eliminado(s)')

                if nuevos_pdfs:
                    _guardar_documentos(solicitud, nuevos_pdfs)
                    messages.success(request, f'✅ {len(nuevos_pdfs)} documento(s) agregado(s)')

                if eliminar_pdf == 'on' and solicitud.documento_pdf:
                    try:
                        if os.path.exists(solicitud.documento_pdf.path):
                            os.remove(solicitud.documento_pdf.path)
                    except Exception:
                        pass
                    solicitud.documento_pdf = None
                    messages.info(request, 'ℹ️ Documento PDF principal eliminado')

                # ── Registrar fechas de cambio de estado automáticamente ──────
                if not es_migracion:
                    now = timezone.now()
                    if estado == 'RESPONDIDA' and not solicitud.fecha_respuesta:
                        solicitud.fecha_respuesta = now
                    if estado == 'FINALIZADA' and not solicitud.fecha_finalizacion:
                        solicitud.fecha_finalizacion = now

                solicitud.save()

            msg = (
                f'✅ Solicitud #{solicitud.id} actualizada en modo migración '
                f'con estado: {solicitud.get_estado_display()}'
                if es_migracion
                else f'✅ Solicitud #{solicitud.id} actualizada exitosamente'
            )
            messages.success(request, msg)
            return redirect('solicitudes:detalle_solicitud', solicitud_id=solicitud.id)

        except Exception as e:
            messages.error(request, f'❌ Error al actualizar la solicitud: {str(e)}')
            traceback.print_exc()
            return redirect('solicitudes:editar_solicitud', solicitud_id=solicitud_id)

    # ── GET ───────────────────────────────────────────────────────────────────
    instructores_qs   = Instructor.objects.filter(activo=True).order_by('nombre')
    disponibilidad    = _calcular_disponibilidad_instructores(instructores_qs, solicitud_actual=solicitud)
    especializados_ids = set(
        instructores_qs.filter(especialidad=solicitud.programa).values_list('id', flat=True)
    )

    context = {
        'solicitud':                        solicitud,
        'instructores_info':                disponibilidad,
        'instructores_especializados_info': [d for d in disponibilidad if d['instructor'].id in especializados_ids],
        'instructores':                     instructores_qs,
        'instructores_especializados':      instructores_qs.filter(especialidad=solicitud.programa),
        'programas':                        Programa.objects.filter(activo=True).select_related('area').order_by('nombre'),
        'ESTADO_CHOICES':                   Solicitud.ESTADO_CHOICES,
        'documentos_actuales':              DocumentoSolicitud.objects.filter(solicitud=solicitud).order_by('-fecha_subida'),
        'ahora':                            timezone.now(),
    }
    return render(request, 'solicitudes/editar_solicitud.html', context)


@puede_editar_requerido
def enviar_respuesta(request, solicitud_id):
    """
    Vista para enviar correo de respuesta a la empresa.
    Cambia el estado de ATENDIDA a RESPONDIDA al enviar.
    """
    solicitud = get_object_or_404(_get_queryset_solicitudes_base(), id=solicitud_id)

    if request.method == 'POST':
        try:
            # ── Validaciones de negocio antes de enviar ───────────────────────
            validaciones = [
                (solicitud.estado == 'RECIBIDA',
                 '❌ Debes asignar un instructor primero (flujo: Recibida → Atendida → Respondida).'),
                (solicitud.estado == 'ATENDIDA' and not solicitud.instructor_asignado,
                 '❌ La solicitud está ATENDIDA pero sin instructor. Asigna uno antes de responder.'),
            ]
            for condicion, mensaje in validaciones:
                if condicion:
                    messages.error(request, mensaje)
                    return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

            mensaje = request.POST.get('mensaje')
            if not mensaje:
                messages.error(request, '❌ El mensaje es obligatorio')
                return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

            correo_destino = solicitud.correo_remitente or solicitud.empresa.correo
            if not correo_destino:
                messages.error(request, '❌ No hay correo de destino disponible')
                return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

            if '@ejemplo.com' in correo_destino.lower():
                messages.error(request, '❌ No se puede enviar a una dirección de ejemplo')
                return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

            from django.core.mail import EmailMessage
            from django.conf import settings

            # Copiar al instructor si tiene correo registrado
            cc_list = []
            if solicitud.instructor_asignado and solicitud.instructor_asignado.correo:
                cc_list.append(solicitud.instructor_asignado.correo)

            EmailMessage(
                subject=f"Respuesta a Solicitud #{solicitud.id} - {solicitud.programa.nombre}",
                body=mensaje,
                from_email=settings.EMAIL_HOST_USER,
                to=[correo_destino],
                cc=cc_list,
            ).send(fail_silently=False)

            if solicitud.estado == 'ATENDIDA':
                solicitud.estado          = 'RESPONDIDA'
                solicitud.fecha_respuesta = timezone.now()
                solicitud.save()

            cc_msg = f' (CC: {", ".join(cc_list)})' if cc_list else ''
            messages.success(request, f'✅ Correo enviado a {correo_destino}{cc_msg}.')
            return redirect('solicitudes:detalle_solicitud', solicitud_id=solicitud.id)

        except Exception as e:
            messages.error(request, f'❌ Error al enviar el correo: {str(e)}')
            return redirect('solicitudes:enviar_respuesta', solicitud_id=solicitud_id)

    # ── GET ───────────────────────────────────────────────────────────────────
    def _fmt_fecha_texto(fecha):
        """Formatea una fecha como '15 de marzo de 2025' para el cuerpo del correo."""
        if not fecha:
            return ''
        return f"{fecha.day} de {MESES[fecha.month]} de {fecha.year}"

    context = {
        'solicitud':          solicitud,
        'destinatario_email': solicitud.correo_remitente or solicitud.empresa.correo,
        'fecha_inicio_texto': _fmt_fecha_texto(solicitud.fecha_atencion),
        'fecha_fin_texto':    _fmt_fecha_texto(solicitud.fecha_fin_formacion),
    }
    return render(request, 'solicitudes/enviar_respuesta.html', context)


@puede_editar_requerido
def procesar_correos_ajax(request):
    """
    Procesa correos y retorna logs en tiempo real para mostrar en el panel.
    Captura el stdout del handler para construir la respuesta JSON con logs.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured

    try:
        handler             = EmailSolicitudHandler()
        solicitudes_creadas = handler.procesar_correos()
        sys.stdout          = old_stdout
        output              = captured.getvalue()

        # ── Clasificar cada línea del output para colorearla en el frontend ──
        logs = []
        for linea in output.split('\n'):
            if not linea.strip():
                continue

            tipo = 'info'
            if '=' * 50 in linea or '-' * 50 in linea:
                tipo = 'separator'
            elif any(k in linea for k in ('INICIANDO', 'PROCESANDO', 'CORREO', 'RESUMEN')):
                tipo = 'section'
            elif 'Conectado exitosamente' in linea or 'Solicitud creada' in linea:
                tipo = 'success'
            elif 'ERROR' in linea or 'Error' in linea:
                tipo = 'error'
            elif 'No encontrado' in linea or 'no encontrado' in linea.lower():
                tipo = 'warning'

            entrada = {'message': linea.strip(), 'type': tipo}

            match_sol = re.search(r'#(\d+)', linea)
            if match_sol and tipo == 'success':
                entrada['solicitud_id'] = int(match_sol.group(1))

            match_count = re.search(r'(\d+)', linea)
            if 'Correos no leídos' in linea and match_count:
                entrada['count'] = int(match_count.group(1))

            logs.append(entrada)

        return JsonResponse({
            'success':           True,
            'solicitudes_count': len(solicitudes_creadas),
            'solicitudes': [
                {
                    'id':       s.id,
                    'empresa':  s.empresa.nombre,
                    'programa': s.programa.nombre,
                    'estado':   s.get_estado_display(),
                    'fecha':    s.fecha_recepcion.strftime('%d/%m/%Y %H:%M'),
                }
                for s in solicitudes_creadas
            ],
            'logs':       logs,
            'raw_output': output,
        })

    except Exception as e:
        sys.stdout = old_stdout
        return JsonResponse({
            'success':   False,
            'error':     str(e),
            'traceback': traceback.format_exc(),
            'logs': [
                {'type': 'error', 'message': f'❌ ERROR: {str(e)}'},
                {'type': 'error', 'message': traceback.format_exc()},
            ],
        }, status=500)


@puede_editar_requerido
@require_http_methods(["GET", "POST"])
def eliminar_solicitud(request, solicitud_id):
    """Vista para eliminar permanentemente una solicitud y su PDF asociado."""
    solicitud = get_object_or_404(_get_queryset_solicitudes_base(), id=solicitud_id)
    template  = 'solicitudes/eliminar_solicitud.html'
    ctx       = {'solicitud': solicitud}

    if request.method == 'POST':
        # Las solicitudes finalizadas requieren confirmación explícita
        if solicitud.estado == 'FINALIZADA':
            if request.POST.get('confirmar_finalizada') != 'confirmar':
                messages.warning(request, '⚠️ Debes confirmar la eliminación de una solicitud finalizada')
                return render(request, template, ctx)

        empresa_nombre  = solicitud.empresa.nombre
        programa_nombre = solicitud.programa.nombre
        sol_id          = solicitud.id

        try:
            with transaction.atomic():
                if solicitud.documento_pdf:
                    try:
                        if os.path.isfile(solicitud.documento_pdf.path):
                            os.remove(solicitud.documento_pdf.path)
                    except Exception as e:
                        print(f"⚠️ Error al eliminar PDF: {e}")
                solicitud.delete()

            messages.success(
                request,
                f'✅ Solicitud #{sol_id} de "{empresa_nombre}" '
                f'para "{programa_nombre}" eliminada exitosamente'
            )
            return redirect('solicitudes:listar_solicitudes')

        except Exception as e:
            messages.error(request, f'❌ Error al eliminar: {str(e)}')
            return render(request, template, ctx)

    return render(request, template, ctx)


@puede_editar_requerido
def crear_solicitud(request):
    """
    Vista para crear una nueva solicitud manualmente.
    Soporta modo migración igual que editar_solicitud.
    """
    if request.method == 'POST':
        try:
            es_migracion      = request.POST.get('es_migracion') == 'true'
            empresa_id        = request.POST.get('empresa')
            programa_id       = request.POST.get('programa')
            correo_remitente  = request.POST.get('correo_remitente')
            numero_aprendices = request.POST.get('numero_aprendices')
            observaciones     = request.POST.get('observaciones', '')
            razon_cupo        = request.POST.get('razon_cupo', '')
            documentos_pdf    = request.FILES.getlist('documentos_pdf')

            if razon_cupo:
                observaciones = f"{observaciones}\n[Razón cupo reducido]: {razon_cupo}".strip()

            # ── Validar empresa y programa ────────────────────────────────────
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
                messages.error(request, '❌ El programa no existe o no está activo')
                return redirect('solicitudes:crear_solicitud')

            # ── Fechas e instructor según el modo ─────────────────────────────
            if es_migracion:
                try:
                    fecha_recepcion = _parsear_fecha(request.POST.get('fecha_recepcion'))
                    if not fecha_recepcion:
                        messages.error(request, '❌ La fecha de recepción es obligatoria en modo migración')
                        return redirect('solicitudes:crear_solicitud')
                except ValueError:
                    messages.error(request, '❌ Formato de fecha de recepción inválido')
                    return redirect('solicitudes:crear_solicitud')

                try:
                    fecha_atencion     = _parsear_fecha(request.POST.get('fecha_atencion'))
                    fecha_respuesta    = _parsear_fecha(request.POST.get('fecha_respuesta'))
                    fecha_finalizacion = _parsear_fecha(request.POST.get('fecha_finalizacion'))
                except ValueError as e:
                    messages.warning(request, f'⚠️ Fecha inválida omitida: {e}')
                    fecha_atencion = fecha_respuesta = fecha_finalizacion = None

                es_valido, error = _validar_fechas_migracion(
                    fecha_recepcion, fecha_atencion, fecha_respuesta, fecha_finalizacion
                )
                if not es_valido:
                    messages.error(request, error)
                    return redirect('solicitudes:crear_solicitud')

                estado = _deducir_estado_migracion(fecha_atencion, fecha_respuesta, fecha_finalizacion)

                instructor = None
                instructor_id = request.POST.get('instructor_asignado')
                if instructor_id:
                    try:
                        instructor = Instructor.objects.get(id=instructor_id, activo=True)
                    except Instructor.DoesNotExist:
                        messages.warning(request, '⚠️ Instructor no encontrado, se creará sin instructor')

            else:
                # Modo normal: fecha actual, estado inicial, sin instructor
                fecha_recepcion    = timezone.now()
                fecha_atencion     = None
                fecha_respuesta    = None
                fecha_finalizacion = None
                estado             = 'RECIBIDA'
                instructor         = None

            # ── Validar documentos PDF ────────────────────────────────────────
            es_valido, error = _validar_documentos_pdf(documentos_pdf)
            if not es_valido:
                messages.error(request, error)
                return redirect('solicitudes:crear_solicitud')

            # ── Crear solicitud en una transacción atómica ────────────────────
            with transaction.atomic():
                nueva = Solicitud(
                    empresa=empresa, programa=programa,
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
                        nueva.numero_aprendices = int(numero_aprendices)
                    except ValueError:
                        nueva.numero_aprendices = 0

                if es_migracion and instructor:
                    nueva.instructor_asignado = instructor

                if documentos_pdf:
                    nueva.documento_pdf = documentos_pdf[0]

                nueva.save()
                _guardar_documentos(nueva, documentos_pdf)

            # ── Construir mensaje de éxito ────────────────────────────────────
            if es_migracion:
                msg = f'✅ Solicitud #{nueva.id} migrada con estado: {nueva.get_estado_display()}'
                if instructor:
                    msg += ' e instructor asignado'
            else:
                msg = f'✅ Solicitud #{nueva.id} creada para {empresa.nombre}'

            if documentos_pdf:
                msg += f' con {len(documentos_pdf)} documento(s)'

            messages.success(request, msg)
            return redirect('solicitudes:detalle_solicitud', solicitud_id=nueva.id)

        except Exception as e:
            messages.error(request, f'❌ Error al crear la solicitud: {str(e)}')
            traceback.print_exc()
            return redirect('solicitudes:crear_solicitud')

    # ── GET ───────────────────────────────────────────────────────────────────
    context = {
        'empresas':     Empresa.objects.all().order_by('nombre'),
        'programas':    Programa.objects.filter(activo=True).select_related('area').order_by('area__nombre', 'nombre'),
        'instructores': Instructor.objects.filter(activo=True).order_by('nombre'),
        'ahora':        timezone.now(),
    }
    return render(request, 'solicitudes/crear_solicitud.html', context)


def guia_solicitud(request):
    """Guía pública para que empresas sepan cómo enviar solicitudes."""
    return render(request, 'solicitudes/guia_solicitud_formacion.html', {
        'from_solicitud_id': request.GET.get('from'),
    })


def catalogo_programas(request):
    """Catálogo público de programas de formación agrupados por área."""
    areas = Area.objects.filter(
        activo=True,
        programas__activo=True,
    ).prefetch_related(
        Prefetch(
            'programas',
            queryset=Programa.objects.filter(activo=True).order_by('nombre'),
            to_attr='programas_activos',
        )
    ).distinct().order_by('nombre')

    context = {
        'areas':            areas,
        'total_programas':  Programa.objects.filter(activo=True).count(),
        'total_areas':      areas.count(),
    }
    return render(request, 'solicitudes/catalogo_programas.html', context)