from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect
from functools import wraps


#=================================
# FUNCIONES DE VERIFICACION DE ROL
#=================================

def es_administrador(user):
    """Admin = superusuario O grupo Administrador"""
    return user.is_superuser or user.groups.filter(name='Administrador').exists()

def es_asistente(user):
    """Verifica si  el  usuario es Asistente"""
    return user.groups.filter(name='Asistente').exists()

def es_coordinador(user):
    """Verifica si  el usuario es Coordinador"""
    return user.groups.filter(name='Coordinador').exists()

def puede_editar(user):
    """Admin y Asistente pueden crear/editar/eliminar"""
    return es_administrador(user) or es_asistente(user)

def puede_ver(user):
    """Todos los roles pueden ver"""
    return es_administrador(user) or es_asistente(user) or es_coordinador(user)or es_coordinador(user)

#=======================================
# DECORADORES LISTOS PARA USAR EN VISTAS
#=======================================

#Solo Administrador
admin_requerido = user_passes_test(
    es_administrador,
    login_url='/login/'
)

# Admin y Asistente (crear/editar/eliminar)
puede_editar_requerido = user_passes_test(
    puede_editar,
    login_url='/login/'
)
#Todos los roles (solo ver)
puede_ver_requerido = user_passes_test(
    puede_ver,
    login_url='/login/'
)