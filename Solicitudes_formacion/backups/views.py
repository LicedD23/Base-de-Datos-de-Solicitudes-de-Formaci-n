import os
from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import FileResponse, Http404
from django.conf import settings
from django.core.management import call_command
from datetime import datetime
import zipfile


@staff_member_required
def panel_backups(request):
    """Panel de gestión de backups con filtros"""
    # ✅ CAMBIO: usar 'db_backups' en lugar de 'backups'
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
    # Aplicar filtros
    nombre_filtro = request.GET.get('nombre','').strip()
    fecha_desde = request.GET.get('fecha_desde','').strip()
    fecha_hasta = request.GET.get('fecha_hasta','').strip()
    
    # Filtrar por nombre
    if nombre_filtro:
        backups=[b for b in backups if nombre_filtro.lower() in b['nombre'].lower()]
    
    #Filtrar por fecha desde
    if fecha_desde:
        try:
            fecha_desde_dt = datetime.striptime(fecha_desde ,'%Y-%m-%d')
            backups = [b for b in backups if b['fecha'].date() >= fecha_desde_dt.date()]
        except ValueError:
            pass
    #Filtrar por fecha hasta
    if fecha_hasta:
        try:
            fecha_hasta_dt = datetime.strptime(fecha_hasta, '%Y-%m-%d')
            backups = [b for b in backups if b['fecha'].date() <= fecha_hasta_dt.date()]
        except ValueError:
            pass
        
    backups.sort(key=lambda x: x['fecha'], reverse=True)
    
    db_path = settings.DATABASES['default']['NAME']
    db_size = 0
    if os.path.exists(db_path):
        db_size = os.path.getsize(db_path) / (1024 * 1024)
    
    context = {
        'backups': backups,
        'total_backups': len(backups),
        'espacio_usado': sum(b['tamaño'] for b in backups),
        'espacio_usado_legible': f"{sum(b['tamaño'] for b in backups):.2f} MB",
        'db_size': db_size,
        'db_size_legible': f"{db_size:.2f} MB",
        'db_path': db_path,
        #Filtros aplicados
        'nombre_filtro': nombre_filtro,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }
    
    return render(request, 'backups/panel_backups.html', context)


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


@staff_member_required
def descargar_backup(request, filename):
    """Descargar un archivo de backup"""
    # ✅ CAMBIO
    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
    filepath = os.path.join(backup_dir, filename)
    
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


@staff_member_required
def eliminar_backup(request, filename):
    """Eliminar un archivo de backup"""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para eliminar.')
        return redirect('backups:panel_backups')
    
    # ✅ CAMBIO
    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
    filepath = os.path.join(backup_dir, filename)
    
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


@staff_member_required
def limpiar_backups_antiguos(request):
    """Limpiar backups antiguos manteniendo solo los últimos 10"""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para limpiar.')
        return redirect('backups:panel_backups')
    
    # ✅ CAMBIO
    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
    backups = []
    
    for filename in os.listdir(backup_dir):
        if filename.startswith("backup_") and filename.endswith(".zip"):
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


@staff_member_required
def restaurar_backup(request, filename):
    """Restaurar un backup"""
    if request.method != 'POST':
        messages.warning(request, '⚠️ Método no permitido. Use POST para restaurar.')
        return redirect('backups:panel_backups')
    
    # ✅ CAMBIO
    backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
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
        call_command('backup_db')
        
        db_config = settings.DATABASES['default']
        db_path = db_config['NAME']
        
        with zipfile.ZipFile(backup_path, 'r') as zip_ref:
            sqlite_files = [f for f in zip_ref.namelist() if f.endswith('.sqlite3')]
            
            if not sqlite_files:
                messages.error(request, '❌ No se encontró archivo .sqlite3 en el backup')
                return redirect('backups:panel_backups')
            
            sqlite_file = sqlite_files[0]
            
            temp_db = os.path.join(backup_dir, 'temp_restore.sqlite3')
            with zip_ref.open(sqlite_file) as source, open(temp_db, 'wb') as target:
                target.write(source.read())
            
            from django.db import connections
            connections.close_all()
            
            import shutil
            shutil.move(temp_db, db_path)
        
        messages.success(
            request, 
            f'✅ Backup "{filename}" restaurado exitosamente. '
            'Por favor, reinicie el servidor para aplicar los cambios.'
        )
        
    except Exception as e:
        messages.error(request, f'❌ Error al restaurar backup: {str(e)}')
        
        temp_db = os.path.join(backup_dir, 'temp_restore.sqlite3')
        if os.path.exists(temp_db):
            try:
                os.remove(temp_db)
            except:
                pass
    
    return redirect('backups:panel_backups')