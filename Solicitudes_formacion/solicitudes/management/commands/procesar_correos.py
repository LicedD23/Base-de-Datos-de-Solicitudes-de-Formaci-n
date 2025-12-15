from django.core.management.base import BaseCommand
from solicitudes.email_handler import EmailSolicitudHandler
import time


class Command(BaseCommand):
    help = 'Procesa correos electrónicos y crea solicitudes automáticamente'

    def add_arguments(self, parser):
        parser.add_argument(
            '--continuo',
            action='store_true',
            help='Ejecuta en modo continuo (cada 5 minutos)',
        )

        parser.add_argument(
            '--limite',
            type=int,
            default=None,
            help='Máximo número de correos a procesar por ciclo',
        )

        parser.add_argument(
            '--workers',
            type=int,
            default=5,
            help='Número de hilos para procesamiento paralelo',
        )

    def handle(self, *args, **options):
        limite = options['limite']
        workers = options['workers']

        if options['continuo']:
            self.stdout.write(
                self.style.SUCCESS('🔁 Modo continuo activado - Ctrl+C para detener')
            )

            while True:
                try:
                    self.stdout.write('📬 Iniciando nuevo ciclo de procesamiento...')
                    
                    handler = EmailSolicitudHandler()
                    handler.procesar_correos(
                        limite=limite,
                        procesar_en_paralelo=True,
                        max_workers=workers
                    )

                    self.stdout.write('⏳ Esperando 5 minutos...\n')
                    time.sleep(300)

                except KeyboardInterrupt:
                    self.stdout.write(
                        self.style.WARNING('\n🛑 Proceso detenido por el usuario')
                    )
                    break

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'❌ Error: {e}')
                    )
                    time.sleep(60)
        else:
            handler = EmailSolicitudHandler()
            handler.procesar_correos(
                limite=limite,
                procesar_en_paralelo=True,
                max_workers=workers
            )

            self.stdout.write(
                self.style.SUCCESS('✅ Correos procesados exitosamente')
            )
