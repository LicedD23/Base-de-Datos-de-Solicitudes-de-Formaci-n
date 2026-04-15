from django.shortcuts import render, redirect
from django.utils import timezone
from django.contrib.auth import authenticate, login, update_session_auth_hash, logout
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.contrib.auth.views import PasswordResetView
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

from programas.models import Programa
from empresas.models import Empresa
from instructores.models import Instructor
from solicitudes.models import Solicitud
from core.management.decorators import admin_requerido

try:
    from solicitudes.models import EstadoSolicitud
except Exception:
    EstadoSolicitud = None


# ─────────────────────────────────────────────
# Roles válidos para registro de usuarios
# ─────────────────────────────────────────────
ROLES_VALIDOS = ['Administrador', 'Asistente', 'Coordinador']


# ─────────────────────────────────────────────
# Vistas
# ─────────────────────────────────────────────

@login_required
def dashboard(request):
    """Dashboard adaptado según el rol del usuario"""
    user = request.user

    es_administrador = user.is_superuser or user.groups.filter(name='Administrador').exists()
    es_asistente     = user.groups.filter(name='Asistente').exists()
    es_coordinador   = user.groups.filter(name='Coordinador').exists()

    # Métricas base (todos los roles)
    total_solicitudes  = Solicitud.objects.count()
    total_empresas     = Empresa.objects.count()
    total_programas    = Programa.objects.count()
    total_instructores = Instructor.objects.filter(activo=True).count()

    solicitudes_pendientes  = None
    solicitudes_finalizadas = None
    ultimas_solicitudes_qs  = []

    if es_administrador or es_asistente:
        solicitudes_pendientes  = Solicitud.objects.filter(estado='RECIBIDA').count()
        solicitudes_finalizadas = Solicitud.objects.filter(estado='FINALIZADA').count()
        ultimas_solicitudes_qs  = Solicitud.objects.select_related(
            'empresa', 'programa', 'instructor_asignado'
        ).order_by('-fecha_recepcion')[:15]

    elif es_coordinador:
        solicitudes_pendientes = Solicitud.objects.filter(estado='RECIBIDA').count()
        ultimas_solicitudes_qs = Solicitud.objects.select_related(
            'empresa', 'programa', 'instructor_asignado'
        ).order_by('-fecha_recepcion')[:10]

    # Limpiar NITs con valor 'None' como string antes de enviar al template
    ultimas_solicitudes = []
    for s in ultimas_solicitudes_qs:
        if s.empresa.nit and str(s.empresa.nit).strip().lower() == 'none':
            s.empresa.nit = None
        ultimas_solicitudes.append(s)

    # Métricas base siempre presentes
    metrics = [
        (total_solicitudes,  'Total Solicitudes',    'bi-file-text-fill',    'primary'),
        (total_empresas,     'Empresas Registradas', 'bi-building-fill',     'info'),
        (total_programas,    'Programas Activos',    'bi-book-fill',         'warning'),
        (total_instructores, 'Instructores Activos', 'bi-person-badge-fill', 'secondary'),
    ]

    # Métricas adicionales según rol
    metricas_opcionales = [
        (solicitudes_pendientes,  'Pendientes',  'bi-clock-history',      'danger'),
        (solicitudes_finalizadas, 'Finalizadas', 'bi-check-circle-fill',  'success'),
    ]
    for valor, label, icono, color in metricas_opcionales:
        if valor is not None:
            metrics.append((valor, label, icono, color))

    context = {
        'metrics':             metrics,
        'ultimas_solicitudes': ultimas_solicitudes,
        'es_administrador':    es_administrador,
        'es_coordinador':      es_coordinador,
        'es_asistente':        es_asistente,
        'now':                 timezone.now(),
    }
    return render(request, 'core/dashboard.html', context)


def home(request):
    """Página de inicio pública."""
    return render(request, 'core/home.html')


def login_view(request):
    """Vista para iniciar sesión"""
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    if request.method != 'POST':
        return render(request, 'core/login.html')

    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
    user     = authenticate(request, username=username, password=password)

    if user is not None:
        login(request, user)
        nombre  = user.get_full_name() or user.username
        messages.success(request, f'¡Bienvenido {nombre}!')
        next_url = request.GET.get('next', 'core:dashboard')
        return redirect(next_url)

    messages.error(request, 'Usuario o contraseña incorrectos')
    return render(request, 'core/login.html')


@admin_requerido
def register_user_view(request):
    """Vista para crear usuarios con diferentes roles (Administrador, Asistente, Coordinador)"""
    if request.method != 'POST':
        return render(request, 'core/register_user.html')

    username   = request.POST.get('username',   '').strip()
    email      = request.POST.get('email',      '').strip()
    password   = request.POST.get('password',   '')
    password2  = request.POST.get('password2',  '')
    first_name = request.POST.get('first_name', '').strip()
    last_name  = request.POST.get('last_name',  '').strip()
    rol        = request.POST.get('rol',        '')

    # Validaciones en orden: (condición de error, mensaje)
    validaciones = [
        (not all([username, email, password, password2, rol]),
         'Todos los campos son obligatorios'),
        (password != password2,
         'Las contraseñas no coinciden'),
        (len(password) < 8,
         'La contraseña debe tener al menos 8 caracteres'),
        (rol not in ROLES_VALIDOS,
         'Rol inválido'),
        (User.objects.filter(username=username).exists(),
         f'El nombre de usuario "{username}" ya existe'),
        (User.objects.filter(email=email).exists(),
         f'El correo "{email}" ya está registrado'),
    ]
    for condicion, mensaje in validaciones:
        if condicion:
            messages.error(request, mensaje)
            return render(request, 'core/register_user.html')

    try:
        user = User.objects.create_user(
            username=username, email=email, password=password,
            first_name=first_name, last_name=last_name
        )
        user.is_staff      = (rol == 'Administrador')
        user.is_superuser  = False
        user.save()

        try:
            grupo = Group.objects.get(name=rol)
            user.groups.add(grupo)
            user.save()
        except Group.DoesNotExist:
            user.delete()
            messages.error(
                request,
                f'El rol "{rol}" no existe. Ejecuta "python manage.py crear_roles"'
            )
            return render(request, 'core/register_user.html')

        messages.success(request, f'✅ Usuario "{username}" creado con rol "{rol}"')
        return redirect('core:dashboard')

    except Exception as e:
        messages.error(request, f'Error: {str(e)}')
        return render(request, 'core/register_user.html')


def logout_view(request):
    """Vista para cerrar sesión"""
    nombre = request.user.get_full_name() or request.user.username
    logout(request)
    messages.success(request, f'Hasta pronto {nombre}! Has cerrado sesión exitosamente')
    return redirect('core:home')


@login_required
def profile_view(request):
    """Vista para ver el perfil del usuario"""
    context = {'user': request.user}

    if request.user.is_staff:
        context.update({
            'total_solicitudes':  Solicitud.objects.count(),
            'total_empresas':     Empresa.objects.count(),
            'total_programas':    Programa.objects.count(),
            'total_instructores': Instructor.objects.filter(activo=True).count(),
        })

    return render(request, 'core/profile.html', context)


@login_required
def profile_edit(request):
    """Vista para editar el perfil del usuario"""
    if request.method != 'POST':
        return render(request, 'core/profile_edit.html')

    user       = request.user
    first_name = request.POST.get('first_name', '').strip()
    last_name  = request.POST.get('last_name',  '').strip()
    email      = request.POST.get('email',      '').strip()

    # Validaciones en orden
    validaciones = [
        (not email,
         'El correo electrónico es obligatorio'),
        (User.objects.filter(email=email).exclude(id=user.id).exists(),
         'Este correo electrónico ya está en uso'),
    ]
    for condicion, mensaje in validaciones:
        if condicion:
            messages.error(request, mensaje)
            return render(request, 'core/profile_edit.html')

    try:
        user.first_name = first_name
        user.last_name  = last_name
        user.email      = email
        user.save()
        messages.success(request, '¡Perfil actualizado exitosamente!')
        return redirect('core:profile')
    except Exception as e:
        messages.error(request, f'Error al actualizar el perfil: {str(e)}')
        return render(request, 'core/profile_edit.html')


@login_required
def change_password(request):
    """Vista para cambiar la contraseña del usuario"""
    if request.method != 'POST':
        return render(request, 'core/change_password.html')

    user             = request.user
    current_password = request.POST.get('current_password', '')
    new_password     = request.POST.get('new_password',     '')
    confirm_password = request.POST.get('confirm_password', '')

    # Validaciones en orden
    validaciones = [
        (not all([current_password, new_password, confirm_password]),
         'Todos los campos son obligatorios'),
        (not user.check_password(current_password),
         'La contraseña actual es incorrecta'),
        (new_password != confirm_password,
         'Las contraseñas nuevas no coinciden'),
        (len(new_password) < 8,
         'La contraseña debe tener al menos 8 caracteres'),
    ]
    for condicion, mensaje in validaciones:
        if condicion:
            messages.error(request, mensaje)
            return render(request, 'core/change_password.html')

    try:
        user.set_password(new_password)
        user.save()
        update_session_auth_hash(request, user)
        messages.success(request, '¡Contraseña cambiada exitosamente!')
        return redirect('core:profile')
    except Exception as e:
        messages.error(request, f'Error al cambiar la contraseña: {str(e)}')
        return render(request, 'core/change_password.html')


def accessibility(request):
    """Vista del panel de accesibilidad"""
    return render(request, 'core/accessibility.html')


@login_required
def manual_usuario(request):
    """Vista para mostrar el manual de usuario"""
    return render(request, 'core/manual_usuario.html')


# ─────────────────────────────────────────────
# Clase para enviar HTML en emails de recuperación
# ─────────────────────────────────────────────

class CustomPasswordResetView(PasswordResetView):
    """
    Vista personalizada para enviar correos HTML en el restablecimiento de contraseña.
    Evita el envío duplicado sobrescribiendo form_valid.
    """

    def form_valid(self, form):
        email = form.cleaned_data['email']

        for user in form.get_users(email):
            context = {
                'email':     user.email,
                'domain':    self.request.get_host(),
                'site_name': self.request.get_host(),
                'uid':       urlsafe_base64_encode(force_bytes(user.pk)),
                'user':      user,
                'token':     self.token_generator.make_token(user),
                'protocol':  'https' if self.request.is_secure() else 'http',
            }

            subject      = ''.join(render_to_string(self.subject_template_name, context).splitlines())
            html_content = render_to_string(self.email_template_name, context)

            email_message = EmailMultiAlternatives(
                subject=subject,
                body='Habilita HTML para ver este mensaje.',
                from_email=self.from_email,
                to=[user.email]
            )
            email_message.attach_alternative(html_content, 'text/html')
            email_message.send(fail_silently=False)

        # Redirige manualmente para evitar envío duplicado del padre
        return HttpResponseRedirect(self.success_url)