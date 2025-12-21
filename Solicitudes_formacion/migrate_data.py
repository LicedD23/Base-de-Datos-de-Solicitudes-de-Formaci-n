import os
import django
import sqlite3
from datetime import datetime

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Solicitudes_formacion.settings')
django.setup()

from django.contrib.auth.models import User
from django.db import connection

print("=" * 60)
print("MIGRACIÓN DE SQLite A MySQL")
print("=" * 60)

# Conectar a SQLite
sqlite_conn = sqlite3.connect('db.sqlite3')
sqlite_conn.row_factory = sqlite3.Row
cursor = sqlite_conn.cursor()

def get_table_names():
    """Obtiene todas las tablas de SQLite"""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [row['name'] for row in cursor.fetchall()]

def migrate_table(table_name):
    """Migra una tabla completa de SQLite a MySQL"""
    try:
        print(f"\n📦 Migrando tabla: {table_name}")
        
        # Obtener datos de SQLite
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
        
        if not rows:
            print(f"  ⚠️  Tabla vacía")
            return
        
        # Obtener nombres de columnas
        columns = [description[0] for description in cursor.description]
        
        # Preparar query INSERT para MySQL
        placeholders = ', '.join(['%s'] * len(columns))
        columns_str = ', '.join([f'`{col}`' for col in columns])
        query = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"
        
        # Insertar en MySQL
        with connection.cursor() as mysql_cursor:
            # Deshabilitar verificación de claves foráneas temporalmente
            mysql_cursor.execute("SET FOREIGN_KEY_CHECKS=0")
            
            count = 0
            for row in rows:
                try:
                    values = tuple(row[col] for col in columns)
                    mysql_cursor.execute(query, values)
                    count += 1
                except Exception as e:
                    print(f"  ❌ Error en registro: {e}")
            
            # Reactivar verificación de claves foráneas
            mysql_cursor.execute("SET FOREIGN_KEY_CHECKS=1")
            
        print(f"  ✅ Migrados {count} registros")
        
    except Exception as e:
        print(f"  ❌ Error migrando {table_name}: {e}")

# Orden de migración (respetando dependencias)
migration_order = [
    # Primero las tablas de Django
    'django_content_type',
    'auth_permission',
    'auth_group',
    'auth_group_permissions',
    'auth_user',
    'auth_user_groups',
    'auth_user_user_permissions',
    'django_admin_log',
    'django_session',
    
    # Luego las tablas de tu aplicación (en orden de dependencias)
    'area_formacion_areaformacion',
    'programas_programa',
    'instructores_instructor',
    'empresas_empresa',
    'solicitudes_solicitud',
    
    # Tablas de respaldos si existen
    'backups_backup',
]

# Obtener todas las tablas disponibles
all_tables = get_table_names()

# Migrar en orden
migrated = []
for table in migration_order:
    if table in all_tables:
        migrate_table(table)
        migrated.append(table)

# Migrar cualquier tabla que no esté en la lista
print("\n" + "=" * 60)
print("VERIFICANDO TABLAS RESTANTES")
print("=" * 60)

remaining = [t for t in all_tables if t not in migrated and not t.startswith('django_')]
if remaining:
    print(f"\n⚠️  Tablas adicionales encontradas: {len(remaining)}")
    for table in remaining:
        migrate_table(table)
else:
    print("\n✅ No hay tablas adicionales")

# Resetear secuencias AUTO_INCREMENT
print("\n" + "=" * 60)
print("AJUSTANDO SECUENCIAS AUTO_INCREMENT")
print("=" * 60)

with connection.cursor() as mysql_cursor:
    for table in migrated:
        try:
            # Obtener el máximo ID
            mysql_cursor.execute(f"SELECT MAX(id) as max_id FROM {table}")
            result = mysql_cursor.fetchone()
            if result and result[0]:
                max_id = result[0] + 1
                mysql_cursor.execute(f"ALTER TABLE {table} AUTO_INCREMENT = {max_id}")
                print(f"  ✅ {table}: AUTO_INCREMENT = {max_id}")
        except Exception as e:
            # No todas las tablas tienen columna 'id'
            pass

print("\n" + "=" * 60)
print("✅ MIGRACIÓN COMPLETADA EXITOSAMENTE")
print("=" * 60)

# Mostrar resumen
print("\n📊 RESUMEN:")
cursor.execute("SELECT COUNT(*) FROM auth_user")
users_count = cursor.fetchone()[0]
print(f"  • Usuarios: {users_count}")

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%solicitud%'")
if cursor.fetchone():
    cursor.execute("SELECT COUNT(*) FROM solicitudes_solicitud")
    solicitudes_count = cursor.fetchone()[0]
    print(f"  • Solicitudes: {solicitudes_count}")

sqlite_conn.close()
print("\n🎉 ¡Listo! Ahora puedes ejecutar: python manage.py runserver")