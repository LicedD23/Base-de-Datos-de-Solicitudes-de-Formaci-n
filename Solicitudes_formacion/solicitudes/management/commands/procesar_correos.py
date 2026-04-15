"""
Comando de gestión Django para procesar correos electrónicos.
Puede ejecutarse una sola vez o en modo continuo (cada 5 minutos).

Uso:
    python manage.py procesar_correos
    python manage.py procesar_correos --continuo
    python manage.py procesar_correos --limite 10 --workers 3
"""

import time

from django.core.management.base import BaseCommand

from solicitudes.email_handler import EmailSolicitudHandler


# Tiempo de espera entre ciclos en modo continuo (segundos)
INTERVALO_CICLO   = 300   # 5 minutos
ESPERA_EN_ERROR   = 60    # 1 minuto si hay error


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

    # ─────────────────────────────────────────────
    # Helpers internos
    # ─────────────────────────────────────────────

    def _ejecutar_ciclo(self, limite, workers):
        """
        Ejecuta un ciclo de procesamiento de correos.
        Crea el handler, llama a procesar_correos y retorna las solicitudes creadas.
        """
        self.stdout.write('📬 Iniciando ciclo de procesamiento...')
        handler = EmailSolicitudHandler()
        return handler.procesar_correos(
            limite=limite,
            procesar_en_paralelo=True,
            max_workers=workers,
        )

    def _modo_unico(self, limite, workers):
        """
        Ejecuta un solo ciclo de procesamiento y termina.
        Es el comportamiento por defecto cuando no se usa --continuo.
        """
        self._ejecutar_ciclo(limite, workers)
        self.stdout.write(self.style.SUCCESS('✅ Correos procesados exitosamente'))

    def _modo_continuo(self, limite, workers):
        """
        Ejecuta ciclos de procesamiento indefinidamente cada INTERVALO_CICLO segundos.
        Se detiene cuando el usuario presiona Ctrl+C.
        Si ocurre un error en un ciclo, espera ESPERA_EN_ERROR segundos y reintenta.
        """
        self.stdout.write(self.style.SUCCESS('🔁 Modo continuo activado — Ctrl+C para detener'))

        while True:
            try:
                self._ejecutar_ciclo(limite, workers)
                self.stdout.write(f'⏳ Esperando {INTERVALO_CICLO // 60} minutos...\n')
                time.sleep(INTERVALO_CICLO)

            except KeyboardInterrupt:
                # El usuario detuvo el proceso manualmente — salida limpia
                self.stdout.write(self.style.WARNING('\n🛑 Proceso detenido por el usuario'))
                break

            except Exception as e:
                # Error en el ciclo — esperar y reintentar en lugar de detener
                self.stdout.write(self.style.ERROR(f'❌ Error en ciclo: {e}'))
                self.stdout.write(f'⏳ Reintentando en {ESPERA_EN_ERROR} segundos...')
                time.sleep(ESPERA_EN_ERROR)

    # ─────────────────────────────────────────────
    # Entrypoint
    # ─────────────────────────────────────────────

    def handle(self, *args, **options):
        """
        Punto de entrada del comando.
        Decide entre modo único y modo continuo según los argumentos.
        """
        limite  = options['limite']
        workers = options['workers']

        if options['continuo']:
            self._modo_continuo(limite, workers)
        else:
            self._modo_unico(limite, workers)