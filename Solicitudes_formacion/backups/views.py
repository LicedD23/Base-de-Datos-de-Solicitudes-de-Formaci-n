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
# FUNCIÓN AUXILIAR PARA RANGOS DE FECHA
# ============================================================================

def calcular_rango_fechas(rango_fecha):
    """
    Calcula las fechas de inicio y fin según el rango seleccionado
    Retorna (fecha_inicio, fecha_fin) o (None, None) si no hay rango
    """
    if not rango_fecha:
        return None, None
    
    hoy = timezone.now().date()
    fecha_inicio = None
    fecha_fin = None
    
    if rango_fecha == 'hoy':
        fecha_inicio = hoy
        fecha_fin = hoy
    
    elif rango_fecha == 'ayer':
        ayer = hoy - timedelta(days=1)
        fecha_inicio = ayer
        fecha_fin = ayer
    
    elif rango_fecha == 'esta_semana':
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        fecha_inicio = inicio_semana
        fecha_fin = hoy
    
    elif rango_fecha == 'semana_pasada':
        inicio_semana_pasada = hoy - timedelta(days=hoy.weekday() + 7)
        fin_semana_pasada = inicio_semana_pasada + timedelta(days=6)
        fecha_inicio = inicio_semana_pasada
        fecha_fin = fin_semana_pasada
    
    elif rango_fecha == 'este_mes':
        inicio_mes = hoy.replace(day=1)
        fecha_inicio = inicio_mes
        fecha_fin = hoy
    
    elif rango_fecha == 'mes_pasado':
        primer_dia_mes_actual = hoy.replace(day=1)
        ultimo_dia_mes_pasado = primer_dia_mes_actual - timedelta(days=1)
        primer_dia_mes_pasado = ultimo_dia_mes_pasado.replace(day=1)
        fecha_inicio = primer_dia_mes_pasado
        fecha_fin = ultimo_dia_mes_pasado
    
    elif rango_fecha == 'ultimos_7_dias':
        fecha_inicio = hoy - timedelta(days=7)
        fecha_fin = hoy
    
    elif rango_fecha == 'ultimos_30_dias':
        fecha_inicio = hoy - timedelta(days=30)
        fecha_fin = hoy
    
    elif rango_fecha == 'este_año':
        fecha_inicio = hoy.replace(month=1, day=1)
        fecha_fin = hoy
    
    return fecha_inicio, fecha_fin


# ============================================================================
# FUNCIÓN AUXILIAR: DETECTAR TIPO DE BASE DE DATOS
# ============================================================================

def get_database_type():
    """Detecta si se está usando MySQL o SQLite"""
    try:
        from django.conf import settings
        
        #Verificar que settings este configurado
        if not hasattr(settings, 'DATABASES'):
            return None
        
        db_config = settings.DATABASES.get('default', {})
        db_engine = db_config.get('ENGINE', '')
        
        if 'mysql' in db_engine:
            return 'mysql'
        elif 'sqlite' in db_engine:
            return 'sqlite'
        
        return None
    except Exception  as e:
        print(f"Error al  detectar tipo  de BD:{e}")
        return None

def get_database_size():
    """
    Otiene el  tamaño  de la base de datos en  MB
    Retorna el  tamaño  en  MB o 0 si  no  se puede obtener
    """
    try: 
        from django.conf import settings
        from django.db import connection
        
        #Verificar que settings este configurado
        if not hasattr(settings, 'DATABASES'):
            return 0
        db_type = get_database_type()
        if not db_type:
            return 0
        
        db_config = settings.DATABASES.get ('default', {})
        
        if db_type == 'mysql':
            try:
                db_name = db_config.get('NAME', '')
                if not db_name:
                    return 0
                #Consulta para obtener el tamaño  de la base de datos MySQL
                with connection.cursor() as cursor:
                    query = """
                        SELECT
                        ROUND(SUM(data_length + index_length) / 1024 / 1024, 2)as size_mb
                    FROM information_schema.TABLES
                    WHERE  table_schema = %s
                    """
                    cursor.execute(query, [db_name])
                    result = cursor.fetchone()
                    
                    if result and result[0]:
                        return float(result[0])
                    return 0
                
            except Exception as e:
                print(f"Error al obtener tamaño  sde MySQL:{e}")
                return 0
            
        elif db_type == 'sqlite':
            try:
                db_path = db_config.get('NAME', '')
                if db_path and os.path.exists(db_path):
                    size_bytes=os.path.getsize(db_path)
                    return round(size_bytes / (1024 * 1024), 2)
                return 0
            except Exception as e:
                print(f"Error al obtener tamaño  de SQLite:{e}")
                return 0
            
        return 0
    
    except Exception as e:
        print(f"error general  al obtener tamaño de BD:{e}")
        return 0
    
# ============================================================================
# PANEL DE BACKUPS CON FILTROS
# ============================================================================

@staff_member_required
def panel_backups(request):
    """Panel de gestión de backups con filtros de nombre y período"""
    from django.conf import settings
    
    # Directorio de backups
    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
    
    # Crear directorio si no existe
    os.makedirs(backup_dir, exist_ok=True)
    
    # Listar backups existentes
    backups = []
    
    for filename in os.listdir(backup_dir):
        if filename.startswith("backup_") and (filename.endswith(".zip") or filename.endswith(".sql")):
            filepath = os.path.join(backup_dir, filename)
            
            if not os.path.exists(filepath):
                continue
                
            file_stats = os.stat(filepath)
            
            try:
                # Extraer fecha del nombre del archivo
                if filename.endswith('.zip'):
                    date_str = filename.replace('backup_', '').replace('.zip', '')
                else:
                    date_str = filename.replace('backup_', '').replace('.sql', '')
                fecha = datetime.strptime(date_str, '%Y%m%d_%H%M%S')
            except ValueError:
                fecha = datetime.fromtimestamp(file_stats.st_mtime)
            
            backups.append({
                'nombre': filename,
                'ruta': filepath,
                'fecha': fecha,
                'tamaño': file_stats.st_size / (1024 * 1024),
                'tamaño_legible': f"{file_stats.st_size / (1024 * 1024):.2f} MB"
            })
    
    # ============================================================================
    # APLICAR FILTROS
    # ============================================================================
    
    # Obtener filtros del request
    nombre_filtro = request.GET.get('nombre', '').strip()
    rango_fecha = request.GET.get('rango_fecha', '').strip()
    
    # Filtrar por nombre
    if nombre_filtro:
        backups = [b for b in backups if nombre_filtro.lower() in b['nombre'].lower()]
    
    # Filtrar por período
    if rango_fecha:
        fecha_inicio, fecha_fin = calcular_rango_fechas(rango_fecha)
        
        if fecha_inicio and fecha_fin:
            backups = [
                b for b in backups 
                if fecha_inicio <= b['fecha'].date() <= fecha_fin
            ]
    
    # Ordenar por fecha más reciente
    backups.sort(key=lambda x: x['fecha'], reverse=True)
    
    # ============================================================================
    # INFORMACIÓN DE LA BASE DE DATOS (CON MANEJO DE ERRORES)
    # ============================================================================
    
    db_type = get_database_type()
    db_path = "No configurado"
    db_info = "No disponible"
    db_size = 0
    
    try:
        if hasattr(settings, 'DATABASES'):
            db_config = settings.DATABASES.get('default', {})
            
            # Obtener el tamaño de la base de datos
            db_size = get_database_size()
            
            # Construir la información de la ruta/conexión
            if db_type == 'mysql':
                db_name = db_config.get('NAME', 'unknown')
                db_host = db_config.get('HOST', 'localhost')
                db_path = f"MySQL: {db_name} @ {db_host}"
                db_info = db_path
            elif db_type == 'sqlite':
                db_path = db_config.get('NAME', 'No configurado')
                db_info = str(db_path)
            else:
                db_path = "Tipo de BD no soportado"
                db_info = db_path
    except Exception as e:
        print(f"Error al obtener info de BD: {e}")
        db_path = "Error al obtener información"
        db_info = str(e)
    
    # Contexto para el template
    context = {
        'backups': backups,
        'total_backups': len(backups),
        'espacio_usado': sum(b['tamaño'] for b in backups),
        'espacio_usado_legible': f"{sum(b['tamaño'] for b in backups):.2f} MB",
        'db_size': db_size,
        'db_size_legible': f"{db_size:.2f} MB" if db_size > 0 else "N/A",
        'db_info': db_info,
        'db_path': db_path,
        'db_type': db_type,
        # Filtros aplicados
        'nombre_filtro': nombre_filtro,
        'rango_fecha': rango_fecha,
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
        # Configuración de la base de datos
        db_config = settings.DATABASES['default']
        db_name = db_config['NAME']
        db_user = db_config['USER']
        db_password = db_config['PASSWORD']
        db_host = db_config.get('HOST', 'localhost')
        db_port = db_config.get('PORT', '3306')
        
        # Crear directorio de backups
        backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # Nombre del archivo
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"backup_{timestamp}.sql"
        backup_path = os.path.join(backup_dir, backup_filename)
        
        # Comando mysqldump
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
            db_name
        ]
        
        # Ejecutar mysqldump
        with open(backup_path, 'w', encoding='utf8') as f:
            result = subprocess.run(
                command,
                stdout=f,
                stderr=subprocess.PIPE,
                text=True
            )
        
        if result.returncode != 0:
            error_msg = result.stderr
            os.remove(backup_path) if os.path.exists(backup_path) else None
            messages.error(request, f'❌ Error al crear backup: {error_msg}')
            return redirect('backups:panel_backups')
        
        # Comprimir el archivo SQL
        zip_filename = f"backup_{timestamp}.zip"
        zip_path = os.path.join(backup_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(backup_path, backup_filename)
        
        # Eliminar el archivo SQL sin comprimir
        os.remove(backup_path)
        
        file_size = os.path.getsize(zip_path) / (1024 * 1024)
        messages.success(
            request,
            f'✅ Backup creado exitosamente: {zip_filename} ({file_size:.2f} MB)'
        )
        
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
    filepath = os.path.join(backup_dir, filename)
    
    # Validaciones de seguridad
    if not os.path.exists(filepath):
        raise Http404("Archivo no encontrado")
    
    if not os.path.abspath(filepath).startswith(os.path.abspath(backup_dir)):
        raise Http404("Ruta no válida")
    
    if not (filename.startswith('backup_') and (filename.endswith('.zip') or filename.endswith('.sql'))):
        raise Http404("Archivo no válido")
    
    try:
        content_type = 'application/zip' if filename.endswith('.zip') else 'application/sql'
        response = FileResponse(
            open(filepath, 'rb'),
            as_attachment=True,
            filename=filename,
            content_type=content_type
        )
        return response
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
    filepath = os.path.join(backup_dir, filename)
    
    # Validaciones de seguridad
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
    backups = []
    
    # Listar todos los backups con su fecha de modificación
    for filename in os.listdir(backup_dir):
        if filename.startswith("backup_") and (filename.endswith(".zip") or filename.endswith(".sql")):
            filepath = os.path.join(backup_dir, filename)
            if os.path.exists(filepath):
                backups.append((filepath, os.path.getmtime(filepath)))
    
    # Ordenar por fecha (más recientes primero)
    backups.sort(key=lambda x: x[1], reverse=True)
    
    # Eliminar todos excepto los últimos 10
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
    
    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
    backup_path = os.path.join(backup_dir, filename)
    
    # Validaciones de seguridad
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
        # Crear backup de seguridad antes de restaurar
        messages.info(request, '🔄 Creando backup de seguridad antes de restaurar...')
        crear_backup_mysql(request)
        
        # Configuración de la base de datos
        db_config = settings.DATABASES['default']
        db_name = db_config['NAME']
        db_user = db_config['USER']
        db_password = db_config['PASSWORD']
        db_host = db_config.get('HOST', 'localhost')
        db_port = db_config.get('PORT', '3306')
        
        # Extraer el archivo SQL del ZIP
        temp_sql = os.path.join(backup_dir, 'temp_restore.sql')
        
        with zipfile.ZipFile(backup_path, 'r') as zip_ref:
            sql_files = [f for f in zip_ref.namelist() if f.endswith('.sql')]
            
            if not sql_files:
                messages.error(request, '❌ No se encontró archivo .sql en el backup')
                return redirect('backups:panel_backups')
            
            sql_file = sql_files[0]
            with zip_ref.open(sql_file) as source, open(temp_sql, 'wb') as target:
                target.write(source.read())
        
        # Restaurar usando mysql command
        command = [
            'mysql',
            f'--host={db_host}',
            f'--port={db_port}',
            f'--user={db_user}',
            f'--password={db_password}',
            db_name
        ]
        
        with open(temp_sql, 'r', encoding='utf8') as f:
            result = subprocess.run(
                command,
                stdin=f,
                stderr=subprocess.PIPE,
                text=True
            )
        
        # Limpiar archivo temporal
        if os.path.exists(temp_sql):
            os.remove(temp_sql)
        
        if result.returncode != 0:
            error_msg = result.stderr
            messages.error(request, f'❌ Error al restaurar: {error_msg}')
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
        
        # Limpiar archivo temporal si existe
        temp_sql = os.path.join(backup_dir, 'temp_restore.sql')
        if os.path.exists(temp_sql):
            try:
                os.remove(temp_sql)
            except:
                pass
    
    return redirect('backups:panel_backups')