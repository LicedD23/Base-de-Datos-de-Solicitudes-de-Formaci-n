import os
from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import FileResponse, Http404
from django.conf import settings
from django.core.management import call_command
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
# PANEL DE BACKUPS CON FILTROS
# ============================================================================

@staff_member_required
def panel_backups(request):
    """Panel de gestión de backups con filtros de nombre y período"""
    # Directorio de backups
    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
    
    # Crear directorio si no existe
    os.makedirs(backup_dir, exist_ok=True)
    
    # Listar backups existentes
    backups = []
    
    for filename in os.listdir(backup_dir):
        if filename.startswith("backup_") and filename.endswith(".zip"):
            filepath = os.path.join(backup_dir, filename)
            
            if not os.path.exists(filepath):
                continue
                
            file_stats = os.stat(filepath)
            
            try:
                date_str = filename.replace('backup_', '').replace('.zip', '')
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
    
    # Información de la base de datos
    db_path = settings.DATABASES['default']['NAME']
    db_size = 0
    if os.path.exists(db_path):
        db_size = os.path.getsize(db_path) / (1024 * 1024)
    
    # Contexto para el template
    context = {
        'backups': backups,
        'total_backups': len(backups),
        'espacio_usado': sum(b['tamaño'] for b in backups),
        'espacio_usado_legible': f"{sum(b['tamaño'] for b in backups):.2f} MB",
        'db_size': db_size,
        'db_size_legible': f"{db_size:.2f} MB",
        'db_path': db_path,
        # Filtros aplicados
        'nombre_filtro': nombre_filtro,
        'rango_fecha': rango_fecha,
    }
    
    return render(request, 'backups/panel_backups.html', context)


# ============================================================================
# CREAR NUEVO BACKUP
# ============================================================================

@staff_member_required
def crear_backup(request):
    """Crear un nuevo backup"""
    if request.method == 'POST':
        try:
            call_command('backup_db')
            messages.success(
                request,
                '✅ Backup creado exitosamente. El archivo se guardó en la carpeta "db_backups".'
            )
        except Exception as e:
            messages.error(request, f'❌ Error al crear backup: {str(e)}')
    else:
        messages.warning(request, '⚠️ Método no permitido. Use POST para crear backups.')
    
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
    
    if not (filename.startswith('backup_') and filename.endswith('.zip')):
        raise Http404("Archivo no válido")
    
    try:
        response = FileResponse(
            open(filepath, 'rb'),
            as_attachment=True,
            filename=filename,
            content_type='application/zip'
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
    
    if not (filename.startswith('backup_') and filename.endswith('.zip')):
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
        if filename.startswith("backup_") and filename.endswith(".zip"):
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
# RESTAURAR BACKUP
# ============================================================================

@staff_member_required
def restaurar_backup(request, filename):
    """Restaurar un backup"""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para restaurar.')
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
        call_command('backup_db')
        
        # Obtener ruta de la base de datos
        db_config = settings.DATABASES['default']
        db_path = db_config['NAME']
        
        # Extraer el archivo .sqlite3 del ZIP
        with zipfile.ZipFile(backup_path, 'r') as zip_ref:
            sqlite_files = [f for f in zip_ref.namelist() if f.endswith('.sqlite3')]
            
            if not sqlite_files:
                messages.error(request, '❌ No se encontró archivo .sqlite3 en el backup')
                return redirect('backups:panel_backups')
            
            sqlite_file = sqlite_files[0]
            
            # Extraer a archivo temporal
            temp_db = os.path.join(backup_dir, 'temp_restore.sqlite3')
            with zip_ref.open(sqlite_file) as source, open(temp_db, 'wb') as target:
                target.write(source.read())
            
            # Cerrar todas las conexiones a la base de datos
            from django.db import connections
            connections.close_all()
            
            # Reemplazar la base de datos actual
            import shutil
            shutil.move(temp_db, db_path)
        
        messages.success(
            request, 
            f'✅ Backup "{filename}" restaurado exitosamente. '
            'Por favor, reinicie el servidor para aplicar los cambios.'
        )
        
    except Exception as e:
        messages.error(request, f'❌ Error al restaurar backup: {str(e)}')
        
        # Limpiar archivo temporal si existe
        temp_db = os.path.join(backup_dir, 'temp_restore.sqlite3')
        if os.path.exists(temp_db):
            try:
                os.remove(temp_db)
            except:
                pass
    
    return redirect('backups:panel_backups')