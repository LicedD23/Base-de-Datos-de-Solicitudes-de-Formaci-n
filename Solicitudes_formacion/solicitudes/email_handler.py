import imaplib
import email
from email.header import decode_header
import re
from datetime import datetime
import json
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

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


class EmailSolicitudHandler:
    """
    Manejador de correos para solicitudes de formación.

    CAMBIOS v2:
    - Acepta correos con asunto válido + PDF adjunto aunque el cuerpo sea corto
    - Extrae texto del PDF adjunto con pdfplumber cuando el cuerpo es insuficiente
    - Si el PDF no tiene texto (escaneado), crea la solicitud con datos mínimos
      y la marca para revisión manual en lugar de descartarla

    Reconoce como 'empresa' (igual que S.A.S o LTDA) a:
      - Empresas privadas (S.A.S, LTDA, S.A, EU, SAS, S.C.A...)
      - Alcaldías y gobernaciones
      - INPEC y establecimientos penitenciarios
      - Instituciones educativas (colegios, escuelas, liceos)
      - Fundaciones, corporaciones, asociaciones, ONG
      - Entidades públicas (ministerios, hospitales, superintendencias...)
    """

    # =========================================================================
    # FILTROS DE ENTRADA
    # =========================================================================

    PALABRAS_CLAVE_ASUNTO = [
        'solicitud', 'formación', 'formacion', 'capacitación', 'capacitacion',
        'programa', 'curso', 'entrenamiento', 'sena', 'ficha', 'convenio',
        # ⭐ NUEVO: frases compuestas que las empresas usan con frecuencia
        'solicitud de formacion', 'solicitud de formación',
        'solicitud de capacitacion', 'solicitud de capacitación',
        'solicitud curso', 'solicitud de curso',
        'solicitud sena', 'solicitud de programa',
        'apoyo', 'placa', 'proyecto',  # Para casos como "Solicitud Apoyo Proyecto..."
    ]

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
        # ⭐ NUEVO: palabras que aparecen en cuerpos cortos pero válidos
        'adjunto', 'oficio', 'documento', 'solicitud',
    ]

    DOMINIOS_EXCLUIDOS = [
        'noreply', 'no-reply', 'mailer-daemon', 'postmaster',
        'notification', 'marketing', 'newsletter',
    ]

    CAMPOS_MINIMOS_REQUERIDOS = 2
    MAX_PDF_SIZE = 10 * 1024 * 1024
    MAX_PDFS_PER_EMAIL = 5

    # ⭐ NUEVO: umbral para considerar que el cuerpo es "demasiado corto"
    # y hay que buscar los datos en el PDF adjunto
    CUERPO_MINIMO_CHARS = 150

    # =========================================================================
    # IDENTIFICADORES DE ENTIDAD
    # =========================================================================

    SUFIJOS_EMPRESA = [
        r'S\.A\.S\.?', r'\bSAS\b', r'S\.A\.', r'\bSA\b',
        r'LTDA\.?', r'\bEU\b', r'E\.U\.?',
        r'S\.C\.A\.?', r'S\.C\.S\.?', r'S\s+EN\s+C',
    ]

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
        # ⭐ NUEVO: Junta de Acción Comunal (caso real de la imagen)
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

    # =========================================================================
    # KEYWORDS PARA PROGRAMAS
    # =========================================================================

    KEYWORDS_PROGRAMAS = {
        'minicargador': 'Operador de Minicargador',
        'mini cargador': 'Operador de Minicargador',
        'montacargas': 'Operador de Montacargas',
        'excavadora': 'Operador de Excavadora',
        'retrocargador': 'Operador de Retrocargador',
        'interpretacion de planos': 'Interpretación de planos para maquinaria industrial',
        'interpretación de planos': 'Interpretación de planos para maquinaria industrial',
        'planos maquinaria': 'Interpretación de planos para maquinaria industrial',
        'lectura de planos': 'Interpretación de planos para maquinaria industrial',
        # ⭐ NUEVO: programa que aparece en el caso real de la imagen
        'placas huellas': 'Placas Huellas',
        'placa huella': 'Placas Huellas',
    }

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

    PATRON_FICHA_SENA = [
        r'ficha\s*(?:sena)?\s*[:\-]?\s*(\d{5,10})',
        r'c[oó]digo\s+de\s+ficha\s*[:\-]?\s*(\d{5,10})',
        r'ficha\s+de\s+caracterizaci[oó]n\s*[:\-]?\s*(\d{5,10})',
        r'n[uú]mero\s+de\s+ficha\s*[:\-]?\s*(\d{5,10})',
    ]

    def __init__(self):
        self.imap_server    = getattr(settings, 'IMAP_HOST', 'imap.gmail.com')
        self.imap_port      = getattr(settings, 'IMAP_PORT', 993)
        self.email_account  = getattr(settings, 'IMAP_USER', settings.EMAIL_HOST_USER)
        self.email_password = getattr(settings, 'IMAP_PASSWORD', settings.EMAIL_HOST_PASSWORD)

        self.stats = {
            'total_correos': 0, 'correos_filtrados': 0,
            'correos_procesados': 0, 'solicitudes_creadas': 0,
            'pdfs_extraidos': 0, 'errores': 0,
            # ⭐ NUEVO: contador de solicitudes creadas desde PDF
            'creadas_desde_pdf': 0,
            'revision_manual': 0,
        }

        print(f"🔧 IMAP: {self.imap_server}:{self.imap_port}")
        print(f"📧 Cuenta: {self.email_account}")

    # =========================================================================
    # ⭐ NUEVO — EXTRACCIÓN DE TEXTO DESDE PDF
    # Este método es el corazón del cambio. Lee el PDF en memoria (sin guardar
    # en disco) y devuelve su texto plano para que el resto del handler lo
    # procese igual que si viniera en el cuerpo del correo.
    # =========================================================================

    def extraer_texto_pdf(self, pdf_bytes):
        """
        Extrae texto plano de un PDF en memoria usando pdfplumber.

        ¿Por qué pdfplumber y no PyPDF2?
        - pdfplumber maneja mejor PDFs con tablas y columnas
        - Preserva mejor el orden de lectura del texto
        - Más tolerante con PDFs mal formados

        Retorna:
            str con el texto extraído, o None si el PDF es una imagen escaneada
            o si pdfplumber no está instalado.
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
                    print(f"   ✅ PDF: {len(texto_total)} caracteres totales extraídos")
                    return texto_total
                else:
                    print("   ⚠️  PDF sin texto extraíble — es un documento escaneado (imagen)")
                    return None

        except ImportError:
            print("   ❌ pdfplumber no instalado. Ejecuta: pip install pdfplumber")
            return None
        except Exception as e:
            print(f"   ⚠️  Error leyendo PDF: {e}")
            return None

    # =========================================================================
    # EXTRACCIÓN DEL NOMBRE DE ENTIDAD
    # =========================================================================

    def extraer_nombre_entidad(self, texto):
        """
        Extrae el nombre de la entidad del texto (cuerpo del correo o PDF).
        Sin cambios en la lógica — ahora también recibe texto extraído de PDFs.
        """
        # --- 1. Campo explícito ---
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

        # --- 2. Prefijo de institución ---
        patron_prefijo = (
            r'(?:' + '|'.join(self.PREFIJOS_INSTITUCION) + r')'
            r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ0-9\s\&\.\-]{2,80})'
        )
        prefijo = re.search(patron_prefijo, texto, re.IGNORECASE)
        if prefijo:
            nombre_completo = self.limpiar_texto(prefijo.group(0))
            if nombre_completo and len(nombre_completo) > 5:
                print(f"   ✅ Nombre (institución): {nombre_completo}")
                return nombre_completo[:200]

        # --- 3. Sufijo jurídico de empresa ---
        patron_sufijo = (
            r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ0-9\s\&\.\,]{3,80}?)'
            r'\s*(?:' + '|'.join(self.SUFIJOS_EMPRESA) + r')'
        )
        sufijo = re.search(patron_sufijo, texto)
        if sufijo:
            nombre_completo = self.limpiar_texto(sufijo.group(0))
            if nombre_completo and len(nombre_completo) > 5 and 'SENA' not in nombre_completo.upper():
                print(f"   ✅ Nombre (empresa): {nombre_completo}")
                return nombre_completo[:200]

        # --- 4. Fallback: mayúsculas en primeras líneas ---
        primeras = '\n'.join(texto.split('\n')[:8])
        mayus = re.search(r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\&\.\,]{6,})', primeras)
        if mayus:
            candidato = self.limpiar_texto(mayus.group(1))
            ignorar = {'SEÑORES', 'ESTIMADOS', 'BUENOS DIAS', 'BUENAS TARDES',
                       'BUENAS NOCHES', 'CORDIALMENTE', 'ATENTAMENTE',
                       'SENA', 'NIT', 'PERSONERIA JURIDICA'}
            if (candidato and len(candidato) > 8
                    and 'SENA' not in candidato
                    and candidato.upper().strip() not in ignorar):
                print(f"   ✅ Nombre (mayúsculas): {candidato}")
                return candidato[:200]

        print("   ⚠️  No se encontró nombre de entidad")
        return None

    # =========================================================================
    # FICHA SENA
    # =========================================================================

    def extraer_ficha_sena(self, cuerpo, asunto=''):
        texto = f"{asunto} {cuerpo}".lower()
        for patron in self.PATRON_FICHA_SENA:
            m = re.search(patron, texto, re.IGNORECASE)
            if m:
                codigo = m.group(1).strip()
                print(f"   📋 Ficha SENA: {codigo}")
                programa = self.FICHAS_SENA.get(codigo)
                if programa:
                    print(f"   ✅ → Programa: {programa}")
                return {'codigo': codigo, 'programa': programa}
        return None

    # =========================================================================
    # CONEXIÓN Y LECTURA
    # =========================================================================

    def extraer_pdfs_adjuntos(self, msg):
        pdfs = []
        try:
            print("\n   === BUSCANDO PDFs ===")
            if not msg.is_multipart():
                print("   ℹ️  Sin adjuntos")
                return pdfs

            for part in msg.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                if part.get('Content-Disposition') is None:
                    continue

                filename = part.get_filename()
                if not filename:
                    continue

                if isinstance(filename, bytes):
                    filename = filename.decode('utf-8', errors='ignore')
                else:
                    partes = decode_header(filename)
                    filename = ''.join(
                        p.decode(enc or 'utf-8', errors='ignore') if isinstance(p, bytes) else p
                        for p, enc in partes
                    )

                if not filename.lower().endswith('.pdf'):
                    continue

                data = part.get_payload(decode=True)
                if not data:
                    continue

                size = len(data)
                if size > self.MAX_PDF_SIZE:
                    print(f"   ⚠️  '{filename}' supera límite - OMITIDO")
                    continue
                if not data.startswith(b'%PDF'):
                    print(f"   ⚠️  '{filename}' no es PDF válido - OMITIDO")
                    continue
                if len(pdfs) >= self.MAX_PDFS_PER_EMAIL:
                    print(f"   ⚠️  Límite de PDFs alcanzado - OMITIDO")
                    continue

                print(f"   ✅ PDF #{len(pdfs)+1}: {filename} ({size/1024:.1f} KB)")
                pdfs.append({'nombre': filename, 'contenido': data, 'size': size})

            print(f"   📄 Total PDFs: {len(pdfs)}")
            return pdfs
        except Exception as e:
            print(f"   ❌ Error extrayendo PDFs: {e}")
            return pdfs

    def conectar_email(self):
        try:
            if not self.email_account or not self.email_password:
                print("❌ Credenciales no configuradas")
                return None
            print(f"🔌 Conectando a {self.imap_server}:{self.imap_port}")
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_account, self.email_password)
            print(f"✅ Conectado: {self.email_account}")
            return mail
        except imaplib.IMAP4.error as e:
            print(f"❌ Error autenticación: {e}")
            return None
        except Exception as e:
            print(f"❌ Error conexión: {e}")
            return None

    def leer_correos_no_leidos(self, limite=20):
        mail = self.conectar_email()
        if not mail:
            return []
        try:
            status, _ = mail.select('INBOX')
            if status != 'OK':
                return []
            status, data = mail.search(None, 'UNSEEN')
            if status != 'OK':
                return []

            email_ids = data[0].split()
            self.stats['total_correos'] = len(email_ids)
            print(f"\n📬 Correos no leídos: {len(email_ids)}")

            if not email_ids:
                return []
            if limite and len(email_ids) > limite:
                print(f"⚠️  Límite: procesando {limite} de {len(email_ids)}")
                email_ids = email_ids[:limite]

            correos = []
            for idx, eid in enumerate(email_ids, 1):
                try:
                    print(f"\n{'='*60}\n📨 Correo {idx}/{len(email_ids)}\n{'='*60}")
                    status, msg_data = mail.fetch(eid, '(RFC822)')
                    if status != 'OK':
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    info = self.parsear_correo(msg)
                    if info:
                        info['email_id'] = eid
                        correos.append(info)
                except Exception as e:
                    print(f"⚠️  Error correo {idx}: {e}")
                    continue

            mail.close()
            mail.logout()
            return correos
        except Exception as e:
            print(f"❌ Error leyendo: {e}")
            return []

    def parsear_correo(self, msg):
        try:
            subject = ''
            if msg['Subject']:
                raw = decode_header(msg['Subject'])[0]
                subject = raw[0].decode(raw[1] or 'utf-8', errors='ignore') \
                    if isinstance(raw[0], bytes) else raw[0]

            from_email = msg.get('From', '')
            body = ''

            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode('utf-8', errors='ignore')
                                break
                        except:
                            pass
            else:
                try:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode('utf-8', errors='ignore')
                except:
                    pass

            return {
                'asunto': subject,
                'remitente': from_email,
                'cuerpo': body,
                'fecha': msg.get('Date', ''),
                'pdfs_adjuntos': self.extraer_pdfs_adjuntos(msg),
            }
        except Exception as e:
            print(f"❌ Error parseando: {e}")
            return None

    # =========================================================================
    # ⭐ FILTRADO — CAMBIO PRINCIPAL
    #
    # LÓGICA ANTERIOR:
    #   El correo debía tener cuerpo largo + palabras clave + campos extraíbles.
    #   Si el cuerpo era corto → RECHAZADO aunque traía PDF con todos los datos.
    #
    # LÓGICA NUEVA:
    #   PUERTA 1 (nueva): asunto válido + PDF adjunto → ACEPTADO directamente.
    #   PUERTA 2 (nueva): asunto válido + cuerpo con plantilla estructurada → ACEPTADO.
    #   PUERTA 3 (original): validación completa del cuerpo libre.
    #
    # Esto significa que el correo de la Junta de Acción Comunal (asunto:
    # "Solicitud Apoyo Proyecto PLACA HUELLA", cuerpo de 4 líneas, PDF adjunto)
    # ahora entra por la PUERTA 1 y llega a extraer_informacion_con_ia().
    # =========================================================================

    def es_correo_valido(self, correo_info):
        """Determina si el correo es una solicitud válida."""
        try:
            asunto    = correo_info.get('asunto', '').lower()
            cuerpo    = correo_info.get('cuerpo', '')
            remitente = correo_info.get('remitente', '').lower()
            pdfs      = correo_info.get('pdfs_adjuntos', [])
            tiene_pdf = len(pdfs) > 0  # ⭐ NUEVO

            # --- Dominios excluidos (sin cambios) ---
            for dom in self.DOMINIOS_EXCLUIDOS:
                if dom in remitente:
                    return False, f"Dominio excluido: {dom}"

            # --- Asunto sigue siendo obligatorio ---
            if not any(p in asunto for p in self.PALABRAS_CLAVE_ASUNTO):
                return False, "Sin palabras clave en asunto"

            # ⭐ PUERTA 1 — NUEVA:
            # Si el asunto es válido Y hay PDF adjunto → aceptar sin revisar el cuerpo.
            # Los datos vendrán del PDF. No importa si el cuerpo tiene 4 líneas.
            if tiene_pdf:
                print(f"   ✅ PUERTA 1: Asunto válido + {len(pdfs)} PDF(s) adjunto(s) → aceptado")
                return True, f"Correo con asunto válido y {len(pdfs)} PDF adjunto(s)"

            # ⭐ PUERTA 2 — NUEVA:
            # Cuerpo con plantilla estructurada (etiquetas Nombre:, NIT:, etc.)
            if self.es_correo_plantilla(cuerpo):
                print("   ✅ PUERTA 2: Plantilla estructurada detectada → aceptado")
                return True, "Correo con plantilla estructurada"

            # --- PUERTA 3 — ORIGINAL: validación completa del cuerpo libre ---
            cuerpo_lower = cuerpo.lower()
            encontradas = sum(1 for p in self.PALABRAS_CLAVE_CUERPO if p in cuerpo_lower)
            if encontradas < 2:
                return False, f"Solo {encontradas} palabras clave en cuerpo (mínimo 2)"

            if len(cuerpo) < 100:
                return False, f"Cuerpo muy corto ({len(cuerpo)} chars) y sin PDF adjunto"

            info = self.extraer_informacion_con_ia(correo_info)
            if not info:
                return False, "No se pudo extraer información"

            campos = sum([
                1 if info.get('nombre') else 0,
                1 if info.get('programa_solicitado') else 0,
                1 if info.get('correo') else 0,
                1 if info.get('telefono') else 0,
            ])
            if campos < self.CAMPOS_MINIMOS_REQUERIDOS:
                return False, f"Campos insuficientes ({campos}/{self.CAMPOS_MINIMOS_REQUERIDOS})"

            return True, "Correo válido (cuerpo completo)"
        except Exception as e:
            return False, f"Error en validación: {e}"

    # =========================================================================
    # ⭐ NUEVO — DETECCIÓN DE PLANTILLA ESTRUCTURADA
    # =========================================================================

    CAMPOS_PLANTILLA = [
        'nombre', 'nit', 'contacto', 'teléfono', 'telefono',
        'programa', 'aprendices', 'correo', 'email', 'empresa', 'entidad',
    ]

    def es_correo_plantilla(self, cuerpo):
        """
        Detecta si el correo usa la plantilla estructurada del sistema.
        Retorna True si tiene al menos 3 etiquetas conocidas (campo: valor).
        """
        cuerpo_lower = cuerpo.lower()
        encontrados = sum(1 for campo in self.CAMPOS_PLANTILLA if f'{campo}:' in cuerpo_lower)
        return encontrados >= 3

    def extraer_de_plantilla(self, cuerpo):
        """Extrae datos directamente desde la plantilla estructurada."""
        info = {
            'nombre': None, 'nit': None, 'contacto': None,
            'correo': None, 'telefono': None, 'municipio': None,
            'direccion': None, 'numero_trabajadores': None,
            'programa_solicitado': None,
        }

        campos_map = {
            'nombre'       : ('nombre', 150),
            'empresa'      : ('nombre', 150),
            'entidad'      : ('nombre', 150),
            'institución'  : ('nombre', 150),
            'institucion'  : ('nombre', 150),
            'nit'          : ('nit', 20),
            'contacto'     : ('contacto', 100),
            'responsable'  : ('contacto', 100),
            'teléfono'     : ('telefono', 20),
            'telefono'     : ('telefono', 20),
            'celular'      : ('telefono', 20),
            'correo'       : ('correo', 150),
            'email'        : ('correo', 150),
            'municipio'    : ('municipio', 100),
            'ciudad'       : ('municipio', 100),
            'dirección'    : ('direccion', 250),
            'direccion'    : ('direccion', 250),
            'programa'     : ('programa_solicitado', 200),
            'curso'        : ('programa_solicitado', 200),
            'capacitación' : ('programa_solicitado', 200),
            'capacitacion' : ('programa_solicitado', 200),
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
    # UTILIDADES DE TEXTO
    # =========================================================================

    def limpiar_texto(self, texto):
        if not texto:
            return None
        texto = texto.replace('*', '')
        texto = re.sub(r'\s+', ' ', texto).strip()
        if not texto or texto.lower() in ('sin especificar', 'no especificado', 'n/a', 'na'):
            return None
        return texto

    def validar_nit(self, nit):
        if not nit:
            return None
        limpio = nit.replace(' ', '').replace('-', '').replace('.', '')
        if not limpio.isdigit():
            return None
        if not (8 <= len(limpio) <= 12):
            return None
        if limpio.startswith('3') and len(limpio) == 10:
            print(f"   ⚠️  Parece celular, no NIT: {limpio}")
            return None
        print(f"   ✅ NIT: {limpio}")
        return limpio

    def normalizar_texto(self, texto):
        if not texto:
            return ''
        texto = texto.lower()
        texto = ''.join(
            c for c in unicodedata.normalize('NFD', texto)
            if unicodedata.category(c) != 'Mn'
        )
        texto = re.sub(r'[^a-z0-9\s]', '', texto)
        return re.sub(r'\s+', ' ', texto).strip()

    def normalizar_para_busqueda(self, texto):
        """
        Normalización avanzada para búsqueda de programas.

        Además de quitar tildes y pasar a minúsculas, elimina plurales
        simples del español para que:
          'minicargadores' encuentre 'minicargador'
          'placas huellas' encuentre 'placa huella'
          'operadores'     encuentre 'operador'
          'excavadoras'    encuentre 'excavadora'

        Esto evita agregar keywords manuales para cada variante de nombre.
        Funciona igual para correos con cuerpo largo, plantilla o PDF adjunto.
        """
        if not texto:
            return ''
        # Paso 1: quitar tildes y pasar a minúsculas
        texto = texto.lower()
        texto = ''.join(
            c for c in unicodedata.normalize('NFD', texto)
            if unicodedata.category(c) != 'Mn'
        )
        texto = re.sub(r'[^a-z0-9\s]', '', texto)
        texto = re.sub(r'\s+', ' ', texto).strip()

        # Paso 2: normalizar plurales token por token
        tokens_normalizados = []
        for token in texto.split():
            if len(token) > 4 and token.endswith('es'):
                # 'operadores' → 'operador', 'excavadoras' NO entra aquí
                token = token[:-2]
            elif len(token) > 3 and token.endswith('s'):
                # 'placas' → 'placa', 'huellas' → 'huella', 'planos' → 'plano'
                token = token[:-1]
            tokens_normalizados.append(token)

        return ' '.join(tokens_normalizados)

    # =========================================================================
    # ⭐ EXTRACCIÓN DE INFORMACIÓN — CAMBIO PRINCIPAL #2
    #
    # LÓGICA ANTERIOR:
    #   Solo analizaba el cuerpo del correo.
    #
    # LÓGICA NUEVA (3 niveles de prioridad):
    #   NIVEL 1: ¿Cuerpo tiene plantilla estructurada? → extraer_de_plantilla()
    #   NIVEL 2: ¿Cuerpo es corto pero hay PDF? → extraer_texto_pdf() y reusar
    #            este mismo método con el texto del PDF como "cuerpo enriquecido"
    #   NIVEL 3: Comportamiento original (cuerpo libre largo)
    # =========================================================================

    def extraer_informacion_con_ia(self, correo_info):
        """Extrae todos los datos del correo."""
        try:
            cuerpo    = correo_info.get('cuerpo', '')
            remitente = correo_info.get('remitente', '')
            asunto    = correo_info.get('asunto', '')

            if not cuerpo and not correo_info.get('pdfs_adjuntos'):
                return None

            print("   Extrayendo información...")

            # ------------------------------------------------------------------
            # ⭐ NIVEL 1: Plantilla estructurada en el cuerpo del correo
            # ------------------------------------------------------------------
            if self.es_correo_plantilla(cuerpo):
                print("   ✅ NIVEL 1: Plantilla estructurada detectada en cuerpo")
                info = self.extraer_de_plantilla(cuerpo)
                if not info['correo']:
                    m = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', remitente)
                    if m:
                        candidato = m.group(1).strip().lower()
                        if not any(d in candidato for d in self.DOMINIOS_EXCLUIDOS):
                            info['correo'] = candidato
                return info

            # ------------------------------------------------------------------
            # ⭐ NIVEL 2: Cuerpo corto → intentar extraer datos del PDF adjunto
            #
            # ¿Cuándo entra aquí?
            # - El correo tiene asunto válido (pasó es_correo_valido PUERTA 1)
            # - El cuerpo tiene menos de CUERPO_MINIMO_CHARS (150) caracteres
            # - Hay al menos un PDF adjunto
            #
            # ¿Qué hace?
            # - Lee el primer PDF con pdfplumber
            # - Si extrae texto: lo "pega" al cuerpo original y relanza la
            #   extracción. El texto del PDF ya tiene NIT, nombre, teléfono, etc.
            # - Si NO extrae texto (PDF escaneado): crea info mínima con lo que
            #   hay en el asunto y el remitente, y pone una observación para
            #   revisión manual. NO descarta el correo.
            # ------------------------------------------------------------------
            pdfs = correo_info.get('pdfs_adjuntos', [])
            cuerpo_es_corto = len(cuerpo.strip()) < self.CUERPO_MINIMO_CHARS

            if cuerpo_es_corto and pdfs:
                print(f"\n   === NIVEL 2: Cuerpo corto ({len(cuerpo.strip())} chars) + PDF adjunto ===")
                print(f"   📄 Intentando extraer texto del PDF: {pdfs[0]['nombre']}")

                texto_pdf = self.extraer_texto_pdf(pdfs[0]['contenido'])

                if texto_pdf:
                    # ✅ PDF con texto: combinar PDF + cuerpo original y relanzar
                    print("   ✅ Texto extraído del PDF — relanzando extracción con texto enriquecido")
                    cuerpo_enriquecido = texto_pdf + '\n\n--- CUERPO CORREO ---\n' + cuerpo
                    correo_enriquecido = dict(correo_info)
                    correo_enriquecido['cuerpo'] = cuerpo_enriquecido
                    # ⚠️ Evitar recursión infinita: el cuerpo enriquecido
                    # ya tiene más de CUERPO_MINIMO_CHARS, así que no volverá
                    # a entrar en este bloque NIVEL 2
                    return self.extraer_informacion_con_ia(correo_enriquecido)

                else:
                    # ⚠️ PDF escaneado (imagen): crear info mínima para no perder el correo
                    print("   ⚠️  PDF escaneado — creando solicitud mínima para revisión manual")
                    info_minima = {
                        'nombre': None, 'nit': None, 'contacto': None,
                        'correo': None, 'telefono': None, 'municipio': None,
                        'direccion': None, 'numero_trabajadores': None,
                        'programa_solicitado': None,
                        # ⭐ Bandera especial para que procesar_correo_individual
                        # sepa que esta solicitud necesita revisión manual
                        '_requiere_revision_manual': True,
                        '_razon': 'PDF adjunto es imagen escaneada, no se pudo extraer texto',
                    }

                    # Intentar sacar programa del asunto
                    for keyword, nombre_prog in self.KEYWORDS_PROGRAMAS.items():
                        if keyword in asunto.lower():
                            info_minima['programa_solicitado'] = nombre_prog
                            print(f"   Programa (asunto): {nombre_prog}")
                            break

                    # Sacar correo del remitente
                    m = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', remitente)
                    if m:
                        candidato = m.group(1).strip().lower()
                        if not any(d in candidato for d in self.DOMINIOS_EXCLUIDOS):
                            info_minima['correo'] = candidato

                    return info_minima

            # ------------------------------------------------------------------
            # NIVEL 3: Comportamiento original — cuerpo libre largo
            # (sin cambios respecto a la versión anterior)
            # ------------------------------------------------------------------
            print("   NIVEL 3: Extracción desde cuerpo libre")

            info = {
                'nombre': None, 'nit': None, 'contacto': None,
                'correo': None, 'telefono': None, 'municipio': None,
                'direccion': None, 'numero_trabajadores': None,
                'programa_solicitado': None,
            }

            # --- NOMBRE ---
            print("\n   === NOMBRE DE ENTIDAD ===")
            info['nombre'] = self.extraer_nombre_entidad(cuerpo)

            # --- NIT ---
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

            # --- CONTACTO ---
            cont = re.search(
                r'(?:Contacto|Representante|Funcionario|Responsable)\s*:\s*([^\n]+)',
                cuerpo, re.IGNORECASE
            )
            if cont:
                contacto = self.limpiar_texto(cont.group(1))
                if contacto:
                    contacto = re.sub(r'^Nombre:\s*', '', contacto, flags=re.IGNORECASE).strip()
                    info['contacto'] = contacto[:100]
                    print(f"   Contacto: {info['contacto']}")

            # --- EMAIL ---
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
                    if not any(d in candidato for d in self.DOMINIOS_EXCLUIDOS):
                        info['correo'] = candidato

            if info['correo']:
                print(f"   Email: {info['correo']}")

            # --- TELÉFONO ---
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

            # --- MUNICIPIO ---
            mun = re.search(r'Municipio\s*:\s*([^\n]+)', cuerpo, re.IGNORECASE)
            if mun:
                municipio = self.limpiar_texto(mun.group(1))
                if municipio:
                    info['municipio'] = re.split(r'\s*[-–]\s*', municipio)[0][:100]
                    print(f"   Municipio: {info['municipio']}")

            # --- DIRECCIÓN ---
            print("\n   === DIRECCIÓN ===")
            dr = re.search(r'Direcci[oó]n\s*:\s*([^\n]+)', cuerpo, re.IGNORECASE)
            if dr:
                dir_texto = self.limpiar_texto(dr.group(1))
                if dir_texto:
                    info['direccion'] = dir_texto[:250]
                    print(f"   Dirección: {info['direccion']}")
            if not info['direccion']:
                print("   ⚠️  Sin dirección")

            # --- PARTICIPANTES ---
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

            # --- FICHA SENA ---
            print("\n   === FICHA SENA ===")
            ficha = self.extraer_ficha_sena(cuerpo, asunto)
            if ficha and ficha.get('programa'):
                info['programa_solicitado'] = ficha['programa']
                print(f"   Programa (ficha {ficha['codigo']}): {info['programa_solicitado']}")

            # --- PROGRAMA ---
            if not info['programa_solicitado']:
                print("\n   === PROGRAMA ===")
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
                    r'programa\s+de\s+formaci[oó]n\s+'
                    r'([A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)(?:\s+para|,|\.|\n)',
                    cuerpo, re.IGNORECASE
                )
                if m:
                    prog = self.limpiar_texto(m.group(1))
                    if prog:
                        info['programa_solicitado'] = prog
                        print(f"   Programa (texto): {prog}")

            if not info['programa_solicitado']:
                cuerpo_lower = cuerpo.lower()
                for keyword, nombre_prog in self.KEYWORDS_PROGRAMAS.items():
                    if keyword in cuerpo_lower:
                        info['programa_solicitado'] = nombre_prog
                        print(f"   Programa (keyword): {nombre_prog}")
                        break

            if not info['programa_solicitado']:
                print("   ⚠️  Sin programa")

            # --- RESUMEN ---
            print("\n   === RESUMEN ===")
            print(f"   Entidad:  {info['nombre'] or 'NO'}")
            print(f"   NIT:      {info['nit'] or 'NO'}")
            print(f"   Contacto: {info['contacto'] or 'NO'}")
            print(f"   Teléfono: {info['telefono'] or 'NO'}")
            print(f"   Email:    {info['correo'] or 'NO'}")
            print(f"   Programa: {info['programa_solicitado'] or 'NO'}")
            print("   " + "="*50)

            return info

        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    # =========================================================================
    # BUSCAR O CREAR EMPRESA
    # =========================================================================

    @transaction.atomic
    def buscar_o_crear_empresa(self, info):
        try:
            nombre = info.get('nombre')
            correo = info.get('correo')
            nit    = info.get('nit')

            if not nombre and not correo:
                print("   ❌ Sin nombre ni correo")
                return None, False

            if nit:
                empresa = Empresa.objects.filter(nit=nit).first()
                if empresa:
                    print(f"   ✅ Encontrada por NIT: {empresa.nombre}")
                    self._actualizar_empresa(empresa, info)
                    return empresa, False

            if nombre:
                qs = Empresa.objects.filter(nombre__iexact=nombre)
                if qs.exists():
                    if nit:
                        empresa = qs.filter(nit=nit).first()
                        if empresa:
                            print(f"   ✅ Encontrada por nombre+NIT: {empresa.nombre}")
                            return empresa, False
                        print("   ⚠️  Mismo nombre, NIT diferente → nueva entrada")
                    else:
                        empresa = qs.first()
                        print(f"   ✅ Encontrada por nombre: {empresa.nombre}")
                        self._actualizar_empresa(empresa, info)
                        return empresa, False

            if correo and '@ejemplo.com' not in correo:
                empresa = Empresa.objects.filter(correo__iexact=correo).first()
                if empresa:
                    print(f"   ✅ Encontrada por correo: {empresa.nombre}")
                    self._actualizar_empresa(empresa, info)
                    return empresa, False

            print("   🆕 Creando nueva entidad...")

            nombre_final = nombre if nombre else f"Entidad {(correo or '').split('@')[0]}"
            correo_final = correo if correo else (
                f"sin-correo-{timezone.now().timestamp()}@ejemplo.com"
            )

            if Empresa.objects.filter(nombre__iexact=nombre_final).exists():
                ts = timezone.now().strftime('%Y%m%d-%H%M%S')
                nombre_final = f"{nombre_final} ({ts})"
                print(f"   ⚠️  Nombre duplicado → {nombre_final}")

            try:
                empresa = Empresa.objects.create(
                    nombre             =nombre_final[:200],
                    nit                =nit or None,
                    contacto           =(info.get('contacto') or 'Sin contacto')[:100],
                    telefono           =(info.get('telefono') or '')[:20],
                    correo             =correo_final,
                    municipio          =(info.get('municipio') or '')[:100],
                    direccion          =(info.get('direccion') or '')[:250],
                    numero_trabajadores=info.get('numero_trabajadores') or 0,
                )
                print(f"   ✅ Creada: {empresa.nombre}")
                return empresa, True

            except IntegrityError as e:
                print(f"   ❌ IntegrityError: {e}")
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
        actualizado = False
        for campo, max_len in [('contacto', 100), ('telefono', 20),
                                ('municipio', 100), ('direccion', 250)]:
            if not getattr(empresa, campo, None) and info.get(campo):
                setattr(empresa, campo, info[campo][:max_len])
                actualizado = True
        if not getattr(empresa, 'correo', None) and info.get('correo'):
            empresa.correo = info['correo']
            actualizado = True
        if (not getattr(empresa, 'numero_trabajadores', 0)
                or empresa.numero_trabajadores == 0) and info.get('numero_trabajadores'):
            empresa.numero_trabajadores = info['numero_trabajadores']
            actualizado = True
        if actualizado:
            empresa.save()
            print("   📝 Entidad actualizada")

    # =========================================================================
    # BÚSQUEDA DE PROGRAMA
    # =========================================================================

    def buscar_programa(self, nombre_programa):
        try:
            if not nombre_programa:
                return None

            print(f"   Buscando: {nombre_programa}")
            # ⭐ normalizar_para_busqueda normaliza plurales:
            # 'minicargadores' → 'minicargador', 'placas huellas' → 'placa huella'
            nombre_norm = self.normalizar_para_busqueda(nombre_programa)
            tokens_busq = set(nombre_norm.split())
            programas   = Programa.objects.filter(activo=True)
            mejor       = None
            mejor_score = 0

            for programa in programas:
                prog_norm   = self.normalizar_para_busqueda(programa.nombre)
                tokens_prog = set(prog_norm.split())
                score = 0

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
                        imp_c = (tokens_busq & importantes) & (tokens_prog & importantes)
                        if imp_c:
                            imp_b = tokens_busq & importantes
                            score = min(score + (len(imp_c) / len(imp_b)) * 15 if imp_b else score, 95)

                if score > 30:
                    print(f"   Candidato: {programa.nombre} ({score:.0f}%)")
                if score > mejor_score:
                    mejor_score = score
                    mejor = programa

            if mejor and mejor_score >= 35:
                print(f"   ✅ Programa: {mejor.nombre} ({mejor_score:.0f}%)")
                return mejor

            print(f"   ❌ No encontrado (mejor: {mejor_score:.0f}%)")
            return None

        except Exception as e:
            print(f"   Error buscando programa: {e}")
            return None

    # =========================================================================
    # ⭐ PROCESAMIENTO — CAMBIO EN procesar_correo_individual
    #
    # Único cambio: cuando info tiene '_requiere_revision_manual' = True
    # (PDF escaneado), se crea la solicitud con observación de alerta y se
    # permite que el programa sea None si no se encontró (en lugar de
    # descartar el correo completamente).
    # =========================================================================

    def procesar_correo_individual(self, correo_info):
        """Procesa un correo y crea la solicitud."""
        try:
            asunto_corto = correo_info['asunto'][:50]
            print(f"\n{'='*60}\n📧 {asunto_corto}\n{'='*60}")

            es_valido, razon = self.es_correo_valido(correo_info)
            if not es_valido:
                print(f"❌ FILTRADO: {razon}")
                self.stats['correos_filtrados'] += 1
                return None

            print(f"✅ {razon}")

            info = self.extraer_informacion_con_ia(correo_info)
            if not info:
                self.stats['errores'] += 1
                return None

            # ⭐ NUEVO: detectar si viene de PDF escaneado
            requiere_revision = info.pop('_requiere_revision_manual', False)
            razon_revision    = info.pop('_razon', '')

            empresa, _ = self.buscar_o_crear_empresa(info)
            if not empresa:
                self.stats['errores'] += 1
                return None

            programa = None
            if info.get('programa_solicitado'):
                programa = self.buscar_programa(info['programa_solicitado'])

            # ⭐ NUEVO: si es revisión manual y no se encontró programa,
            # buscar el primero activo como placeholder para no perder la solicitud
            if not programa and requiere_revision:
                print("   ⚠️  PDF escaneado sin programa identificado — usando placeholder")
                programa = Programa.objects.filter(activo=True).first()
                if not programa:
                    print("❌ No hay programas activos en la base de datos")
                    self.stats['errores'] += 1
                    return None

            if not programa:
                print(f"❌ Programa no encontrado: {info.get('programa_solicitado')}")
                self.stats['errores'] += 1
                return None

            # ⭐ NUEVO: construir observación con alerta si es revisión manual
            if requiere_revision:
                observacion = (
                    f"⚠️ REVISIÓN MANUAL REQUERIDA\n"
                    f"Razón: {razon_revision}\n"
                    f"Asunto original: {asunto_corto}\n"
                    f"Datos extraídos del PDF adjunto no disponibles — completar manualmente."
                )
                self.stats['revision_manual'] += 1
            else:
                observacion = f"Creada automáticamente desde correo: {asunto_corto}"

            solicitud = Solicitud.objects.create(
                empresa          =empresa,
                programa         =programa,
                estado           ='RECIBIDA',
                fecha_recepcion  =timezone.now(),
                observaciones    =observacion,
                numero_aprendices=info.get('numero_trabajadores'),
                correo_remitente =self._extraer_email_limpio(correo_info['remitente']),
            )

            # Guardar PDFs adjuntos
            pdfs = correo_info.get('pdfs_adjuntos', [])
            if pdfs:
                print(f"\n   📄 Guardando {len(pdfs)} PDF(s)...")
                for idx, pdf in enumerate(pdfs, 1):
                    try:
                        ts = timezone.now().strftime('%Y%m%d_%H%M%S')
                        n_limpio = re.sub(r'[^\w\s\-.]', '', pdf['nombre'])
                        n_final  = f"solicitud_{solicitud.id}_{ts}_{idx}_{n_limpio}"
                        DocumentoSolicitud.objects.create(
                            solicitud     =solicitud,
                            archivo       =ContentFile(pdf['contenido'], name=n_final),
                            nombre_archivo=pdf['nombre'],
                        )
                        if idx == 1:
                            solicitud.documento_pdf.save(
                                n_final, ContentFile(pdf['contenido']), save=True
                            )
                        print(f"   ✅ PDF #{idx}: {n_final}")
                        self.stats['pdfs_extraidos'] += 1
                    except Exception as e:
                        print(f"   ⚠️  Error PDF #{idx}: {e}")

            estado_log = "⚠️ REVISIÓN MANUAL" if requiere_revision else "✅"
            print(f"\n{estado_log} SOLICITUD #{solicitud.id} → {empresa.nombre}")
            self.stats['solicitudes_creadas'] += 1
            self.stats['correos_procesados']  += 1
            return solicitud

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            self.stats['errores'] += 1
            return None

    def procesar_correos(self, limite=20, procesar_en_paralelo=False, max_workers=3):
        print("\n" + "="*60)
        print("🚀 PROCESAMIENTO DE CORREOS")
        print(f"   Límite: {limite} | Paralelo: {procesar_en_paralelo}")
        print("="*60)

        self.stats = {k: 0 for k in self.stats}
        correos = self.leer_correos_no_leidos(limite=limite)

        if not correos:
            print("\n📭 Sin correos nuevos")
            return []

        solicitudes_creadas = []

        if procesar_en_paralelo and len(correos) > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self.procesar_correo_individual, c): c for c in correos}
                for future in as_completed(futures):
                    try:
                        s = future.result()
                        if s:
                            solicitudes_creadas.append(s)
                    except Exception as e:
                        logger.error(f"Error paralelo: {e}")
        else:
            for idx, correo in enumerate(correos, 1):
                print(f"\n{'='*60}\nCORREO {idx}/{len(correos)}\n{'='*60}")
                s = self.procesar_correo_individual(correo)
                if s:
                    solicitudes_creadas.append(s)

        self.mostrar_resumen()
        return solicitudes_creadas

    def mostrar_resumen(self):
        print("\n" + "="*60 + "\n📊 RESUMEN\n" + "="*60)
        for k, v in self.stats.items():
            print(f"   {k}: {v}")
        if self.stats['total_correos'] > 0:
            tasa = (self.stats['solicitudes_creadas'] / self.stats['total_correos']) * 100
            print(f"   tasa_exito: {tasa:.1f}%")
        # ⭐ NUEVO: advertencia si hay solicitudes pendientes de revisión manual
        if self.stats.get('revision_manual', 0) > 0:
            print(f"\n   ⚠️  {self.stats['revision_manual']} solicitud(es) requieren REVISIÓN MANUAL")
            print(f"      (PDF escaneado — completar datos en el panel de edición)")
        print("="*60)

    def enviar_respuesta_automatica(self, empresa, solicitud, correo_info):
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
            m = re.search(r'[\w\.-]+@[\w\.-]+', correo_info['remitente'])
            dest = m.group(0) if m else empresa.correo
            if dest and '@ejemplo.com' not in dest:
                send_mail(
                    subject=asunto, message=mensaje,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[dest], fail_silently=False,
                )
                print(f"   ✅ Respuesta enviada a: {dest}")
        except Exception as e:
            print(f"   ❌ Error enviando respuesta: {e}")

    def marcar_como_leido(self, email_id):
        try:
            mail = self.conectar_email()
            if mail:
                mail.select('INBOX')
                mail.store(email_id, '+FLAGS', '\\Seen')
                mail.close()
                mail.logout()
                return True
        except Exception as e:
            print(f"⚠️  Error marcando leído: {e}")
        return False

    def _extraer_email_limpio(self, remitente):
        try:
            m = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', remitente)
            return m.group(0).lower() if m else None
        except:
            return None