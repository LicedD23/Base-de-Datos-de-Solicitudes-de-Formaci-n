from django.contrib import admin
from .models import Instructor

@admin.register(Instructor)
class InstructorAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'cedula', 'telefono', 'correo', 'activo']
    search_fields = ['nombre', 'cedula', 'correo']
    list_filter = ['activo', 'especialidad']
    filter_horizontal = ['especialidad']
