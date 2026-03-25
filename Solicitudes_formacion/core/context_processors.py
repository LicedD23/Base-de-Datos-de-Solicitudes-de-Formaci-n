# core/context_processors.py

def user_roles(request):
    """
    Context processor para hacer disponible el rol del usuario en todos los templates
    """
    if request.user.is_authenticated:
        return {
            'es_administrador': request.user.is_superuser or request.user.groups.filter(name='Administrador').exists(),
            'es_asistente': request.user.groups.filter(name='Asistente').exists(),
            'es_coordinador': request.user.groups.filter(name='Coordinador').exists(),
        }
    return {
        'es_administrador': False,
        'es_asistente': False,
        'es_coordinador': False,
    }