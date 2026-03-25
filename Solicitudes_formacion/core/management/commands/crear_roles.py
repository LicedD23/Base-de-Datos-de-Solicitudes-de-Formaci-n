from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission

class Command(BaseCommand):
    help = 'Crear los 3 roles del sistema: Administrador, Asistente, Coordinador'
    
    def handle(self, *args, **kwargs):
        
        print("\n" + "="*60)
        print("🚀 CREANDO ROLES DEL  SISTEMA SENA")
        print("="*60 + "\n")
        
        #===== ADMINISTRADOR =====
        admin_group, created = Group.objects.get_or_create(name='Administrador')
        admin_group.permissions.set(Permission.objects.all())
        status = "✅ Creado" if created else "✅ Actualizado"
        print(f'{status} ADMINISTRADOR: Todos los permisos ({Permission.objects.count()})')
        
        #===== ASISTENTE (Opera el  sistema - CRUD completo ) =====
        asist_group, created = Group.objects.get_or_create(name='Asistente')
        permisos_asist= [
            #SOLICITUDES -CRUD completo
            'view_solicitud', 'add_solicitud', 'change_solicitud', 'delete_solicitud',
            
            #INSTRUCTORES -CRUD completo
            'view_instructor', 'add_instructor', 'change_instructor', 'delete_instructor',
            
            #EMPRESAS -CRUD completo
            'view_empresa', 'add_empresa', 'change_empresa', 'delete_empresa',
            
            #PROGRAMAD -CRUD completo
            'view_programa', 'add_programa', 'change_programa', 'delete_programa',
            
            #AREA -CRUD completo
            'view_area', 'add_area', 'change_area', 'delete_area',
            
            #REPORTES -Ver y Generar
            'view_reporte', 'add_reporte',
        ]
        asist_perms = Permission.objects.filter(codename__in=permisos_asist)
        asist_group.permissions.set(asist_perms)
        status = "✅Creado " if created else "✅Actualizado"
        print(f'{status} ASISTENTE: {asist_perms.count()} permisos (CRUD + Reportes)')
        
        #===== COORDINADOR (Solo consulta + Reportes)=====
        coord_group, created = Group.objects.get_or_create(name='Coordinador')
        permisos_coord = [
            #Solo puede VER
            'view_solicitud',
            'view_instructor',
            'view_empresa',
            'view_programa',
            'view_area',
            
            #REPORTES -VER Y Generar 
            'view_reporte', 'add_reporte',
        ]
        coord_perms = Permission.objects.filter(codename__in=permisos_coord)
        coord_group.permissions.set(coord_perms)
        status = "✅ Creado" if created else "✅ Actualizado"
        print(f'{status} COORDINADOR: {coord_perms.count()} permisos (consulta+ Reportes)')
        
        print("\n" + "="*60)  
        print("📊 RESUMEN:")
        print("="*60) 
        print("1. administrador → Gestion total + Backups")
        print("2. Asistente     → CRUD completo + Generar Reportes")
        print("3. Coordinador   → Solo consulta + Generar reportes")
        print("="*60)
        print("\n🎉 Roles creados exitosamente!\n")