from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.core.cache import cache
from django.utils import timezone
from django.contrib.auth import authenticate, login, update_session_auth_hash
from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import IntegrityError
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect

# ✅ AGREGAR ESTAS IMPORTACIONES PARA EL EMAIL
from django.contrib.auth.views import PasswordResetView
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

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
    #Si el usuario ya esta auntenticado, redirigir al  dashboard
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    
    if request.method=='POST':
        username= request.POST.get('username','').strip()
        password = request.POST.get('password','')
        
        user= authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            nombre = user.get_full_name() or user.username
            messages.success(request, f'¡Bienvenido {nombre}!')
            
            #Redirigir a la pagina solicitada o  al  dashboard
            next_url = request.GET.get('next','core:dashboard')
            return redirect(next_url)
        else:
            messages.error(request, 'Usuario o  contraseña incorrectos')
    
    return render(request, 'core/login.html')

#REGISTRO DE ADMINISTRADORES
@user_passes_test(lambda u: u.is_superuser)
def register_admin_view(request):
    """Vista para crear usuarios administradores o superusuarios"""
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password2 = request.POST.get('password2', '')
        is_superuser = request.POST.get('is_superuser') == 'on'
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        
        # Validaciones
        if not all([username, email, password, password2]):
            messages.error(request, 'Usuario, correo y contraseñas son obligatorios')
            return render(request, 'core/register_admin.html')
        
        if password != password2:
            messages.error(request, 'Las contraseñas no coinciden')
            return render(request, 'core/register_admin.html')
        
        if len(password) < 8:
            messages.error(request, 'La contraseña debe tener al menos 8 caracteres')
            return render(request, 'core/register_admin.html')
        
        # Validar que el username no exista
        if User.objects.filter(username=username).exists():
            messages.error(request, 'El nombre de usuario ya existe')
            return render(request, 'core/register_admin.html')
        
        # Validar email duplicado
        if User.objects.filter(email=email).exists():
            messages.error(request, 'El correo electrónico ya está registrado')
            return render(request, 'core/register_admin.html')
        
        try:
            # Crear el usuario
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name
            )
            user.is_staff = True
            user.is_superuser = is_superuser
            user.save()
            
            tipo = "superusuario" if is_superuser else "administrador"
            messages.success(request, f'✅ {tipo.capitalize()} "{username}" creado exitosamente.')
            return redirect('core:dashboard')
        
        except Exception as e:
            messages.error(request, f'Error inesperado: {str(e)}')
            return render(request, 'core/register_admin.html')
    
    # Contexto para el template
    context = {
        'current_user': request.user,
    }
    return render(request, 'core/register_admin.html', context)
        
def logout_view(request):
    """vista para cerrar sesion"""
    nombre = request.user.get_full_name() or request.user.username
    logout(request)
    messages.success(request,f'Hasta pronto {nombre}! Has cerrado sesion exitosamente')
    return redirect('core:home')

@login_required
def profile_view(request):
    """Vista para ver el perfil del usuario"""
    #Estadisticas del  usuario si es staff
    context = {
        'user':request.user
    }
    if request.user.is_staff:
        #Metricas del  sistema para el  administrador
        context['total_solicitudes'] = Solicitud.objects.count()
        context['total_empresas'] = Empresa.objects.count()
        context['total_programas'] = Programa.objects.count()
        context['total_instructores'] = Instructor.objects.filter(activo=True).count()
    
    return render(request, 'core/profile.html', context)

@login_required
def profile_edit(request):
    """Vista para editar el perfil del usuario"""
    
    if request.method == 'POST':
        user = request.user
        
        #Obtener datos del formulario
        first_name = request.POST.get('first_name','').strip()
        last_name = request.POST.get('last_name','').strip()
        email = request.POST.get('email','').strip()
        
        #Validaciones
        if not email:
            messages.error(request,'El correo electronico es obligatorio')
            return render(request, 'core/profile_edit.html')
    
        # ✅ CORRECCIÓN 1: User con mayúscula
        if User.objects.filter(email=email).exclude(id=user.id).exists():
            messages.error(request, 'Este correo electronico ya esta en uso')
            return render(request, 'core/profile_edit.html')
        
        try:
            #Actualizar datos del usuario
            user.first_name = first_name
            user.last_name = last_name
            user.email = email
            user.save()
            
            messages.success(request, '¡Perfil actualizado exitosamente!')
            return redirect('core:profile')
        except Exception as e:
            messages.error(request, f'Error al actualizar el perfil: {str(e)}')
            return render(request,'core/profile_edit.html')
    return render(request, 'core/profile_edit.html')

@login_required
def change_password(request):
    """Vista para cambiar la contraseña del usuario"""
    
    if request.method == 'POST':
        user = request.user
        current_password = request.POST.get('current_password','')
        # ✅ CORRECCIÓN 2: new_password en lugar de nex_password
        new_password = request.POST.get('new_password','')
        confirm_password = request.POST.get('confirm_password','')
        
        #Validaciones
        if not all([current_password, new_password, confirm_password]):
            messages.error(request, 'Todos los campos son obligatorios')
            return render(request, 'core/change_password.html')
        
        #Verificar contraseña actual
        if not user.check_password(current_password):
            messages.error(request, 'La contraseña actual es incorrecta')
            return render(request, 'core/change_password.html')
        
        #Verificar que las contraseñas coincidan
        if new_password != confirm_password:
            messages.error(request, 'Las contraseñas nuevas no coinciden')
            return render(request, 'core/change_password.html')
        
        #Verificar longitud minima
        if len(new_password) < 8:
            messages.error(request, 'La contraseña debe tener al menos 8 caracteres')
            return render(request, 'core/change_password.html')
        
        try:
            #Cambiar contraseña
            user.set_password(new_password)
            user.save()
            
            # Mantener la sesion activa despues de cambiar la contraseña
            update_session_auth_hash(request, user)
            
            messages.success(request, '¡Contraseña cambiada exitosamente!')
            return redirect('core:profile')
        except Exception as e:
            messages.error(request, f'Error al cambiar la contraseña: {str(e)}')
            return render(request, 'core/change_password.html')
    
    return render(request, 'core/change_password.html')

def accessibility(request):
    return render(request, 'core/accessibility.html')


# ============================================
# ✅ NUEVA CLASE PARA ENVIAR HTML EN EMAILS
# ============================================
class CustomPasswordResetView(PasswordResetView):
    """
    Vista personalizada para enviar correos HTML en el restablecimiento de contraseña.
    """
    
    def form_valid(self, form):
        """
        Sobrescribe form_valid para personalizar el envío del email.
        """
        # Obtener los datos del formulario
        opts = {
            'use_https': self.request.is_secure(),
            'token_generator': self.token_generator,
            'from_email': self.from_email,
            'email_template_name': self.email_template_name,
            'subject_template_name': self.subject_template_name,
            'request': self.request,
            'html_email_template_name': self.html_email_template_name,
            'extra_email_context': self.extra_email_context,
        }
        
        # Obtener usuarios asociados al email
        email = form.cleaned_data["email"]
        for user in form.get_users(email):
            # Construir el contexto del email
            context = {
                'email': user.email,
                'domain': self.request.get_host(),
                'site_name': self.request.get_host(),
                'uid': urlsafe_base64_encode(force_bytes(user.pk)),
                'user': user,
                'token': self.token_generator.make_token(user),
                'protocol': 'https' if self.request.is_secure() else 'http',
            }
            
            # Renderizar asunto
            subject = render_to_string(self.subject_template_name, context)
            subject = ''.join(subject.splitlines())
            
            # Renderizar HTML
            html_content = render_to_string(self.email_template_name, context)
            
            # Crear y enviar el email
            email_message = EmailMultiAlternatives(
                subject=subject,
                body='Habilita HTML para ver este mensaje.',
                from_email=opts['from_email'],
                to=[user.email]
            )
            email_message.attach_alternative(html_content, "text/html")
            email_message.send(fail_silently=False)
        
        # ✅ Redirigir manualmente sin llamar a super() para evitar envío duplicado
        return HttpResponseRedirect(self.success_url)