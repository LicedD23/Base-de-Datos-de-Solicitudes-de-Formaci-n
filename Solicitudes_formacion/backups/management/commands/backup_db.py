import os
import zipfile
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection


# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────

BACKUP_DIR_NAME  = 'db_backups'
BACKUP_KEEP      = 50
BACKUP_PREFIX    = 'backup_'
BACKUP_EXTENSION = '.zip'


# ─────────────────────────────────────────────
# Command
# ─────────────────────────────────────────────

class Command(BaseCommand):
    help = 'Crea una copia de seguridad de la base de datos de SQLite'

    # ── Validaciones ──────────────────────────

    def _validar_engine(self, db_config):
        """Verifica que el motor sea SQLite. Retorna True si es válido."""
        if 'sqlite' not in db_config.get('ENGINE', '').lower():
            self.stdout.write(self.style.ERROR('✗ Este comando solo funciona con SQLite'))
            return False
        return True

    def _validar_db_path(self, db_path):
        """Verifica que el archivo de BD exista. Retorna True si es válido."""
        if not os.path.exists(db_path):
            self.stdout.write(self.style.ERROR(f'✗ No se encontró la base de datos en: {db_path}'))
            return False
        return True

    # ── Helpers de paths ──────────────────────

    def _get_backup_dir(self):
        """Retorna el directorio de backups y lo crea si no existe."""
        backup_dir = os.path.join(settings.BASE_DIR, BACKUP_DIR_NAME)
        os.makedirs(backup_dir, exist_ok=True)
        return backup_dir

    def _build_backup_paths(self, backup_dir):
        """Construye y retorna los paths del .sqlite3 y .zip con timestamp."""
        timestamp       = datetime.now().strftime('%Y%m%d_%H%M%S')
        sqlite_filename = f'{BACKUP_PREFIX}{timestamp}.sqlite3'
        zip_filename    = f'{BACKUP_PREFIX}{timestamp}{BACKUP_EXTENSION}'
        return (
            os.path.join(backup_dir, sqlite_filename), sqlite_filename,
            os.path.join(backup_dir, zip_filename),    zip_filename,
        )

    # ── Pasos del backup ──────────────────────

    def _ejecutar_vacuum(self, sqlite_path):
        """Ejecuta VACUUM INTO para generar copia segura de la BD."""
        self.stdout.write('→ Iniciando backup usando VACUUM INTO...')
        with connection.cursor() as cursor:
            cursor.execute(f"VACUUM INTO '{sqlite_path}';")

    def _comprimir_backup(self, sqlite_path, sqlite_filename, zip_path):
        """Comprime el .sqlite3 en un .zip y elimina el archivo sin comprimir."""
        self.stdout.write('→ Creando archivo ZIP...')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
            zipf.write(sqlite_path, sqlite_filename)
        os.remove(sqlite_path)

    def _reportar_exito(self, zip_path, zip_filename, backup_dir):
        """Imprime los mensajes de éxito con tamaño y ubicación."""
        size = os.path.getsize(zip_path) / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(f'✓ Backup SQLite generado: {zip_filename} ({size:.2f} MB)'))
        self.stdout.write(self.style.SUCCESS(f'✓ Ubicación: {backup_dir}'))

    # ── Limpieza ──────────────────────────────

    def cleanup_old_backups(self, backup_dir, keep=BACKUP_KEEP):
        """Mantiene los últimos N backups eliminando los más antiguos."""
        backups = sorted(
            [
                (os.path.join(backup_dir, f), os.path.getmtime(os.path.join(backup_dir, f)))
                for f in os.listdir(backup_dir)
                if f.startswith(BACKUP_PREFIX) and f.endswith(BACKUP_EXTENSION)
            ],
            key=lambda x: x[1],
            reverse=True,
        )

        for filepath, _ in backups[keep:]:
            try:
                os.remove(filepath)
                self.stdout.write(self.style.WARNING(f'🗑 Backup eliminado: {os.path.basename(filepath)}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'No se pudo eliminar {filepath}: {e}'))

    # ── Entrypoint ────────────────────────────

    def handle(self, *args, **options):
        """Orquesta la creación del backup: valida, genera, comprime y limpia."""
        db_config = settings.DATABASES['default']

        if not self._validar_engine(db_config):
            return

        db_path = db_config['NAME']

        if not self._validar_db_path(db_path):
            return

        backup_dir                                          = self._get_backup_dir()
        sqlite_path, sqlite_filename, zip_path, zip_filename = self._build_backup_paths(backup_dir)

        try:
            self._ejecutar_vacuum(sqlite_path)
            self._comprimir_backup(sqlite_path, sqlite_filename, zip_path)
            self._reportar_exito(zip_path, zip_filename, backup_dir)
            self.cleanup_old_backups(backup_dir)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Error creando backup: {e}'))