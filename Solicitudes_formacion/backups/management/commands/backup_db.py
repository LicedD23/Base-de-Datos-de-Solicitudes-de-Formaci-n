import os
import zipfile
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection

class Command(BaseCommand):
    help = 'Crea una copia de seguridad de la base de datos de SQLite'
    
    def handle(self, *args, **options):
        db_config = settings.DATABASES['default']
        db_engine = db_config['ENGINE']
        
        # Validar que la base sea SQLite
        if 'sqlite' not in db_engine.lower():
            self.stdout.write(self.style.ERROR('✗ Este comando solo funciona con SQLite'))
            return
        
        db_path = db_config['NAME']
        
        if not os.path.exists(db_path):
            self.stdout.write(self.style.ERROR(f'✗ No se encontró la base de datos en: {db_path}'))
            return
        
        # ✅ CAMBIO: Usar nombre diferente 'db_backups' en lugar de 'backups'
        backup_dir = os.path.join(settings.BASE_DIR, 'db_backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # Nombre de archivo
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        sqlite_filename = f'backup_{timestamp}.sqlite3'
        zip_filename = f'backup_{timestamp}.zip'
        
        sqlite_path = os.path.join(backup_dir, sqlite_filename)
        zip_path = os.path.join(backup_dir, zip_filename)
        
        try:
            # 1. Hacer copia segura usando VACUUM INTO (SQLite 3.27+)
            self.stdout.write("→ Iniciando backup usando VACUUM INTO...")
            with connection.cursor() as cursor:
                cursor.execute(f"VACUUM INTO '{sqlite_path}';")
            
            # 2. Crear archivo ZIP
            self.stdout.write("→ Creando archivo ZIP...")
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
                zipf.write(sqlite_path, sqlite_filename)
            
            # 3. Eliminar archivo sin comprimir
            os.remove(sqlite_path)
            
            size = os.path.getsize(zip_path) / (1024 * 1024)
            self.stdout.write(
                self.style.SUCCESS(f'✓ Backup SQLite generado: {zip_filename} ({size:.2f} MB)')
            )
            self.stdout.write(
                self.style.SUCCESS(f'✓ Ubicación: {backup_dir}')
            )
            
            # 4. Limpiar backups antiguos
            self.cleanup_old_backups(backup_dir)
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Error creando backup: {e}'))
    
    def cleanup_old_backups(self, backup_dir, keep=50):
        """Mantiene los últimos N backups"""
        backups = []
        
        for filename in os.listdir(backup_dir):
            if filename.startswith("backup_") and filename.endswith(".zip"):
                filepath = os.path.join(backup_dir, filename)
                backups.append((filepath, os.path.getmtime(filepath)))
        
        # Ordenar por fecha (más nuevos primero)
        backups.sort(key=lambda x: x[1], reverse=True)
        
        # Eliminar los antiguos
        for filepath, _ in backups[keep:]:
            try:
                os.remove(filepath)
                self.stdout.write(self.style.WARNING(f'🗑 Backup eliminado: {os.path.basename(filepath)}'))
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'No se pudo eliminar {filepath}: {e}')
                )