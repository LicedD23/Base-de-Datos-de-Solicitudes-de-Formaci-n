from django.contrib import admin
from .models import Instructor

@admin.register(Instructor)
class InstructorAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'telefono', 'correo', 'activo']
    list_filter = ['activo', 'especialidad']
    filter_horizontal = ['especialidad']
