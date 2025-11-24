from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.utils import timezone
from django.contrib.auth import authenticate,login
from django.contrib.auth import logout
# imports directos de modelos (están en apps separadas)
from area_formacion.models import Area
from programas.models import Programa
from empresas.models import Empresa
from instructores.models import Instructor
from solicitudes.models import Solicitud

# Intentamos importar EstadoSolicitud si existe (TextChoices). Si no, lo manejamos abajo.
try:
    from solicitudes.models import EstadoSolicitud
except Exception:
    EstadoSolicitud = None


@staff_member_required
def dashboard(request):
    """Dashboard principal con métricas generales (optimizado)."""
    cache_key = 'core_dashboard_metrics'
    context = cache.get(cache_key)
    if context is None:
        # métricas agregadas
        total_areas = Area.objects.count()
        total_programas = Programa.objects.count()
        total_empresas = Empresa.objects.count()
        total_instructores = Instructor.objects.filter(activo=True).count()
        total_solicitudes = Solicitud.objects.count()

        # usar la constante EstadoSolicitud si está definida, si no usar la cadena
        if EstadoSolicitud is not None:
            solicitudes_pendientes = Solicitud.objects.filter(estado=EstadoSolicitud.RECIBIDA).count()
        else:
            solicitudes_pendientes = Solicitud.objects.filter(estado='RECIBIDA').count()

        ultimas = list(
            Solicitud.objects
                .select_related('empresa', 'programa', 'instructor_asignado')
                .order_by('-fecha_recepcion')[:5]
        )

        # preparar lista de métricas para render en plantilla (incluye iconos y color)
        metrics = [
            (total_areas, "Áreas", "bi-diagram-3", "primary"),
            (total_programas, "Programas", "bi-book", "success"),
            (total_empresas, "Empresas", "bi-building", "warning"),
            (total_instructores, "Instructores Activos", "bi-person-badge", "info"),
            (total_solicitudes, "Solicitudes", "bi-envelope", "danger"),
            (solicitudes_pendientes, "Pendientes", "bi-hourglass-split", "secondary"),
        ]

        context = {
            'total_areas': total_areas,
            'total_programas': total_programas,
            'total_empresas': total_empresas,
            'total_instructores': total_instructores,
            'total_solicitudes': total_solicitudes,
            'solicitudes_pendientes': solicitudes_pendientes,
            'ultimas_solicitudes': ultimas,
            'metrics': metrics,
            'now': timezone.now(),
        }
        cache.set(cache_key, context, 60)

    return render(request, 'core/dashboard.html', context)


def home(request):
    """Página de inicio pública."""
    return render(request, 'core/home.html')

def login_view(request):
    """Vista para iniciar sesion"""
    if request.method == 'POST':
        user = authenticate(
            request,
            username= request.POST["username"],
            password= request.POST["password"]
        )
        if user:
            login(request, user)
            return redirect('core:dashboard')
        
    return render(request, 'core/login.html')

def logout_view(request):
    """vista para cerrar sesion"""
    logout(request)
    return redirect('core:home')


