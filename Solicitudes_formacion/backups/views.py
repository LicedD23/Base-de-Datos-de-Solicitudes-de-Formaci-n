import os
import subprocess
from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import FileResponse, Http404
from django.conf import settings
from django.db import connection
from django.utils import timezone
from datetime import datetime, timedelta
import zipfile


# ============================================================================
# FUNCIÓN AUXILIAR PARA RANGOS DE FECHA PREDEFINIDOS
# ============================================================================

def calcular_rango_fechas(rango_fecha):
    """
    Calcula las fechas de inicio y fin según el rango seleccionado.
    Retorna (fecha_inicio, fecha_fin) o (None, None) si no hay rango.
    """
    if not rango_fecha:
        return None, None

    hoy = timezone.now().date()

    rangos = {
        'hoy':             (hoy, hoy),
        'ayer':            (hoy - timedelta(days=1), hoy - timedelta(days=1)),
        'esta_semana':     (hoy - timedelta(days=hoy.weekday()), hoy),
        'semana_pasada':   (
            hoy - timedelta(days=hoy.weekday() + 7),
            hoy - timedelta(days=hoy.weekday() + 1),
        ),
        'este_mes':        (hoy.replace(day=1), hoy),
        'ultimos_7_dias':  (hoy - timedelta(days=7), hoy),
        'ultimos_30_dias': (hoy - timedelta(days=30), hoy),
        'este_año':        (hoy.replace(month=1, day=1), hoy),
    }

    if rango_fecha == 'mes_pasado':
        primer_dia_mes = hoy.replace(day=1)
        ultimo_dia_mes_pasado = primer_dia_mes - timedelta(days=1)
        return ultimo_dia_mes_pasado.replace(day=1), ultimo_dia_mes_pasado

    return rangos.get(rango_fecha, (None, None))


# ============================================================================
# ⭐ NUEVA — OBTENER Y VALIDAR FECHAS EXACTAS DEL REQUEST
#
# Lógica idéntica a la de reportes/views.py:
#   - Lee fecha_inicio y fecha_fin del GET
#   - Valida formato YYYY-MM-DD
#   - Valida que fecha_fin no sea anterior a fecha_inicio
#   - Las fechas exactas tienen PRIORIDAD sobre rango_fecha
# ============================================================================

def obtener_fechas_exactas(request):
    """
    Lee fecha_inicio y fecha_fin del request GET.
    Retorna (fecha_inicio: date | None, fecha_fin: date | None, errores: list).
    """
    errores = []
    fecha_inicio = None
    fecha_fin = None

    raw_inicio = request.GET.get('fecha_inicio', '').strip()
    raw_fin    = request.GET.get('fecha_fin', '').strip()

    if raw_inicio:
        try:
            fecha_inicio = datetime.strptime(raw_inicio, '%Y-%m-%d').date()
        except ValueError:
            errores.append(f"Formato de fecha inicio inválido: '{raw_inicio}'.")

    if raw_fin:
        try:
            fecha_fin = datetime.strptime(raw_fin, '%Y-%m-%d').date()
        except ValueError:
            errores.append(f"Formato de fecha fin inválido: '{raw_fin}'.")

    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        errores.append("La fecha fin no puede ser anterior a la fecha inicio.")
        fecha_fin = None

    return fecha_inicio, fecha_fin, errores


# ============================================================================
# FUNCIÓN AUXILIAR: DETECTAR TIPO DE BASE DE DATOS
# ============================================================================

def get_database_type():
    """Detecta si se está usando MySQL o SQLite"""
    try:
        if not hasattr(settings, 'DATABASES'):
            return None

        db_config = settings.DATABASES.get('default', {})
        db_engine = db_config.get('ENGINE', '')

        if 'mysql' in db_engine:
            return 'mysql'
        elif 'sqlite' in db_engine:
            return 'sqlite'

        return None
    except Exception as e:
        print(f"Error al detectar tipo de BD: {e}")
        return None


def get_database_size():
    """
    Obtiene el tamaño de la base de datos en MB.
    Retorna el tamaño en MB o 0 si no se puede obtener.
    """
    try:
        if not hasattr(settings, 'DATABASES'):
            return 0

        db_type = get_database_type()
        if not db_type:
            return 0

        db_config = settings.DATABASES.get('default', {})

        if db_type == 'mysql':
            try:
                db_name = db_config.get('NAME', '')
                if not db_name:
                    return 0
                with connection.cursor() as cursor:
                    query = """
                        SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS size_mb
                        FROM information_schema.TABLES
                        WHERE table_schema = %s
                    """
                    cursor.execute(query, [db_name])
                    result = cursor.fetchone()
                    if result and result[0]:
                        return float(result[0])
                return 0
            except Exception as e:
                print(f"Error al obtener tamaño de MySQL: {e}")
                return 0

        elif db_type == 'sqlite':
            try:
                db_path = db_config.get('NAME', '')
                if db_path and os.path.exists(db_path):
                    size_bytes = os.path.getsize(db_path)
                    return round(size_bytes / (1024 * 1024), 2)
                return 0
            except Exception as e:
                print(f"Error al obtener tamaño de SQLite: {e}")
                return 0

        return 0

    except Exception as e:
        print(f"Error general al obtener tamaño de BD: {e}")
        return 0


# ============================================================================
# PANEL DE BACKUPS CON FILTROS
# ============================================================================

@staff_member_required
def panel_backups(request):
    """
    Panel de gestión de backups con filtros de nombre, período predefinido
    y rango de fechas exacto.

    Lógica de prioridad de fechas (idéntica al JS del template):
      1. Si hay fecha_inicio o fecha_fin  → se usan esas fechas exactas.
      2. Si no hay fechas exactas y hay rango_fecha → período predefinido.
    """
    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
    os.makedirs(backup_dir, exist_ok=True)

    # ── Leer todos los backups del disco ─────────────────────────────────────
    backups = []

    for filename in os.listdir(backup_dir):
        if filename.startswith("backup_") and (filename.endswith(".zip") or filename.endswith(".sql")):
            filepath = os.path.join(backup_dir, filename)

            if not os.path.exists(filepath):
                continue

            file_stats = os.stat(filepath)

            try:
                if filename.endswith('.zip'):
                    date_str = filename.replace('backup_', '').replace('.zip', '')
                else:
                    date_str = filename.replace('backup_', '').replace('.sql', '')
                fecha = datetime.strptime(date_str, '%Y%m%d_%H%M%S')
            except ValueError:
                fecha = datetime.fromtimestamp(file_stats.st_mtime)

            backups.append({
                'nombre':         filename,
                'ruta':           filepath,
                'fecha':          fecha,
                'tamaño':         file_stats.st_size / (1024 * 1024),
                'tamaño_legible': f"{file_stats.st_size / (1024 * 1024):.2f} MB",
            })

    # ── Leer parámetros de filtro ─────────────────────────────────────────────
    nombre_filtro = request.GET.get('nombre', '').strip()
    rango_fecha   = request.GET.get('rango_fecha', '').strip()

    # ⭐ Leer fechas exactas
    fecha_inicio_exacta, fecha_fin_exacta, _ = obtener_fechas_exactas(request)
    usar_fechas_exactas = bool(fecha_inicio_exacta or fecha_fin_exacta)

    # ── Filtrar por nombre ────────────────────────────────────────────────────
    if nombre_filtro:
        backups = [b for b in backups if nombre_filtro.lower() in b['nombre'].lower()]

    # ── Filtrar por fecha ─────────────────────────────────────────────────────
    if usar_fechas_exactas:
        # PRIORIDAD: rango exacto definido por el usuario (igual que en reportes)
        fi = fecha_inicio_exacta
        ff = fecha_fin_exacta
        backups = [
            b for b in backups
            if (fi is None or b['fecha'].date() >= fi)
            and (ff is None or b['fecha'].date() <= ff)
        ]
    elif rango_fecha:
        # Período predefinido solo si NO hay fechas exactas
        fecha_inicio_pred, fecha_fin_pred = calcular_rango_fechas(rango_fecha)
        if fecha_inicio_pred and fecha_fin_pred:
            backups = [
                b for b in backups
                if fecha_inicio_pred <= b['fecha'].date() <= fecha_fin_pred
            ]

    # Ordenar por fecha más reciente
    backups.sort(key=lambda x: x['fecha'], reverse=True)

    # ── Información de la base de datos ──────────────────────────────────────
    db_type = get_database_type()
    db_path = "No configurado"
    db_size = 0

    try:
        if hasattr(settings, 'DATABASES'):
            db_config = settings.DATABASES.get('default', {})
            db_size   = get_database_size()

            if db_type == 'mysql':
                db_name = db_config.get('NAME', 'unknown')
                db_host = db_config.get('HOST', 'localhost')
                db_path = f"MySQL: {db_name} @ {db_host}"
            elif db_type == 'sqlite':
                db_path = db_config.get('NAME', 'No configurado')
            else:
                db_path = "Tipo de BD no soportado"
    except Exception as e:
        print(f"Error al obtener info de BD: {e}")
        db_path = "Error al obtener información"

    context = {
        'backups':             backups,
        'total_backups':       len(backups),
        'espacio_usado':       sum(b['tamaño'] for b in backups),
        'espacio_usado_legible': f"{sum(b['tamaño'] for b in backups):.2f} MB",
        'db_size':             db_size,
        'db_size_legible':     f"{db_size:.2f} MB" if db_size > 0 else "N/A",
        'db_path':             db_path,
        'db_type':             db_type,
        # Filtros aplicados (para repintar el formulario)
        'nombre_filtro':        nombre_filtro,
        'rango_fecha':          rango_fecha,
        # ⭐ Fechas exactas (para repintar los inputs date)
        'fecha_inicio_filter':  str(fecha_inicio_exacta) if fecha_inicio_exacta else '',
        'fecha_fin_filter':     str(fecha_fin_exacta)    if fecha_fin_exacta    else '',
    }

    return render(request, 'backups/panel_backups.html', context)


# ============================================================================
# CREAR NUEVO BACKUP - MYSQL
# ============================================================================

@staff_member_required
def crear_backup(request):
    """Crear un nuevo backup de MySQL"""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para crear backups.')
        return redirect('backups:panel_backups')

    db_type = get_database_type()

    if db_type == 'mysql':
        return crear_backup_mysql(request)
    elif db_type == 'sqlite':
        messages.error(request, '❌ El sistema está configurado para SQLite. Actualice el código.')
        return redirect('backups:panel_backups')
    else:
        messages.error(request, '❌ Tipo de base de datos no soportado.')
        return redirect('backups:panel_backups')


def crear_backup_mysql(request):
    """Crear backup de MySQL usando mysqldump"""
    try:
        db_config   = settings.DATABASES['default']
        db_name     = db_config['NAME']
        db_user     = db_config['USER']
        db_password = db_config['PASSWORD']
        db_host     = db_config.get('HOST', 'localhost')
        db_port     = db_config.get('PORT', '3306')

        backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
        os.makedirs(backup_dir, exist_ok=True)

        timestamp       = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"backup_{timestamp}.sql"
        backup_path     = os.path.join(backup_dir, backup_filename)

        command = [
            'mysqldump',
            f'--host={db_host}',
            f'--port={db_port}',
            f'--user={db_user}',
            f'--password={db_password}',
            '--single-transaction',
            '--routines',
            '--triggers',
            '--events',
            db_name,
        ]

        with open(backup_path, 'w', encoding='utf8') as f:
            result = subprocess.run(command, stdout=f, stderr=subprocess.PIPE, text=True)

        if result.returncode != 0:
            if os.path.exists(backup_path):
                os.remove(backup_path)
            messages.error(request, f'❌ Error al crear backup: {result.stderr}')
            return redirect('backups:panel_backups')

        zip_filename = f"backup_{timestamp}.zip"
        zip_path     = os.path.join(backup_dir, zip_filename)

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(backup_path, backup_filename)

        os.remove(backup_path)

        file_size = os.path.getsize(zip_path) / (1024 * 1024)
        messages.success(request, f'✅ Backup creado exitosamente: {zip_filename} ({file_size:.2f} MB)')

    except FileNotFoundError:
        messages.error(
            request,
            '❌ mysqldump no encontrado. Asegúrate de que MySQL esté instalado '
            'y que mysqldump esté en el PATH del sistema.'
        )
    except Exception as e:
        messages.error(request, f'❌ Error al crear backup: {str(e)}')

    return redirect('backups:panel_backups')


# ============================================================================
# DESCARGAR BACKUP
# ============================================================================

@staff_member_required
def descargar_backup(request, filename):
    """Descargar un archivo de backup"""
    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
    filepath   = os.path.join(backup_dir, filename)

    if not os.path.exists(filepath):
        raise Http404("Archivo no encontrado")

    if not os.path.abspath(filepath).startswith(os.path.abspath(backup_dir)):
        raise Http404("Ruta no válida")

    if not (filename.startswith('backup_') and (filename.endswith('.zip') or filename.endswith('.sql'))):
        raise Http404("Archivo no válido")

    try:
        content_type = 'application/zip' if filename.endswith('.zip') else 'application/sql'
        return FileResponse(open(filepath, 'rb'), as_attachment=True, filename=filename, content_type=content_type)
    except Exception as e:
        messages.error(request, f'❌ Error al descargar: {str(e)}')
        return redirect('backups:panel_backups')


# ============================================================================
# ELIMINAR BACKUP
# ============================================================================

@staff_member_required
def eliminar_backup(request, filename):
    """Eliminar un archivo de backup"""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para eliminar.')
        return redirect('backups:panel_backups')

    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
    filepath   = os.path.join(backup_dir, filename)

    if not os.path.exists(filepath):
        messages.error(request, '❌ Archivo no encontrado')
        return redirect('backups:panel_backups')

    if not os.path.abspath(filepath).startswith(os.path.abspath(backup_dir)):
        messages.error(request, '❌ Ruta no válida')
        return redirect('backups:panel_backups')

    if not (filename.startswith('backup_') and (filename.endswith('.zip') or filename.endswith('.sql'))):
        messages.error(request, '❌ Archivo no válido')
        return redirect('backups:panel_backups')

    try:
        os.remove(filepath)
        messages.success(request, f'✅ Backup "{filename}" eliminado correctamente')
    except Exception as e:
        messages.error(request, f'❌ Error al eliminar: {str(e)}')

    return redirect('backups:panel_backups')


# ============================================================================
# LIMPIAR BACKUPS ANTIGUOS
# ============================================================================

@staff_member_required
def limpiar_backups_antiguos(request):
    """Limpiar backups antiguos manteniendo solo los últimos 10"""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para limpiar.')
        return redirect('backups:panel_backups')

    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
    backups    = []

    for filename in os.listdir(backup_dir):
        if filename.startswith("backup_") and (filename.endswith(".zip") or filename.endswith(".sql")):
            filepath = os.path.join(backup_dir, filename)
            if os.path.exists(filepath):
                backups.append((filepath, os.path.getmtime(filepath)))

    backups.sort(key=lambda x: x[1], reverse=True)

    eliminados = 0
    for filepath, _ in backups[10:]:
        try:
            os.remove(filepath)
            eliminados += 1
        except Exception as e:
            messages.error(request, f'Error al eliminar {os.path.basename(filepath)}: {e}')

    if eliminados > 0:
        messages.success(request, f'✅ Se eliminaron {eliminados} backup(s) antiguo(s)')
    else:
        messages.info(request, 'ℹ️ No hay backups antiguos para eliminar')

    return redirect('backups:panel_backups')


# ============================================================================
# RESTAURAR BACKUP - MYSQL
# ============================================================================

@staff_member_required
def restaurar_backup(request, filename):
    """Restaurar un backup de MySQL"""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para restaurar.')
        return redirect('backups:panel_backups')

    db_type = get_database_type()

    if db_type != 'mysql':
        messages.error(request, '❌ La restauración solo está disponible para MySQL.')
        return redirect('backups:panel_backups')

    backup_dir  = os.path.join(settings.BASE_DIR, 'db_backups')
    backup_path = os.path.join(backup_dir, filename)

    if not os.path.exists(backup_path):
        messages.error(request, '❌ Archivo no encontrado')
        return redirect('backups:panel_backups')

    if not os.path.abspath(backup_path).startswith(os.path.abspath(backup_dir)):
        messages.error(request, '❌ Ruta no válida')
        return redirect('backups:panel_backups')

    if not (filename.startswith('backup_') and filename.endswith('.zip')):
        messages.error(request, '❌ Archivo no válido')
        return redirect('backups:panel_backups')

    try:
        messages.info(request, '🔄 Creando backup de seguridad antes de restaurar...')
        crear_backup_mysql(request)

        db_config   = settings.DATABASES['default']
        db_name     = db_config['NAME']
        db_user     = db_config['USER']
        db_password = db_config['PASSWORD']
        db_host     = db_config.get('HOST', 'localhost')
        db_port     = db_config.get('PORT', '3306')

        temp_sql = os.path.join(backup_dir, 'temp_restore.sql')

        with zipfile.ZipFile(backup_path, 'r') as zip_ref:
            sql_files = [f for f in zip_ref.namelist() if f.endswith('.sql')]
            if not sql_files:
                messages.error(request, '❌ No se encontró archivo .sql en el backup')
                return redirect('backups:panel_backups')
            sql_file = sql_files[0]
            with zip_ref.open(sql_file) as source, open(temp_sql, 'wb') as target:
                target.write(source.read())

        command = [
            'mysql',
            f'--host={db_host}',
            f'--port={db_port}',
            f'--user={db_user}',
            f'--password={db_password}',
            db_name,
        ]

        with open(temp_sql, 'r', encoding='utf8') as f:
            result = subprocess.run(command, stdin=f, stderr=subprocess.PIPE, text=True)

        if os.path.exists(temp_sql):
            os.remove(temp_sql)

        if result.returncode != 0:
            messages.error(request, f'❌ Error al restaurar: {result.stderr}')
            return redirect('backups:panel_backups')

        messages.success(
            request,
            f'✅ Backup "{filename}" restaurado exitosamente. '
            'Recarga la página para ver los cambios.'
        )

    except FileNotFoundError:
        messages.error(
            request,
            '❌ mysql no encontrado. Asegúrate de que MySQL esté instalado '
            'y que mysql esté en el PATH del sistema.'
        )
    except Exception as e:
        messages.error(request, f'❌ Error al restaurar backup: {str(e)}')
        temp_sql = os.path.join(backup_dir, 'temp_restore.sql')
        if os.path.exists(temp_sql):
            try:
                os.remove(temp_sql)
            except Exception:
                pass

    return redirect('backups:panel_backups')