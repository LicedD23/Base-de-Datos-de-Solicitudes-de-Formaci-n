"""
Manejador de correos electrónicos para solicitudes de formación.
Sistema de Gestión de Solicitudes SENA

Flujo general:
    1. Conectarse al servidor IMAP y leer correos no leídos
    2. Filtrar los correos que parecen solicitudes válidas (es_correo_valido)
    3. Extraer los datos de la solicitud del cuerpo o PDF adjunto (extraer_informacion_con_ia)
    4. Buscar o crear la empresa en la base de datos
    5. Buscar el programa solicitado
    6. Crear la solicitud y guardar los PDFs adjuntos

Versión actual acepta correos con:
    - Cuerpo completo con datos de la empresa
    - Plantilla estructurada (Nombre: , NIT: , etc.)
    - Asunto válido + PDF adjunto (aunque el cuerpo sea muy corto)
    - PDF escaneado → crea solicitud mínima para revisión manual
"""

import imaplib
import email
import re
import unicodedata
import logging
from email.header import decode_header
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.core.files.base import ContentFile

from .models import Solicitud, DocumentoSolicitud
from empresas.models import Empresa
from programas.models import Programa
from instructores.models import Instructor

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTES DE FILTRADO
# Definidas aquí para cambiarlas fácilmente sin tocar la lógica de la clase.
# =============================================================================

# Palabras que deben aparecer en el asunto para considerar el correo válido
PALABRAS_CLAVE_ASUNTO = [
    'solicitud', 'formación', 'formacion', 'capacitación', 'capacitacion',
    'programa', 'curso', 'entrenamiento', 'sena', 'ficha', 'convenio',
    'solicitud de formacion', 'solicitud de formación',
    'solicitud de capacitacion', 'solicitud de capacitación',
    'solicitud curso', 'solicitud de curso',
    'solicitud sena', 'solicitud de programa',
    'apoyo', 'placa', 'proyecto',
]

# Palabras que deben aparecer en el cuerpo (mínimo 2) en correos sin PDF
PALABRAS_CLAVE_CUERPO = [
    'solicito', 'solicitamos', 'requerimos',
    'nit', 'empresa', 'entidad', 'institución', 'institucion',
    'trabajadores', 'funcionarios', 'empleados', 'internos', 'beneficiarios',
    'programa de formación', 'programa de formacion',
    'alcaldía', 'alcaldia', 'gobernación', 'gobernacion',
    'fundación', 'fundacion', 'corporación', 'corporacion',
    'inpec', 'penitenciaria', 'penitenciaría',
    'institución educativa', 'institucion educativa',
    'ficha sena', 'ficha de caracterización', 'ficha de caracterizacion',
    'código de ficha', 'numero de ficha',
    'adjunto', 'oficio', 'documento', 'solicitud',
]

# Remitentes que se ignoran automáticamente (bots, marketing, etc.)
DOMINIOS_EXCLUIDOS = [
    'noreply', 'no-reply', 'mailer-daemon', 'postmaster',
    'notification', 'marketing', 'newsletter',
]

# Sufijos jurídicos de empresas privadas (para extraer nombre)
SUFIJOS_EMPRESA = [
    r'S\.A\.S\.?', r'\bSAS\b', r'S\.A\.', r'\bSA\b',
    r'LTDA\.?', r'\bEU\b', r'E\.U\.?',
    r'S\.C\.A\.?', r'S\.C\.S\.?', r'S\s+EN\s+C',
]

# Prefijos de instituciones públicas y sin ánimo de lucro (para extraer nombre)
PREFIJOS_INSTITUCION = [
    r'Alcald[íi]a\s+(?:Municipal\s+)?(?:de(?:l)?\s+)?',
    r'Gobernaci[oó]n\s+(?:de(?:l)?\s+)?',
    r'Municipio\s+de\s+',
    r'Distrito\s+(?:de\s+)?',
    r'INPEC\s*',
    r'Establecimiento\s+Penitenciario\s+(?:y\s+Carcelario\s+)?(?:de(?:l)?\s+)?',
    r'C[áa]rcel\s+(?:y\s+Penitenciar[íi]a\s+)?(?:de(?:l)?\s+)?',
    r'Colonia\s+Agr[íi]cola\s+(?:de(?:l)?\s+)?',
    r'Instituci[oó]n\s+Educativa\s+',
    r'I\.E\.\s+',
    r'Colegio\s+',
    r'Escuela\s+',
    r'Liceo\s+',
    r'Centro\s+Educativo\s+',
    r'Fundaci[oó]n\s+',
    r'Corporaci[oó]n\s+',
    r'Asociaci[oó]n\s+',
    r'Liga\s+',
    r'Federaci[oó]n\s+',
    r'Confederaci[oó]n\s+',
    r'Junta\s+(?:de\s+)?Acci[oó]n\s+Comunal\s+(?:de(?:l)?\s+)?',
    r'\bJAC\b\s+',
    r'Ministerio\s+de\s+',
    r'Departamento\s+Administrativo\s+(?:de(?:l)?\s+)?',
    r'Unidad\s+Administrativa\s+Especial\s+',
    r'Superintendencia\s+(?:de(?:l)?\s+)?',
    r'Agencia\s+Nacional\s+(?:de(?:l)?\s+)?',
    r'Instituto\s+Colombiano\s+(?:de(?:l)?\s+)?',
    r'Empresa\s+Social\s+del\s+Estado\s+',
    r'\bESE\b\s+',
    r'Hospital\s+(?:Departamental\s+|Municipal\s+|Universitario\s+|Regional\s+)?',
    r'Registradur[íi]a\s+',
    r'Procuradur[íi]a\s+',
    r'Contralor[íi]a\s+',
    r'Person[íi]a\s+',
    r'Defensor[íi]a\s+del\s+Pueblo\s+',
    r'Fiscal[íi]a\s+',
    r'Juzgado\s+',
    r'Tribunal\s+',
    r'Polic[íi]a\s+Nacional\s+',
    r'Ej[eé]rcito\s+Nacional\s+',
    r'Armada\s+Nacional\s+',
    r'Fuerza\s+A[eé]rea\s+',
    r'ICBF\s+',
    r'SENA\s+Regional\s+',
]

# Palabras clave para identificar el programa solicitado
KEYWORDS_PROGRAMAS = {
    'minicargador':              'Operador de Minicargador',
    'mini cargador':             'Operador de Minicargador',
    'montacargas':               'Operador de Montacargas',
    'excavadora':                'Operador de Excavadora',
    'retrocargador':             'Operador de Retrocargador',
    'interpretacion de planos':  'Interpretación de planos para maquinaria industrial',
    'interpretación de planos':  'Interpretación de planos para maquinaria industrial',
    'planos maquinaria':         'Interpretación de planos para maquinaria industrial',
    'lectura de planos':         'Interpretación de planos para maquinaria industrial',
    'placas huellas':            'Placas Huellas',
    'placa huella':              'Placas Huellas',
}

# Mapa de códigos de ficha SENA a nombres de programa
FICHAS_SENA = {
    '2350024': 'Operador de Minicargador',
    '2350025': 'Operador de Montacargas',
    '2350026': 'Operador de Excavadora',
    '2350027': 'Operador de Retrocargador',
    '2350028': 'Interpretación de planos para maquinaria industrial',
    '2600001': 'Seguridad y Salud en el Trabajo',
    '2600002': 'Trabajo en Alturas',
    '2600003': 'Manejo Seguro de Sustancias Químicas',
    '2700001': 'Logística Empresarial',
    '2700002': 'Gestión de Almacenes',
    '2800001': 'Servicio al Cliente',
    '2800002': 'Gestión Administrativa',
}

# Patrones regex para encontrar el código de ficha SENA en el texto
PATRON_FICHA_SENA = [
    r'ficha\s*(?:sena)?\s*[:\-]?\s*(\d{5,10})',
    r'c[oó]digo\s+de\s+ficha\s*[:\-]?\s*(\d{5,10})',
    r'ficha\s+de\s+caracterizaci[oó]n\s*[:\-]?\s*(\d{5,10})',
    r'n[uú]mero\s+de\s+ficha\s*[:\-]?\s*(\d{5,10})',
]

# Límites de configuración
CAMPOS_MINIMOS_REQUERIDOS = 2    # campos mínimos para considerar una extracción válida
MAX_PDF_SIZE              = 10 * 1024 * 1024  # 10 MB
MAX_PDFS_POR_EMAIL        = 5    # máximo PDFs por correo
CUERPO_MINIMO_CHARS       = 150  # si el cuerpo tiene menos → buscar datos en el PDF

# Campos de la plantilla estructurada del sistema
CAMPOS_PLANTILLA = [
    'nombre', 'nit', 'contacto', 'teléfono', 'telefono',
    'programa', 'aprendices', 'correo', 'email', 'empresa', 'entidad',
]


# =============================================================================
# CLASE PRINCIPAL
# =============================================================================

class EmailSolicitudHandler:
    """
    Manejador de correos para solicitudes de formación del SENA.

    Responsabilidades:
        - Conectarse al servidor IMAP y leer correos no leídos
        - Filtrar correos que son solicitudes válidas
        - Extraer datos de la solicitud (nombre, NIT, programa, etc.)
        - Buscar o crear la empresa en la base de datos
        - Buscar el programa solicitado
        - Crear la solicitud con sus documentos PDF adjuntos

    Uso básico:
        handler = EmailSolicitudHandler()
        solicitudes = handler.procesar_correos(limite=20)
    """

    def __init__(self):
        # Credenciales del servidor IMAP leídas desde settings.py
        self.imap_server    = getattr(settings, 'IMAP_HOST',     'imap.gmail.com')
        self.imap_port      = getattr(settings, 'IMAP_PORT',     993)
        self.email_account  = getattr(settings, 'IMAP_USER',     settings.EMAIL_HOST_USER)
        self.email_password = getattr(settings, 'IMAP_PASSWORD', settings.EMAIL_HOST_PASSWORD)

        # Contadores para el resumen al final del procesamiento
        self.stats = {
            'total_correos':      0,
            'correos_filtrados':  0,
            'correos_procesados': 0,
            'solicitudes_creadas':0,
            'pdfs_extraidos':     0,
            'errores':            0,
            'creadas_desde_pdf':  0,
            'revision_manual':    0,
        }

        print(f"🔧 IMAP: {self.imap_server}:{self.imap_port}")
        print(f"📧 Cuenta: {self.email_account}")

    # =========================================================================
    # UTILIDADES DE TEXTO
    # Funciones pequeñas para limpiar y normalizar texto antes de procesarlo.
    # =========================================================================

    def limpiar_texto(self, texto):
        """
        Limpia un texto eliminando asteriscos y espacios extra.
        Retorna None si el texto queda vacío o es un valor nulo conocido.
        """
        if not texto:
            return None
        texto = texto.replace('*', '')
        texto = re.sub(r'\s+', ' ', texto).strip()
        if not texto or texto.lower() in ('sin especificar', 'no especificado', 'n/a', 'na'):
            return None
        return texto

    def validar_nit(self, nit):
        """
        Valida y limpia un NIT colombiano.
        Retorna el NIT solo con dígitos, o None si no es válido.
        Un NIT válido tiene entre 8 y 12 dígitos y no parece un número celular.
        """
        if not nit:
            return None

        limpio = nit.replace(' ', '').replace('-', '').replace('.', '')

        if not limpio.isdigit():
            return None
        if not (8 <= len(limpio) <= 12):
            return None

        # Los celulares colombianos empiezan por 3 y tienen 10 dígitos
        if limpio.startswith('3') and len(limpio) == 10:
            print(f"   ⚠️  Parece celular, no NIT: {limpio}")
            return None

        print(f"   ✅ NIT: {limpio}")
        return limpio

    def normalizar_texto(self, texto):
        """
        Convierte texto a minúsculas, elimina tildes y caracteres especiales.
        Usado para comparaciones simples.
        """
        if not texto:
            return ''
        texto = texto.lower()
        texto = ''.join(
            c for c in unicodedata.normalize('NFD', texto)
            if unicodedata.category(c) != 'Mn'
        )
        return re.sub(r'[^a-z0-9\s]', '', re.sub(r'\s+', ' ', texto)).strip()

    def normalizar_para_busqueda(self, texto):
        """
        Normalización avanzada para buscar programas.

        Además de quitar tildes y pasar a minúsculas, normaliza plurales:
            'minicargadores' → 'minicargador'
            'placas huellas' → 'placa huella'
            'excavadoras'    → 'excavadora'

        Esto evita necesitar keywords manuales para cada variante del nombre.
        """
        if not texto:
            return ''

        # Paso 1: quitar tildes y pasar a minúsculas
        texto = texto.lower()
        texto = ''.join(
            c for c in unicodedata.normalize('NFD', texto)
            if unicodedata.category(c) != 'Mn'
        )
        texto = re.sub(r'[^a-z0-9\s]', '', re.sub(r'\s+', ' ', texto)).strip()

        # Paso 2: normalizar plurales token por token
        tokens = []
        for token in texto.split():
            if len(token) > 4 and token.endswith('es'):
                token = token[:-2]    # 'operadores' → 'operador'
            elif len(token) > 3 and token.endswith('s'):
                token = token[:-1]    # 'placas' → 'placa', 'huellas' → 'huella'
            tokens.append(token)

        return ' '.join(tokens)

    # =========================================================================
    # CONEXIÓN Y LECTURA DE CORREOS
    # =========================================================================

    def conectar_email(self):
        """
        Conecta al servidor IMAP usando SSL y retorna el objeto de conexión.
        Retorna None si las credenciales no están configuradas o si hay error.
        """
        try:
            if not self.email_account or not self.email_password:
                print("❌ Credenciales no configuradas en settings.py")
                return None

            print(f"🔌 Conectando a {self.imap_server}:{self.imap_port}")
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_account, self.email_password)
            print(f"✅ Conectado: {self.email_account}")
            return mail

        except imaplib.IMAP4.error as e:
            print(f"❌ Error de autenticación: {e}")
            return None
        except Exception as e:
            print(f"❌ Error de conexión: {e}")
            return None

    def leer_correos_no_leidos(self, limite=20):
        """
        Lee los correos no leídos de la bandeja de entrada.
        Parsea cada correo y retorna una lista de dicts con su información.

        Parámetros:
            limite → máximo de correos a procesar (None = sin límite)
        """
        mail = self.conectar_email()
        if not mail:
            return []

        try:
            status, _ = mail.select('INBOX')
            if status != 'OK':
                return []

            # UNSEEN = correos no leídos
            status, data = mail.search(None, 'UNSEEN')
            if status != 'OK':
                return []

            email_ids = data[0].split()
            self.stats['total_correos'] = len(email_ids)
            print(f"\n📬 Correos no leídos: {len(email_ids)}")

            if not email_ids:
                return []

            # Aplicar límite si se especificó
            if limite and len(email_ids) > limite:
                print(f"⚠️  Límite activo: procesando {limite} de {len(email_ids)}")
                email_ids = email_ids[:limite]

            correos = []
            for idx, eid in enumerate(email_ids, 1):
                try:
                    print(f"\n{'='*60}\n📨 Correo {idx}/{len(email_ids)}\n{'='*60}")
                    status, msg_data = mail.fetch(eid, '(RFC822)')
                    if status != 'OK':
                        continue
                    msg  = email.message_from_bytes(msg_data[0][1])
                    info = self.parsear_correo(msg)
                    if info:
                        info['email_id'] = eid
                        correos.append(info)
                except Exception as e:
                    print(f"⚠️  Error procesando correo {idx}: {e}")
                    continue

            mail.close()
            mail.logout()
            return correos

        except Exception as e:
            print(f"❌ Error leyendo correos: {e}")
            return []

    def parsear_correo(self, msg):
        """
        Extrae los campos básicos de un mensaje de correo:
        asunto, remitente, cuerpo de texto y PDFs adjuntos.

        Retorna un dict con estos campos, o None si hay error.
        """
        try:
            # Decodificar el asunto (puede venir en base64 o quoted-printable)
            subject = ''
            if msg['Subject']:
                raw     = decode_header(msg['Subject'])[0]
                subject = (
                    raw[0].decode(raw[1] or 'utf-8', errors='ignore')
                    if isinstance(raw[0], bytes) else raw[0]
                )

            from_email = msg.get('From', '')
            body       = ''

            # Buscar la parte de texto plano del correo
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode('utf-8', errors='ignore')
                                break
                        except Exception:
                            pass
            else:
                try:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode('utf-8', errors='ignore')
                except Exception:
                    pass

            return {
                'asunto':        subject,
                'remitente':     from_email,
                'cuerpo':        body,
                'fecha':         msg.get('Date', ''),
                'pdfs_adjuntos': self.extraer_pdfs_adjuntos(msg),
            }

        except Exception as e:
            print(f"❌ Error parseando correo: {e}")
            return None

    def extraer_pdfs_adjuntos(self, msg):
        """
        Extrae todos los archivos PDF adjuntos de un correo.
        Valida tamaño, firma PDF (%PDF) y límite por correo.

        Retorna lista de dicts con: nombre, contenido (bytes), size.
        """
        pdfs = []
        try:
            print("\n   === BUSCANDO PDFs ===")
            if not msg.is_multipart():
                print("   ℹ️  Correo sin adjuntos")
                return pdfs

            for part in msg.walk():
                # Solo nos interesan los adjuntos (no el cuerpo del correo)
                if part.get_content_maintype() == 'multipart':
                    continue
                if part.get('Content-Disposition') is None:
                    continue

                filename = part.get_filename()
                if not filename:
                    continue

                # Decodificar nombre del archivo si viene codificado
                if isinstance(filename, bytes):
                    filename = filename.decode('utf-8', errors='ignore')
                else:
                    partes   = decode_header(filename)
                    filename = ''.join(
                        p.decode(enc or 'utf-8', errors='ignore')
                        if isinstance(p, bytes) else p
                        for p, enc in partes
                    )

                if not filename.lower().endswith('.pdf'):
                    continue

                data = part.get_payload(decode=True)
                if not data:
                    continue

                size = len(data)

                # Validaciones de seguridad
                if size > MAX_PDF_SIZE:
                    print(f"   ⚠️  '{filename}' supera el límite de tamaño — OMITIDO")
                    continue
                if not data.startswith(b'%PDF'):
                    print(f"   ⚠️  '{filename}' no tiene firma PDF válida — OMITIDO")
                    continue
                if len(pdfs) >= MAX_PDFS_POR_EMAIL:                          
                    print(f"   ⚠️  Límite de {MAX_PDFS_POR_EMAIL} PDFs alcanzado — OMITIDO")  
                    continue

                print(f"   ✅ PDF #{len(pdfs)+1}: {filename} ({size/1024:.1f} KB)")
                pdfs.append({'nombre': filename, 'contenido': data, 'size': size})

            print(f"   📄 Total PDFs encontrados: {len(pdfs)}")
            return pdfs

        except Exception as e:
            print(f"   ❌ Error extrayendo PDFs: {e}")
            return pdfs

    # =========================================================================
    # EXTRACCIÓN DE TEXTO DESDE PDF
    # Usada cuando el cuerpo del correo es muy corto y los datos vienen en PDF.
    # =========================================================================

    def extraer_texto_pdf(self, pdf_bytes):
        """
        Extrae texto plano de un PDF en memoria usando pdfplumber.

        ¿Por qué pdfplumber?
            - Maneja mejor PDFs con tablas y columnas que PyPDF2
            - Preserva mejor el orden de lectura
            - Más tolerante con PDFs mal formados

        Retorna:
            str con el texto extraído, o
            None si el PDF es una imagen escaneada o si pdfplumber no está instalado.
        """
        try:
            import pdfplumber
            import io

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                texto_total = ''

                for num_pagina, pagina in enumerate(pdf.pages, 1):
                    texto_pagina = pagina.extract_text()
                    if texto_pagina:
                        texto_total += texto_pagina + '\n'
                        print(f"   📄 Página {num_pagina}: {len(texto_pagina)} chars extraídos")
                    else:
                        print(f"   ⚠️  Página {num_pagina}: sin texto (posiblemente imagen)")

                texto_total = texto_total.strip()

                if texto_total:
                    print(f"   ✅ PDF: {len(texto_total)} caracteres extraídos en total")
                    return texto_total
                else:
                    print("   ⚠️  PDF sin texto — es un documento escaneado (imagen)")
                    return None

        except ImportError:
            print("   ❌ pdfplumber no instalado. Ejecuta: pip install pdfplumber")
            return None
        except Exception as e:
            print(f"   ⚠️  Error leyendo PDF: {e}")
            return None

    # =========================================================================
    # FILTRADO DE CORREOS
    # Decide si un correo es una solicitud válida o debe descartarse.
    #
    # PUERTAS DE ENTRADA (en orden de prioridad):
    #   PUERTA 1: Asunto válido + PDF adjunto → ACEPTADO (datos vienen del PDF)
    #   PUERTA 2: Asunto válido + plantilla estructurada en el cuerpo → ACEPTADO
    #   PUERTA 3: Asunto válido + cuerpo libre con ≥2 palabras clave → ACEPTADO
    # =========================================================================

    def es_correo_valido(self, correo_info):
        """
        Determina si el correo es una solicitud de formación válida.

        Retorna (True, razón) si es válido, o (False, razón) si debe descartarse.
        """
        try:
            asunto    = correo_info.get('asunto', '').lower()
            cuerpo    = correo_info.get('cuerpo', '')
            remitente = correo_info.get('remitente', '').lower()
            pdfs      = correo_info.get('pdfs_adjuntos', [])
            tiene_pdf = len(pdfs) > 0

            # Ignorar correos de bots y sistemas automáticos
            for dominio in DOMINIOS_EXCLUIDOS:
                if dominio in remitente:
                    return False, f"Dominio excluido: {dominio}"

            # El asunto siempre debe tener palabras clave
            if not any(p in asunto for p in PALABRAS_CLAVE_ASUNTO):
                return False, "Sin palabras clave en el asunto"

            # PUERTA 1: asunto válido + PDF adjunto → datos vienen del PDF
            if tiene_pdf:
                print(f"   ✅ PUERTA 1: Asunto válido + {len(pdfs)} PDF(s) → aceptado")
                return True, f"Asunto válido con {len(pdfs)} PDF adjunto(s)"

            # PUERTA 2: cuerpo con plantilla estructurada (Nombre: , NIT: , etc.)
            if self.es_correo_plantilla(cuerpo):
                print("   ✅ PUERTA 2: Plantilla estructurada detectada → aceptado")
                return True, "Correo con plantilla estructurada"

            # PUERTA 3: cuerpo libre con suficientes palabras clave
            cuerpo_lower = cuerpo.lower()
            encontradas  = sum(1 for p in PALABRAS_CLAVE_CUERPO if p in cuerpo_lower)

            if encontradas < CAMPOS_MINIMOS_REQUERIDOS:
                return False, f"Solo {encontradas} palabras clave en cuerpo (mínimo {CAMPOS_MINIMOS_REQUERIDOS})"

            if len(cuerpo) < 100:
                return False, f"Cuerpo muy corto ({len(cuerpo)} chars) y sin PDF adjunto"

            # Verificar que se puedan extraer campos suficientes
            info = self.extraer_informacion_con_ia(correo_info)
            if not info:
                return False, "No se pudo extraer información del cuerpo"

            campos = sum([
                1 if info.get('nombre')              else 0,
                1 if info.get('programa_solicitado') else 0,
                1 if info.get('correo')              else 0,
                1 if info.get('telefono')            else 0,
            ])
            if campos < CAMPOS_MINIMOS_REQUERIDOS:
                return False, f"Campos insuficientes ({campos}/{CAMPOS_MINIMOS_REQUERIDOS})"

            return True, "Correo válido (cuerpo completo)"

        except Exception as e:
            return False, f"Error en validación: {e}"

    def es_correo_plantilla(self, cuerpo):
        """
        Detecta si el cuerpo del correo usa la plantilla estructurada del sistema.
        Retorna True si tiene al menos 3 etiquetas conocidas (campo: valor).
        """
        cuerpo_lower = cuerpo.lower()
        encontrados  = sum(
            1 for campo in CAMPOS_PLANTILLA
            if f'{campo}:' in cuerpo_lower
        )
        return encontrados >= 3

    # =========================================================================
    # EXTRACCIÓN DE INFORMACIÓN
    # Tres niveles según el tipo de correo recibido.
    # =========================================================================

    def extraer_informacion_con_ia(self, correo_info):
        """
        Extrae todos los datos de la solicitud del correo.

        Niveles de extracción (en orden de prioridad):
            NIVEL 1: Cuerpo con plantilla estructurada → extraer_de_plantilla()
            NIVEL 2: Cuerpo corto + PDF adjunto → leer PDF y relanzar extracción
            NIVEL 3: Cuerpo libre largo → extracción con expresiones regulares

        Retorna un dict con: nombre, nit, contacto, correo, telefono,
        municipio, direccion, numero_trabajadores, programa_solicitado.
        Puede incluir _requiere_revision_manual=True si el PDF es escaneado.
        """
        try:
            cuerpo    = correo_info.get('cuerpo', '')
            remitente = correo_info.get('remitente', '')
            asunto    = correo_info.get('asunto', '')

            if not cuerpo and not correo_info.get('pdfs_adjuntos'):
                return None

            print("   Extrayendo información del correo...")

            # ------------------------------------------------------------------
            # NIVEL 1: Plantilla estructurada en el cuerpo
            # ------------------------------------------------------------------
            if self.es_correo_plantilla(cuerpo):
                print("   ✅ NIVEL 1: Plantilla estructurada detectada")
                info = self.extraer_de_plantilla(cuerpo)

                if not info['correo']:
                    m = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', remitente)
                    if m:
                        candidato = m.group(1).strip().lower()
                        if not any(d in candidato for d in DOMINIOS_EXCLUIDOS):
                            info['correo'] = candidato
                return info

            # ------------------------------------------------------------------
            # NIVEL 2: Cuerpo corto + PDF adjunto
            # ------------------------------------------------------------------
            pdfs            = correo_info.get('pdfs_adjuntos', [])
            cuerpo_es_corto = len(cuerpo.strip()) < CUERPO_MINIMO_CHARS

            if cuerpo_es_corto and pdfs:
                print(f"\n   === NIVEL 2: Cuerpo corto ({len(cuerpo.strip())} chars) + PDF ===")
                print(f"   📄 Leyendo PDF: {pdfs[0]['nombre']}")

                texto_pdf = self.extraer_texto_pdf(pdfs[0]['contenido'])

                if texto_pdf:
                    print("   ✅ Texto extraído del PDF — relanzando con texto enriquecido")
                    cuerpo_enriquecido           = texto_pdf + '\n\n--- CUERPO CORREO ---\n' + cuerpo
                    correo_enriquecido           = dict(correo_info)
                    correo_enriquecido['cuerpo'] = cuerpo_enriquecido
                    return self.extraer_informacion_con_ia(correo_enriquecido)

                else:
                    print("   ⚠️  PDF escaneado — creando solicitud mínima para revisión manual")
                    info_minima = {
                        'nombre': None, 'nit': None, 'contacto': None,
                        'correo': None, 'telefono': None, 'municipio': None,
                        'direccion': None, 'numero_trabajadores': None,
                        'programa_solicitado': None,
                        '_requiere_revision_manual': True,
                        '_razon': 'PDF adjunto es imagen escaneada, no se pudo extraer texto',
                    }

                    for keyword, nombre_prog in KEYWORDS_PROGRAMAS.items():
                        if keyword in asunto.lower():
                            info_minima['programa_solicitado'] = nombre_prog
                            print(f"   Programa (asunto): {nombre_prog}")
                            break

                    m = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', remitente)
                    if m:
                        candidato = m.group(1).strip().lower()
                        if not any(d in candidato for d in DOMINIOS_EXCLUIDOS):
                            info_minima['correo'] = candidato

                    return info_minima

            # ------------------------------------------------------------------
            # NIVEL 3: Cuerpo libre largo
            # ------------------------------------------------------------------
            print("   NIVEL 3: Extracción desde cuerpo libre")

            info = {
                'nombre': None, 'nit': None, 'contacto': None,
                'correo': None, 'telefono': None, 'municipio': None,
                'direccion': None, 'numero_trabajadores': None,
                'programa_solicitado': None,
            }

            # ── Nombre de la entidad ──────────────────────────────────────────
            print("\n   === NOMBRE DE ENTIDAD ===")
            info['nombre'] = self.extraer_nombre_entidad(cuerpo)

            # ── NIT ───────────────────────────────────────────────────────────
            print("\n   === NIT ===")
            for patron in [
                r'(?:Nombre|Entidad|Empresa)[^:\n]*:\s*[^\n]+?NIT[:\s]+([0-9\s\.\-]+)',
                r'NIT\s*:\s*([0-9\s\.\-]+)',
                r'NIT\s*[:\-]?\s*([0-9\s\.\-]{8,15})',
            ]:
                m = re.search(patron, cuerpo, re.IGNORECASE)
                if m:
                    nit_v = self.validar_nit(m.group(1).strip())
                    if nit_v:
                        info['nit'] = nit_v
                        break

            if not info['nit']:
                m = re.search(r'\b([0-9]{8,11})\b', cuerpo)
                if m:
                    info['nit'] = self.validar_nit(m.group(1))

            if not info['nit']:
                print("   ⚠️  Sin NIT")

            # ── Contacto ──────────────────────────────────────────────────────
            cont = re.search(
                r'(?:Contacto|Representante|Funcionario|Responsable)\s*:\s*([^\n]+)',
                cuerpo, re.IGNORECASE
            )
            if cont:
                contacto = self.limpiar_texto(cont.group(1))
                if contacto:
                    contacto         = re.sub(r'^Nombre:\s*', '', contacto, flags=re.IGNORECASE).strip()
                    info['contacto'] = contacto[:100]
                    print(f"   Contacto: {info['contacto']}")

            # ── Correo electrónico ────────────────────────────────────────────
            for patron in [
                r'(?:Correo|Email)\s*:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            ]:
                m = re.search(patron, cuerpo, re.IGNORECASE)
                if m:
                    info['correo'] = m.group(1).strip().lower()
                    break

            if not info['correo']:
                m = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', remitente)
                if m:
                    candidato = m.group(1).strip().lower()
                    if not any(d in candidato for d in DOMINIOS_EXCLUIDOS):
                        info['correo'] = candidato

            if info['correo']:
                print(f"   Email: {info['correo']}")

            # ── Teléfono ──────────────────────────────────────────────────────
            print("\n   === TELÉFONO ===")
            tel = re.search(
                r'(?:Tel[eéÉ]fono|Tel|Celular|M[oó]vil|Ext\.?)\s*:\s*([0-9\s\-\(\)+]+)',
                cuerpo, re.IGNORECASE
            )
            if tel:
                limpio = re.sub(r'[\s\-\(\)]', '', tel.group(1).strip())
                if len(limpio) >= 7 and limpio.isdigit():
                    info['telefono'] = limpio[:20]

            if not info['telefono']:
                m = re.search(r'\b(3\d{9})\b', cuerpo)
                if m:
                    info['telefono'] = m.group(1)

            if not info['telefono']:
                m = re.search(r'\b([2-8]\d{6})\b', cuerpo)
                if m:
                    info['telefono'] = m.group(1)

            print(f"   Teléfono: {info['telefono'] or '⚠️  Sin teléfono'}")

            # ── Municipio ─────────────────────────────────────────────────────
            mun = re.search(r'Municipio\s*:\s*([^\n]+)', cuerpo, re.IGNORECASE)
            if mun:
                municipio = self.limpiar_texto(mun.group(1))
                if municipio:
                    info['municipio'] = re.split(r'\s*[-–]\s*', municipio)[0][:100]
                    print(f"   Municipio: {info['municipio']}")

            # ── Dirección ─────────────────────────────────────────────────────
            print("\n   === DIRECCIÓN ===")
            dr = re.search(r'Direcci[oó]n\s*:\s*([^\n]+)', cuerpo, re.IGNORECASE)
            if dr:
                dir_texto = self.limpiar_texto(dr.group(1))
                if dir_texto:
                    info['direccion'] = dir_texto[:250]
                    print(f"   Dirección: {info['direccion']}")

            if not info['direccion']:
                print("   ⚠️  Sin dirección")

            # ── Número de participantes ───────────────────────────────────────
            trab = re.search(
                r'N[uúÚ]mero\s+de\s+'
                r'(?:trabajadores|funcionarios|beneficiarios|empleados|internos|participantes)'
                r'\s*:\s*([0-9]+)',
                cuerpo, re.IGNORECASE
            )
            if trab:
                n = int(trab.group(1))
                if n > 0:
                    info['numero_trabajadores'] = n
                    print(f"   Participantes: {n}")

            # ── Programa: buscar ficha SENA primero ───────────────────────────
            print("\n   === PROGRAMA ===")
            ficha = self.extraer_ficha_sena(cuerpo, asunto)
            if ficha and ficha.get('programa'):
                info['programa_solicitado'] = ficha['programa']
                print(f"   Programa (ficha {ficha['codigo']}): {info['programa_solicitado']}")

            if not info['programa_solicitado']:
                m = re.search(
                    r'(?:programa|formaci[oó]n|curso)\s+(?:de\s+)?([a-záéíóúñ\s]+)',
                    asunto.lower()
                )
                if m:
                    prog = self.limpiar_texto(m.group(1))
                    if prog:
                        info['programa_solicitado'] = re.sub(
                            r'\s+en\s+.*$', '', prog, flags=re.IGNORECASE
                        )
                        print(f"   Programa (asunto): {info['programa_solicitado']}")

            if not info['programa_solicitado']:
                m = re.search(
                    r'programa\s+de\s+formaci[oó]n\s+([A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)(?:\s+para|,|\.|\n)',
                    cuerpo, re.IGNORECASE
                )
                if m:
                    prog = self.limpiar_texto(m.group(1))
                    if prog:
                        info['programa_solicitado'] = prog
                        print(f"   Programa (texto): {prog}")

            if not info['programa_solicitado']:
                cuerpo_lower = cuerpo.lower()
                for keyword, nombre_prog in KEYWORDS_PROGRAMAS.items():
                    if keyword in cuerpo_lower:
                        info['programa_solicitado'] = nombre_prog
                        print(f"   Programa (keyword): {nombre_prog}")
                        break

            if not info['programa_solicitado']:
                print("   ⚠️  Sin programa identificado")

            # ── Resumen de lo extraído ────────────────────────────────────────
            print("\n   === RESUMEN EXTRACCIÓN ===")
            print(f"   Entidad:  {info['nombre']              or 'NO'}")
            print(f"   NIT:      {info['nit']                 or 'NO'}")
            print(f"   Contacto: {info['contacto']            or 'NO'}")
            print(f"   Teléfono: {info['telefono']            or 'NO'}")
            print(f"   Email:    {info['correo']              or 'NO'}")
            print(f"   Programa: {info['programa_solicitado'] or 'NO'}")

            return info

        except Exception as e:
            print(f"   ❌ Error en extracción: {e}")
            import traceback
            traceback.print_exc()
            return None

    def extraer_nombre_entidad(self, texto):
        """
        Intenta extraer el nombre de la empresa o institución del texto.

        Estrategia (en orden de prioridad):
            1. Campo explícito: "Nombre: Alcaldía de Tunja"
            2. Prefijo de institución: "Alcaldía de...", "Fundación...", etc.
            3. Sufijo jurídico: "Empresa X S.A.S", "Distribuidora Y LTDA"
            4. Fallback: texto en MAYÚSCULAS en las primeras líneas
        """
        # Estrategia 1: campo explícito
        campo = re.search(
            r'(?:Nombre|Entidad|Empresa|Institución|Institucion'
            r'|Organización|Organizacion)\s*:\s*([^\n]{5,150})',
            texto, re.IGNORECASE
        )
        if campo:
            candidato = self.limpiar_texto(campo.group(1))
            if candidato:
                print(f"   ✅ Nombre (campo explícito): {candidato}")
                return candidato[:200]

        # Estrategia 2: prefijo de institución pública
        patron_prefijo = (
            r'(?:' + '|'.join(PREFIJOS_INSTITUCION) + r')'
            r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ0-9\s\&\.\-]{2,80})'
        )
        prefijo = re.search(patron_prefijo, texto, re.IGNORECASE)
        if prefijo:
            nombre = self.limpiar_texto(prefijo.group(0))
            if nombre and len(nombre) > 5:
                print(f"   ✅ Nombre (institución): {nombre}")
                return nombre[:200]

        # Estrategia 3: sufijo jurídico de empresa privada
        patron_sufijo = (
            r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ0-9\s\&\.\,]{3,80}?)'
            r'\s*(?:' + '|'.join(SUFIJOS_EMPRESA) + r')'
        )
        sufijo = re.search(patron_sufijo, texto)
        if sufijo:
            nombre = self.limpiar_texto(sufijo.group(0))
            if nombre and len(nombre) > 5 and 'SENA' not in nombre.upper():
                print(f"   ✅ Nombre (empresa): {nombre}")
                return nombre[:200]

        # Estrategia 4: texto en MAYÚSCULAS en las primeras 8 líneas
        primeras = '\n'.join(texto.split('\n')[:8])
        mayus    = re.search(r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\&\.\,]{6,})', primeras)
        if mayus:
            candidato = self.limpiar_texto(mayus.group(1))
            ignorar   = {
                'SEÑORES', 'ESTIMADOS', 'BUENOS DIAS', 'BUENAS TARDES',
                'BUENAS NOCHES', 'CORDIALMENTE', 'ATENTAMENTE',
                'SENA', 'NIT', 'PERSONERIA JURIDICA',
            }
            if (candidato and len(candidato) > 8
                    and 'SENA' not in candidato
                    and candidato.upper().strip() not in ignorar):
                print(f"   ✅ Nombre (mayúsculas): {candidato}")
                return candidato[:200]

        print("   ⚠️  No se encontró nombre de entidad")
        return None

    def extraer_ficha_sena(self, cuerpo, asunto=''):
        """
        Busca un código de ficha SENA en el texto.
        Si lo encuentra, retorna el código y el nombre del programa asociado.

        Retorna dict con {codigo, programa} o None si no encuentra.
        """
        texto = f"{asunto} {cuerpo}".lower()

        for patron in PATRON_FICHA_SENA:
            m = re.search(patron, texto, re.IGNORECASE)
            if m:
                codigo   = m.group(1).strip()
                programa = FICHAS_SENA.get(codigo)
                print(f"   📋 Ficha SENA: {codigo}")
                if programa:
                    print(f"   ✅ → Programa: {programa}")
                return {'codigo': codigo, 'programa': programa}

        return None

    def extraer_de_plantilla(self, cuerpo):
        """
        Extrae datos cuando el correo usa la plantilla estructurada del sistema.
        La plantilla tiene formato "campo: valor" en cada línea.
        """
        info = {
            'nombre': None, 'nit': None, 'contacto': None,
            'correo': None, 'telefono': None, 'municipio': None,
            'direccion': None, 'numero_trabajadores': None,
            'programa_solicitado': None,
        }

        campos_map = {
            'nombre':       ('nombre', 150),
            'empresa':      ('nombre', 150),
            'entidad':      ('nombre', 150),
            'institución':  ('nombre', 150),
            'institucion':  ('nombre', 150),
            'nit':          ('nit', 20),
            'contacto':     ('contacto', 100),
            'responsable':  ('contacto', 100),
            'teléfono':     ('telefono', 20),
            'telefono':     ('telefono', 20),
            'celular':      ('telefono', 20),
            'correo':       ('correo', 150),
            'email':        ('correo', 150),
            'municipio':    ('municipio', 100),
            'ciudad':       ('municipio', 100),
            'dirección':    ('direccion', 250),
            'direccion':    ('direccion', 250),
            'programa':     ('programa_solicitado', 200),
            'curso':        ('programa_solicitado', 200),
            'capacitación': ('programa_solicitado', 200),
            'capacitacion': ('programa_solicitado', 200),
        }

        for linea in cuerpo.split('\n'):
            if ':' not in linea:
                continue

            clave_raw, _, valor_raw = linea.partition(':')
            clave = clave_raw.strip().lower().replace('*', '').replace('n°', '').strip()
            valor = valor_raw.strip().strip('[]').strip()

            if valor.startswith('[') or not valor or valor.lower() in ('', 'n/a', 'na'):
                continue

            if clave in campos_map:
                campo_destino, max_len = campos_map[clave]
                if not info[campo_destino]:
                    limpio = self.limpiar_texto(valor)
                    if limpio:
                        info[campo_destino] = limpio[:max_len]

        if info['nit']:
            info['nit'] = self.validar_nit(info['nit'])

        m = re.search(
            r'(?:aprendices|trabajadores|participantes|beneficiarios)\s*:\s*(\d+)',
            cuerpo, re.IGNORECASE
        )
        if m:
            n = int(m.group(1))
            if n > 0:
                info['numero_trabajadores'] = n

        print(f"   📋 Plantilla → Nombre: {info['nombre']} | Programa: {info['programa_solicitado']}")
        return info

    # =========================================================================
    # BASE DE DATOS — EMPRESA
    # =========================================================================

    @transaction.atomic
    def buscar_o_crear_empresa(self, info):
        """
        Busca la empresa en la base de datos o la crea si no existe.

        Orden de búsqueda:
            1. Por NIT (más confiable)
            2. Por nombre exacto
            3. Por correo electrónico
            4. Si no existe → crear nueva entrada

        Retorna (empresa, fue_creada: bool).
        """
        try:
            nombre = info.get('nombre')
            correo = info.get('correo')
            nit    = info.get('nit')

            if not nombre and not correo:
                print("   ❌ Sin nombre ni correo — no se puede crear empresa")
                return None, False

            # Búsqueda por NIT
            if nit:
                empresa = Empresa.objects.filter(nit=nit).first()
                if empresa:
                    print(f"   ✅ Empresa encontrada por NIT: {empresa.nombre}")
                    self._actualizar_empresa(empresa, info)
                    return empresa, False

            # Búsqueda por nombre exacto
            if nombre:
                qs = Empresa.objects.filter(nombre__iexact=nombre)
                if qs.exists():
                    if nit:
                        empresa = qs.filter(nit=nit).first()
                        if empresa:
                            print(f"   ✅ Empresa encontrada por nombre+NIT: {empresa.nombre}")
                            return empresa, False
                        print("   ⚠️  Mismo nombre pero NIT diferente → se creará nueva entrada")
                    else:
                        empresa = qs.first()
                        print(f"   ✅ Empresa encontrada por nombre: {empresa.nombre}")
                        self._actualizar_empresa(empresa, info)
                        return empresa, False

            # Búsqueda por correo
            if correo and '@ejemplo.com' not in correo:
                empresa = Empresa.objects.filter(correo__iexact=correo).first()
                if empresa:
                    print(f"   ✅ Empresa encontrada por correo: {empresa.nombre}")
                    self._actualizar_empresa(empresa, info)
                    return empresa, False

            # No se encontró → crear nueva empresa
            print("   🆕 Creando nueva empresa...")

            nombre_final = nombre if nombre else f"Entidad {(correo or '').split('@')[0]}"
            correo_final = correo if correo else (
                f"sin-correo-{timezone.now().timestamp()}@ejemplo.com"
            )

            if Empresa.objects.filter(nombre__iexact=nombre_final).exists():
                ts           = timezone.now().strftime('%Y%m%d-%H%M%S')
                nombre_final = f"{nombre_final} ({ts})"
                print(f"   ⚠️  Nombre duplicado → renombrando a: {nombre_final}")

            try:
                empresa = Empresa.objects.create(
                    nombre              = nombre_final[:200],
                    nit                 = nit or None,
                    contacto            = (info.get('contacto') or 'Sin contacto')[:100],
                    telefono            = (info.get('telefono') or '')[:20],
                    correo              = correo_final,
                    municipio           = (info.get('municipio') or '')[:100],
                    direccion           = (info.get('direccion') or '')[:250],
                    numero_trabajadores = info.get('numero_trabajadores') or 0,
                )
                print(f"   ✅ Empresa creada: {empresa.nombre}")
                return empresa, True

            except IntegrityError as e:
                print(f"   ❌ IntegrityError (posible concurrencia): {e}")
                if nit:
                    empresa = Empresa.objects.filter(nit=nit).first()
                    if empresa:
                        return empresa, False
                raise

        except Exception as e:
            print(f"   ❌ Error en buscar_o_crear_empresa: {e}")
            import traceback
            traceback.print_exc()
            return None, False

    def _actualizar_empresa(self, empresa, info):
        """
        Completa los campos vacíos de una empresa existente con datos nuevos.
        Solo actualiza campos que estén vacíos y el info tenga valor.
        """
        actualizado = False

        for campo, max_len in [('contacto', 100), ('telefono', 20),
                                ('municipio', 100), ('direccion', 250)]:
            if not getattr(empresa, campo, None) and info.get(campo):
                setattr(empresa, campo, info[campo][:max_len])
                actualizado = True

        if not getattr(empresa, 'correo', None) and info.get('correo'):
            empresa.correo = info['correo']
            actualizado    = True

        if (not getattr(empresa, 'numero_trabajadores', 0) or
                empresa.numero_trabajadores == 0) and info.get('numero_trabajadores'):
            empresa.numero_trabajadores = info['numero_trabajadores']
            actualizado = True

        if actualizado:
            empresa.save()
            print("   📝 Empresa actualizada con nuevos datos")

    # =========================================================================
    # BASE DE DATOS — PROGRAMA
    # =========================================================================

    def buscar_programa(self, nombre_programa):
        """
        Busca el programa más parecido al nombre solicitado en la base de datos.

        Algoritmo de puntuación:
            100 → coincidencia exacta
             90 → uno contiene al otro
             85 → score por tokens en común (cobertura promedio)
             +15 → bonus por tokens importantes (operador, excavadora, etc.)
             mínimo 35 puntos para considerarlo válido

        Usa normalizar_para_busqueda para manejar plurales y tildes.
        """
        try:
            if not nombre_programa:
                return None

            print(f"   Buscando programa: '{nombre_programa}'")

            nombre_norm = self.normalizar_para_busqueda(nombre_programa)
            tokens_busq = set(nombre_norm.split())
            programas   = Programa.objects.filter(activo=True)
            mejor       = None
            mejor_score = 0

            for programa in programas:
                prog_norm   = self.normalizar_para_busqueda(programa.nombre)
                tokens_prog = set(prog_norm.split())
                score       = 0

                if prog_norm == nombre_norm:
                    score = 100
                elif nombre_norm in prog_norm or prog_norm in nombre_norm:
                    score = 90
                else:
                    comunes = tokens_busq & tokens_prog
                    if comunes:
                        cob_b = len(comunes) / len(tokens_busq) if tokens_busq else 0
                        cob_p = len(comunes) / len(tokens_prog)  if tokens_prog  else 0
                        score = ((cob_b + cob_p) / 2) * 85

                        importantes = {
                            'sistemas', 'hidraulicos', 'maquinaria', 'pesada',
                            'operador', 'excavadora', 'retrocargador', 'montacargas',
                            'minicargador', 'interpretacion', 'planos',
                        }
                        imp_comunes = (tokens_busq & importantes) & (tokens_prog & importantes)
                        if imp_comunes:
                            imp_busq = tokens_busq & importantes
                            score    = min(
                                score + (len(imp_comunes) / len(imp_busq)) * 15
                                if imp_busq else score,
                                95
                            )

                if score > 30:
                    print(f"   Candidato: {programa.nombre} ({score:.0f}%)")

                if score > mejor_score:
                    mejor_score = score
                    mejor       = programa

            if mejor and mejor_score >= 35:
                print(f"   ✅ Programa encontrado: {mejor.nombre} ({mejor_score:.0f}%)")
                return mejor

            print(f"   ❌ No se encontró programa (mejor score: {mejor_score:.0f}%)")
            return None

        except Exception as e:
            print(f"   Error buscando programa: {e}")
            return None

    # =========================================================================
    # PROCESAMIENTO INDIVIDUAL DE CORREOS
    # =========================================================================

    def procesar_correo_individual(self, correo_info):
        """
        Procesa un correo y crea la solicitud en la base de datos.

        Pasos:
            1. Validar que el correo sea una solicitud
            2. Extraer datos (nombre, NIT, programa, etc.)
            3. Buscar o crear la empresa
            4. Buscar el programa
            5. Crear la solicitud
            6. Guardar los PDFs adjuntos

        Retorna la Solicitud creada, o None si hubo error.
        """
        try:
            asunto_corto = correo_info['asunto'][:50]
            print(f"\n{'='*60}\n📧 {asunto_corto}\n{'='*60}")

            # Paso 1: validar
            es_valido, razon = self.es_correo_valido(correo_info)
            if not es_valido:
                print(f"❌ FILTRADO: {razon}")
                self.stats['correos_filtrados'] += 1
                return None

            print(f"✅ {razon}")

            # Paso 2: extraer datos
            info = self.extraer_informacion_con_ia(correo_info)
            if not info:
                self.stats['errores'] += 1
                return None

            requiere_revision = info.pop('_requiere_revision_manual', False)
            razon_revision    = info.pop('_razon', '')

            # Paso 3: empresa
            empresa, _ = self.buscar_o_crear_empresa(info)
            if not empresa:
                self.stats['errores'] += 1
                return None

            # Paso 4: programa
            programa = None
            if info.get('programa_solicitado'):
                programa = self.buscar_programa(info['programa_solicitado'])

            if not programa and requiere_revision:
                print("   ⚠️  PDF escaneado sin programa — usando placeholder")
                programa = Programa.objects.filter(activo=True).first()
                if not programa:
                    print("❌ No hay programas activos en la base de datos")
                    self.stats['errores'] += 1
                    return None

            if not programa:
                print(f"❌ Programa no encontrado: {info.get('programa_solicitado')}")
                self.stats['errores'] += 1
                return None

            # Paso 5: crear solicitud
            if requiere_revision:
                observacion = (
                    f"⚠️ REVISIÓN MANUAL REQUERIDA\n"
                    f"Razón: {razon_revision}\n"
                    f"Asunto original: {asunto_corto}\n"
                    f"Completar datos manualmente en el panel de edición."
                )
                self.stats['revision_manual'] += 1
            else:
                observacion = f"Creada automáticamente desde correo: {asunto_corto}"

            solicitud = Solicitud.objects.create(
                empresa           = empresa,
                programa          = programa,
                estado            = 'RECIBIDA',
                fecha_recepcion   = timezone.now(),
                observaciones     = observacion,
                numero_aprendices = info.get('numero_trabajadores'),
                correo_remitente  = self._extraer_email_limpio(correo_info['remitente']),
            )

            # Paso 6: guardar PDFs adjuntos
            pdfs = correo_info.get('pdfs_adjuntos', [])
            if pdfs:
                print(f"\n   📄 Guardando {len(pdfs)} PDF(s)...")
                for idx, pdf in enumerate(pdfs, 1):
                    try:
                        ts       = timezone.now().strftime('%Y%m%d_%H%M%S')
                        n_limpio = re.sub(r'[^\w\s\-.]', '', pdf['nombre'])
                        n_final  = f"solicitud_{solicitud.id}_{ts}_{idx}_{n_limpio}"

                        DocumentoSolicitud.objects.create(
                            solicitud      = solicitud,
                            archivo        = ContentFile(pdf['contenido'], name=n_final),
                            nombre_archivo = pdf['nombre'],
                        )

                        if idx == 1:
                            solicitud.documento_pdf.save(
                                n_final, ContentFile(pdf['contenido']), save=True
                            )

                        print(f"   ✅ PDF #{idx}: {n_final}")
                        self.stats['pdfs_extraidos'] += 1

                    except Exception as e:
                        print(f"   ⚠️  Error guardando PDF #{idx}: {e}")

            estado_log = "⚠️ REVISIÓN MANUAL" if requiere_revision else "✅"
            print(f"\n{estado_log} SOLICITUD #{solicitud.id} → {empresa.nombre}")

            self.stats['solicitudes_creadas'] += 1
            self.stats['correos_procesados']  += 1
            return solicitud

        except Exception as e:
            print(f"❌ Error procesando correo: {e}")
            import traceback
            traceback.print_exc()
            self.stats['errores'] += 1
            return None

    # =========================================================================
    # PROCESAMIENTO EN LOTE
    # =========================================================================

    def procesar_correos(self, limite=20, procesar_en_paralelo=False, max_workers=3):
        """
        Lee y procesa todos los correos no leídos.

        Parámetros:
            limite               → máximo de correos a leer (None = sin límite)
            procesar_en_paralelo → usar ThreadPoolExecutor para mayor velocidad
            max_workers          → número de hilos si se usa procesamiento paralelo

        Retorna lista de Solicitudes creadas.
        """
        print("\n" + "="*60)
        print("🚀 INICIANDO PROCESAMIENTO DE CORREOS")
        print(f"   Límite: {limite} | Paralelo: {procesar_en_paralelo} | Workers: {max_workers}")
        print("="*60)

        self.stats = {k: 0 for k in self.stats}

        correos = self.leer_correos_no_leidos(limite=limite)
        if not correos:
            print("\n📭 No hay correos nuevos")
            return []

        solicitudes_creadas = []

        if procesar_en_paralelo and len(correos) > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self.procesar_correo_individual, c): c
                    for c in correos
                }
                for future in as_completed(futures):
                    try:
                        s = future.result()
                        if s:
                            solicitudes_creadas.append(s)
                    except Exception as e:
                        logger.error(f"Error en procesamiento paralelo: {e}")
        else:
            for idx, correo in enumerate(correos, 1):
                print(f"\n{'='*60}\nPROCESANDO {idx}/{len(correos)}\n{'='*60}")
                s = self.procesar_correo_individual(correo)
                if s:
                    solicitudes_creadas.append(s)

        self.mostrar_resumen()
        return solicitudes_creadas

    def mostrar_resumen(self):
        """Imprime el resumen estadístico del procesamiento."""
        print("\n" + "="*60 + "\n📊 RESUMEN DEL PROCESAMIENTO\n" + "="*60)

        for clave, valor in self.stats.items():
            print(f"   {clave}: {valor}")

        if self.stats['total_correos'] > 0:
            tasa = (self.stats['solicitudes_creadas'] / self.stats['total_correos']) * 100
            print(f"   tasa_exito: {tasa:.1f}%")

        if self.stats.get('revision_manual', 0) > 0:
            print(f"\n   ⚠️  {self.stats['revision_manual']} solicitud(es) requieren REVISIÓN MANUAL")
            print(f"      (PDF escaneado — completar datos en el panel de edición)")

        print("="*60)

    # =========================================================================
    # UTILIDADES ADICIONALES
    # =========================================================================

    def enviar_respuesta_automatica(self, empresa, solicitud, correo_info):
        """
        Envía un correo de confirmación a la empresa cuando se crea su solicitud.
        No es obligatorio — se puede llamar opcionalmente desde procesar_correo_individual.
        """
        try:
            asunto  = "RE: " + correo_info['asunto']
            mensaje = (
                f"Estimado/a {empresa.contacto},\n\n"
                f"Hemos recibido su solicitud de formación.\n\n"
                f"- Solicitud #: {solicitud.id}\n"
                f"- Entidad: {empresa.nombre}\n"
                f"- Programa: {solicitud.programa.nombre}\n"
                f"- Estado: Recibida\n\n"
                f"Nos comunicaremos pronto.\n\n"
                f"Cordialmente,\nSENA - Coordinación de Formación Empresarial"
            )
            m    = re.search(r'[\w\.-]+@[\w\.-]+', correo_info['remitente'])
            dest = m.group(0) if m else empresa.correo

            if dest and '@ejemplo.com' not in dest:
                send_mail(
                    subject        = asunto,
                    message        = mensaje,
                    from_email     = settings.EMAIL_HOST_USER,
                    recipient_list = [dest],
                    fail_silently  = False,
                )
                print(f"   ✅ Respuesta automática enviada a: {dest}")

        except Exception as e:
            print(f"   ❌ Error enviando respuesta automática: {e}")

    def marcar_como_leido(self, email_id):
        """
        Marca un correo como leído en el servidor IMAP.
        Se puede llamar después de procesar exitosamente un correo.
        """
        try:
            mail = self.conectar_email()
            if mail:
                mail.select('INBOX')
                mail.store(email_id, '+FLAGS', '\\Seen')
                mail.close()
                mail.logout()
                return True
        except Exception as e:
            print(f"⚠️  Error marcando como leído: {e}")
        return False

    def _extraer_email_limpio(self, remitente):
        """
        Extrae solo la dirección de correo de un campo 'From' completo.
        Ejemplo: '"Juan Pérez" <juan@empresa.com>' → 'juan@empresa.com'
        """
        try:
            m = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', remitente)
            return m.group(0).lower() if m else None
        except Exception:
            return None