from django.core.management.base import BaseCommand
from solicitudes.email_handler import EmailSolicitudHandler


class Command(BaseCommand):
    help = 'Procesa correos electrónicos y crea solicitudes automáticamente'

    def add_arguments(self, parser):
        parser.add_argument(
            '--continuo',
            action='store_true',
            help='Ejecuta en modo continuo (cada 5 minutos)',
        )

    def handle(self, *args, **options):
        handler = EmailSolicitudHandler()
        
        if options['continuo']:
            import time
            self.stdout.write(
                self.style.SUCCESS('Modo continuo activado - Ctrl+C para detener')
            )
            
            while True:
                try:
                    handler.procesar_correos()
                    self.stdout.write('Esperando 5 minutos...\n')
                    time.sleep(300)  # 5 minutos
                except KeyboardInterrupt:
                    self.stdout.write(
                        self.style.WARNING('\nProceso detenido por el usuario')
                    )
                    break
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'Error: {e}')
                    )
                    time.sleep(60)  # Esperar 1 minuto en caso de error
        else:
            handler.procesar_correos()
            self.stdout.write(
                self.style.SUCCESS('Correos procesados exitosamente')
            )
                        
                    
                    