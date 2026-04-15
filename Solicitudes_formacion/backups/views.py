import os
import subprocess
import zipfile
from datetime import datetime, timedelta

from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import FileResponse, Http404
from django.conf import settings
from django.db import connection
from django.utils import timezone


# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────

BACKUP_DIR         = os.path.join(settings.BASE_DIR, 'db_backups')
EXTENSIONES_VALIDAS = ('.zip', '.sql')


# ─────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────

def _get_backup_dir():
    """Retorna la ruta del directorio de backups y lo crea si no existe."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return BACKUP_DIR


def _validar_archivo(filename, backup_dir, solo_zip=False):
    """
    Valida que el filename sea seguro y tenga extensión permitida.
    Retorna (filepath, error_message). Si es válido, error_message es None.
    """
    filepath = os.path.join(backup_dir, filename)

    if not os.path.exists(filepath):
        return filepath, '❌ Archivo no encontrado'

    if not os.path.abspath(filepath).startswith(os.path.abspath(backup_dir)):
        return filepath, '❌ Ruta no válida'

    if solo_zip:
        valido = filename.startswith('backup_') and filename.endswith('.zip')
    else:
        valido = filename.startswith('backup_') and any(filename.endswith(e) for e in EXTENSIONES_VALIDAS)

    if not valido:
        return filepath, '❌ Archivo no válido'

    return filepath, None


def _get_db_credentials():
    """Retorna las credenciales de la BD como diccionario."""
    db_config = settings.DATABASES['default']
    return {
        'name':     db_config['NAME'],
        'user':     db_config['USER'],
        'password': db_config['PASSWORD'],
        'host':     db_config.get('HOST', 'localhost'),
        'port':     db_config.get('PORT', '3306'),
    }


def _es_backup_valido(filename):
    """Verifica si el nombre del archivo corresponde a un backup válido."""
    return filename.startswith('backup_') and any(filename.endswith(e) for e in EXTENSIONES_VALIDAS)


def _listar_backups_del_disco(backup_dir):
    """Lee todos los archivos de backup del disco y retorna lista de dicts."""
    backups = []
    for filename in os.listdir(backup_dir):
        if not _es_backup_valido(filename):
            continue

        filepath = os.path.join(backup_dir, filename)
        if not os.path.exists(filepath):
            continue

        file_stats = os.stat(filepath)
        try:
            date_str = filename.replace('backup_', '').replace('.zip', '').replace('.sql', '')
            fecha = datetime.strptime(date_str, '%Y%m%d_%H%M%S')
        except ValueError:
            fecha = datetime.fromtimestamp(file_stats.st_mtime)

        tamaño_mb = file_stats.st_size / (1024 * 1024)
        backups.append({
            'nombre':         filename,
            'ruta':           filepath,
            'fecha':          fecha,
            'tamaño':         tamaño_mb,
            'tamaño_legible': f"{tamaño_mb:.2f} MB",
        })
    return backups


# ─────────────────────────────────────────────
# Funciones de dominio (rangos de fecha y BD)
# ─────────────────────────────────────────────

def calcular_rango_fechas(rango_fecha):
    """
    Calcula las fechas de inicio y fin según el rango seleccionado.
    Retorna (fecha_inicio, fecha_fin) o (None, None) si no hay rango.
    """
    if not rango_fecha:
        return None, None

    hoy = timezone.now().date()

    if rango_fecha == 'mes_pasado':
        ultimo = hoy.replace(day=1) - timedelta(days=1)
        return ultimo.replace(day=1), ultimo

    rangos = {
        'hoy':             (hoy, hoy),
        'ayer':            (hoy - timedelta(days=1), hoy - timedelta(days=1)),
        'esta_semana':     (hoy - timedelta(days=hoy.weekday()), hoy),
        'semana_pasada':   (
            hoy - timedelta(days=hoy.weekday() + 7),
            hoy - timedelta(days=hoy.weekday() + 1),
        ),
        'este_mes':        (hoy.replace(day=1), hoy),
        'ultimos_7_dias':  (hoy - timedelta(days=7),  hoy),
        'ultimos_30_dias': (hoy - timedelta(days=30), hoy),
        'este_año':        (hoy.replace(month=1, day=1), hoy),
    }
    return rangos.get(rango_fecha, (None, None))


def obtener_fechas_exactas(request):
    """
    Lee fecha_inicio y fecha_fin del request GET.
    Retorna (fecha_inicio: date | None, fecha_fin: date | None, errores: list).
    Las fechas exactas tienen PRIORIDAD sobre rango_fecha.
    """
    errores      = []
    fecha_inicio = None
    fecha_fin    = None

    raw_inicio = request.GET.get('fecha_inicio', '').strip()
    raw_fin    = request.GET.get('fecha_fin',    '').strip()

    # Validaciones en lista: (valor_raw, nombre, destino)
    parseos = [
        (raw_inicio, 'inicio'),
        (raw_fin,    'fin'),
    ]
    resultados = {}
    for raw, nombre in parseos:
        if raw:
            try:
                resultados[nombre] = datetime.strptime(raw, '%Y-%m-%d').date()
            except ValueError:
                errores.append(f"Formato de fecha {nombre} inválido: '{raw}'.")
                resultados[nombre] = None
        else:
            resultados[nombre] = None

    fecha_inicio = resultados['inicio']
    fecha_fin    = resultados['fin']

    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        errores.append("La fecha fin no puede ser anterior a la fecha inicio.")
        fecha_fin = None

    return fecha_inicio, fecha_fin, errores


def get_database_type():
    """Detecta si se está usando MySQL o SQLite."""
    try:
        if not hasattr(settings, 'DATABASES'):
            return None
        db_engine = settings.DATABASES.get('default', {}).get('ENGINE', '')
        if 'mysql'  in db_engine:
            return 'mysql'
        if 'sqlite' in db_engine:
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

        db_type   = get_database_type()
        db_config = settings.DATABASES.get('default', {})

        if db_type == 'mysql':
            db_name = db_config.get('NAME', '')
            if not db_name:
                return 0
            try:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2)
                        FROM information_schema.TABLES
                        WHERE table_schema = %s
                    """, [db_name])
                    result = cursor.fetchone()
                    return float(result[0]) if result and result[0] else 0
            except Exception as e:
                print(f"Error al obtener tamaño de MySQL: {e}")
                return 0

        if db_type == 'sqlite':
            db_path = db_config.get('NAME', '')
            try:
                return round(os.path.getsize(db_path) / (1024 * 1024), 2) if db_path and os.path.exists(db_path) else 0
            except Exception as e:
                print(f"Error al obtener tamaño de SQLite: {e}")
                return 0

        return 0

    except Exception as e:
        print(f"Error general al obtener tamaño de BD: {e}")
        return 0


# ─────────────────────────────────────────────
# Vistas
# ─────────────────────────────────────────────

@staff_member_required
def panel_backups(request):
    """
    Panel de gestión de backups con filtros de nombre, período predefinido
    y rango de fechas exacto.
    Prioridad: fechas exactas > período predefinido.
    """
    backup_dir = _get_backup_dir()
    backups    = _listar_backups_del_disco(backup_dir)

    # Filtros
    nombre_filtro = request.GET.get('nombre',     '').strip()
    rango_fecha   = request.GET.get('rango_fecha','').strip()
    fecha_inicio_exacta, fecha_fin_exacta, _ = obtener_fechas_exactas(request)
    usar_fechas_exactas = bool(fecha_inicio_exacta or fecha_fin_exacta)

    if nombre_filtro:
        backups = [b for b in backups if nombre_filtro.lower() in b['nombre'].lower()]

    if usar_fechas_exactas:
        fi = fecha_inicio_exacta
        ff = fecha_fin_exacta
        backups = [
            b for b in backups
            if (fi is None or b['fecha'].date() >= fi)
            and (ff is None or b['fecha'].date() <= ff)
        ]
    elif rango_fecha:
        fi, ff = calcular_rango_fechas(rango_fecha)
        if fi and ff:
            backups = [b for b in backups if fi <= b['fecha'].date() <= ff]

    backups.sort(key=lambda x: x['fecha'], reverse=True)

    # Info de la base de datos
    db_type = get_database_type()
    db_size = 0
    db_path = "No configurado"

    try:
        if hasattr(settings, 'DATABASES'):
            db_config = settings.DATABASES.get('default', {})
            db_size   = get_database_size()

            rutas_db = {
                'mysql':  lambda: f"MySQL: {db_config.get('NAME', 'unknown')} @ {db_config.get('HOST', 'localhost')}",
                'sqlite': lambda: db_config.get('NAME', 'No configurado'),
            }
            db_path = rutas_db.get(db_type, lambda: "Tipo de BD no soportado")()
    except Exception as e:
        print(f"Error al obtener info de BD: {e}")
        db_path = "Error al obtener información"

    espacio = sum(b['tamaño'] for b in backups)
    context = {
        'backups':               backups,
        'total_backups':         len(backups),
        'espacio_usado':         espacio,
        'espacio_usado_legible': f"{espacio:.2f} MB",
        'db_size':               db_size,
        'db_size_legible':       f"{db_size:.2f} MB" if db_size > 0 else "N/A",
        'db_path':               db_path,
        'db_type':               db_type,
        'nombre_filtro':         nombre_filtro,
        'rango_fecha':           rango_fecha,
        'fecha_inicio_filter':   str(fecha_inicio_exacta) if fecha_inicio_exacta else '',
        'fecha_fin_filter':      str(fecha_fin_exacta)    if fecha_fin_exacta    else '',
    }
    return render(request, 'backups/panel_backups.html', context)


@staff_member_required
def crear_backup(request):
    """Crear un nuevo backup según el tipo de BD configurado."""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para crear backups.')
        return redirect('backups:panel_backups')

    db_type = get_database_type()

    manejadores = {
        'mysql':  lambda: crear_backup_mysql(request),
        'sqlite': lambda: (
            messages.error(request, '❌ El sistema está configurado para SQLite. Actualice el código.'),
            redirect('backups:panel_backups')
        )[-1],
    }

    handler = manejadores.get(db_type)
    if handler:
        return handler()

    messages.error(request, '❌ Tipo de base de datos no soportado.')
    return redirect('backups:panel_backups')


def crear_backup_mysql(request):
    """Crear backup de MySQL usando mysqldump."""
    try:
        creds      = _get_db_credentials()
        backup_dir = _get_backup_dir()
        timestamp  = datetime.now().strftime('%Y%m%d_%H%M%S')

        sql_filename = f"backup_{timestamp}.sql"
        sql_path     = os.path.join(backup_dir, sql_filename)
        zip_filename = f"backup_{timestamp}.zip"
        zip_path     = os.path.join(backup_dir, zip_filename)

        command = [
            'mysqldump',
            f'--host={creds["host"]}',
            f'--port={creds["port"]}',
            f'--user={creds["user"]}',
            f'--password={creds["password"]}',
            '--single-transaction', '--routines', '--triggers', '--events',
            creds['name'],
        ]

        with open(sql_path, 'w', encoding='utf8') as f:
            result = subprocess.run(command, stdout=f, stderr=subprocess.PIPE, text=True)

        if result.returncode != 0:
            if os.path.exists(sql_path):
                os.remove(sql_path)
            messages.error(request, f'❌ Error al crear backup: {result.stderr}')
            return redirect('backups:panel_backups')

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(sql_path, sql_filename)
        os.remove(sql_path)

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


@staff_member_required
def descargar_backup(request, filename):
    """Descargar un archivo de backup."""
    backup_dir = _get_backup_dir()
    filepath, error = _validar_archivo(filename, backup_dir)

    if error:
        raise Http404(error)

    try:
        content_type = 'application/zip' if filename.endswith('.zip') else 'application/sql'
        return FileResponse(open(filepath, 'rb'), as_attachment=True, filename=filename, content_type=content_type)
    except Exception as e:
        messages.error(request, f'❌ Error al descargar: {str(e)}')
        return redirect('backups:panel_backups')


@staff_member_required
def eliminar_backup(request, filename):
    """Eliminar un archivo de backup."""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para eliminar.')
        return redirect('backups:panel_backups')

    backup_dir = _get_backup_dir()
    filepath, error = _validar_archivo(filename, backup_dir)

    if error:
        messages.error(request, error)
        return redirect('backups:panel_backups')

    try:
        os.remove(filepath)
        messages.success(request, f'✅ Backup "{filename}" eliminado correctamente')
    except Exception as e:
        messages.error(request, f'❌ Error al eliminar: {str(e)}')

    return redirect('backups:panel_backups')


@staff_member_required
def limpiar_backups_antiguos(request):
    """Limpiar backups antiguos manteniendo solo los últimos 10."""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para limpiar.')
        return redirect('backups:panel_backups')

    backup_dir = _get_backup_dir()
    backups    = [
        (os.path.join(backup_dir, f), os.path.getmtime(os.path.join(backup_dir, f)))
        for f in os.listdir(backup_dir)
        if _es_backup_valido(f) and os.path.exists(os.path.join(backup_dir, f))
    ]
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


@staff_member_required
def restaurar_backup(request, filename):
    """Restaurar un backup de MySQL."""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para restaurar.')
        return redirect('backups:panel_backups')

    if get_database_type() != 'mysql':
        messages.error(request, '❌ La restauración solo está disponible para MySQL.')
        return redirect('backups:panel_backups')

    backup_dir = _get_backup_dir()
    backup_path, error = _validar_archivo(filename, backup_dir, solo_zip=True)

    if error:
        messages.error(request, error)
        return redirect('backups:panel_backups')

    temp_sql = os.path.join(backup_dir, 'temp_restore.sql')

    try:
        messages.info(request, '🔄 Creando backup de seguridad antes de restaurar...')
        crear_backup_mysql(request)

        creds = _get_db_credentials()

        with zipfile.ZipFile(backup_path, 'r') as zip_ref:
            sql_files = [f for f in zip_ref.namelist() if f.endswith('.sql')]
            if not sql_files:
                messages.error(request, '❌ No se encontró archivo .sql en el backup')
                return redirect('backups:panel_backups')
            with zip_ref.open(sql_files[0]) as source, open(temp_sql, 'wb') as target:
                target.write(source.read())

        command = [
            'mysql',
            f'--host={creds["host"]}',
            f'--port={creds["port"]}',
            f'--user={creds["user"]}',
            f'--password={creds["password"]}',
            creds['name'],
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
        if os.path.exists(temp_sql):
            try:
                os.remove(temp_sql)
            except Exception:
                pass

    return redirect('backups:panel_backups')