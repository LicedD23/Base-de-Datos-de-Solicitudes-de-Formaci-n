from django.contrib import admin
from .models import Area, Empresa, Programa, Instructor, Solicitud

# Register your models here.
@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display= ['nombre','contacto','telefono','municipio','numero_trabajadores']
    search_fields = ['nombre','contacto','municipio']
    list_filter = ['municipio']
    
@admin.register(Programa)
class ProgramaAdmin(admin.ModelAdmin):
    list_display = ['area','nombre','duracion_horas','activo']
    search_fields = ['nombre','area__nombre']
    list_filter = ['area','activo']
    raw_id_fields = ('area',)

@admin.register(Instructor)
class InstructorAdmin(admin.ModelAdmin):
    list_display = ['nombre','telefono','correo','activo']
    list_filter = ['activo','especialidad']
    filter_horizontal = ['especialidad']

@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ['empresa','programa','fecha_recepcion','instructor_asignado','estado']
    list_filter = ['estado','programa','fecha_recepcion']
    search_fields = ['empresa__nombre','observaciones']
    date_hierarchy = 'fecha_recepcion'
    
    fieldsets = (
        ('Informacion Basica',{
            'fields': ('empresa','programa','fecha_recepcion')
        }),
        ('Asignacion',{
            'fields':('instructor_asignado','estado')
        }),
        ('Fechas de Seguimiento',{
            'fields':('fecha_respuesta','fecha_atencion')
        }),
        ('Observaciones',{
            'fields':('observaciones',)
        }),
        )


class ProgramaInline(admin.TabularInline):
    model = Programa
    extra = 1
    show_change_link = True


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'activo', 'fecha_creacion']
    search_fields = ['nombre']
    list_filter = ['activo']
    inlines = [ProgramaInline]
    