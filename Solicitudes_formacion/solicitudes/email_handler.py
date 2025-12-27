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

from .models import Solicitud
from empresas.models import Empresa
from programas.models import Programa
from instructores.models import Instructor

# Configurar logging
logger = logging.getLogger(__name__)


class EmailSolicitudHandler:
    """Manejador de correos electronicos para solicitudes de formacion - VERSIÓN MEJORADA"""
    
    # =========================================================================
    # CONFIGURACIÓN DE FILTROS
    # =========================================================================
    
    PALABRAS_CLAVE_ASUNTO = [
        'solicitud', 'formación', 'formacion', 'capacitación', 'capacitacion',
        'programa', 'curso', 'entrenamiento', 'sena',
    ]
    
    PALABRAS_CLAVE_CUERPO = [
        'empresa', 'nit', 'programa de formación', 'programa de formacion',
        'solicito', 'solicitamos', 'requerimos', 'necesitamos capacitación',
        'trabajadores',
    ]
    
    DOMINIOS_EXCLUIDOS = [
        'noreply', 'no-reply', 'mailer-daemon', 'postmaster',
        'notification', 'marketing', 'newsletter',
    ]
    
    CAMPOS_MINIMOS_REQUERIDOS = 2
    
    # Keywords para programas (fácil de expandir)
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
    }
    
    def __init__(self):
        self.imap_server = getattr(settings, 'IMAP_HOST', 'imap.gmail.com')
        self.imap_port = getattr(settings, 'IMAP_PORT', 993)
        self.email_account = getattr(settings, 'IMAP_USER', settings.EMAIL_HOST_USER)
        self.email_password = getattr(settings, 'IMAP_PASSWORD', settings.EMAIL_HOST_PASSWORD)
        
        self.stats = {
            'total_correos': 0,
            'correos_filtrados': 0,
            'correos_procesados': 0,
            'solicitudes_creadas': 0,
            'errores': 0,
        }
        
        print(f"🔧 Configuración IMAP: {self.imap_server}:{self.imap_port}")
        print(f"📧 Cuenta: {self.email_account}")
    
    # =========================================================================
    # MÉTODOS DE CONEXIÓN (MEJORADOS CON MANEJO DE ERRORES)
    # =========================================================================
    
    def conectar_email(self):
        """Conecta al servidor IMAP con manejo robusto de errores"""
        try:
            if not self.email_account or not self.email_password:
                logger.error("Credenciales IMAP no configuradas")
                print("❌ ERROR: EMAIL_HOST_USER o EMAIL_HOST_PASSWORD no configurados")
                return None
            
            print(f"🔌 Intentando conectar a {self.imap_server}:{self.imap_port}")
            
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_account, self.email_password)
            print(f"✅ Conectado exitosamente a {self.email_account} (IMAP)")
            return mail
            
        except imaplib.IMAP4.error as e:
            logger.error(f"Error de autenticación IMAP: {str(e)}")
            print(f"❌ Error de autenticación: {str(e)}")
            print("💡 Verifica las credenciales y permisos de la cuenta")
            return None
        except Exception as e:
            logger.error(f"Error conectando IMAP: {str(e)}")
            print(f"❌ Error conectando al correo IMAP: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def leer_correos_no_leidos(self, limite=20):
        """
        Lee correos no leidos de la bandeja de entrada.
        
        Args:
            limite (int): Número máximo de correos a leer. Por defecto 20 (seguro).
        """
        mail = self.conectar_email()
        if not mail:
            return []
        
        try:
            status, response = mail.select('INBOX')
            
            if status != "OK":
                return []
            
            status, messages = mail.search(None, 'UNSEEN')
            
            if status != "OK":
                return []
            
            email_ids = messages[0].split()
            self.stats['total_correos'] = len(email_ids)
            
            print(f"\n📬 Correos no leídos encontrados: {len(email_ids)}")
            
            if not email_ids:
                return []
            
            # Aplicar límite de seguridad
            if limite and len(email_ids) > limite:
                print(f"⚠️ LÍMITE DE SEGURIDAD: Procesando {limite} de {len(email_ids)} correos")
                print(f"💡 Para procesar más: handler.procesar_correos(limite=N)")
                email_ids = email_ids[:limite]
            
            correos = []
            
            for idx, email_id in enumerate(email_ids, 1):
                try:
                    print(f"\n{'='*60}")
                    print(f"📨 Leyendo correo {idx}/{len(email_ids)}")
                    print(f"{'='*60}")
                    
                    status, msg_data = mail.fetch(email_id, '(RFC822)')
                    
                    if status != "OK":
                        continue
                    
                    msg = email.message_from_bytes(msg_data[0][1])
                    correo_info = self.parsear_correo(msg)
                    
                    if correo_info:
                        correo_info['email_id'] = email_id
                        correos.append(correo_info)
                except Exception as e:
                    logger.error(f"Error leyendo correo {idx}: {str(e)}")
                    print(f"⚠️ Error leyendo correo {idx}, continuando...")
                    continue
            
            mail.close()
            mail.logout()
            
            return correos
            
        except Exception as e:
            print(f"❌ Error leyendo correos: {str(e)}")
            return []
    
    def parsear_correo(self, msg):
        """Extrae informacion basica del correo"""
        try:
            subject = ""
            if msg["Subject"]:
                subject_header = decode_header(msg["Subject"])[0]
                subject, encoding = subject_header[0], subject_header[1]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8", errors='ignore')
            
            from_email = msg.get("From", "")
            
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
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
                'fecha': msg.get("Date", "")
            }
            
        except Exception as e:
            print(f"❌ Error parseando correo: {str(e)}")
            return None
    
    # =========================================================================
    # MÉTODOS DE FILTRADO
    # =========================================================================
    
    def es_correo_valido(self, correo_info):
        """Determina si un correo es una solicitud válida"""
        try:
            asunto = correo_info.get('asunto', '').lower()
            cuerpo = correo_info.get('cuerpo', '').lower()
            remitente = correo_info.get('remitente', '').lower()
            
            for dominio in self.DOMINIOS_EXCLUIDOS:
                if dominio in remitente:
                    return False, f"Dominio excluido: {dominio}"
            
            tiene_palabra_clave_asunto = any(
                palabra in asunto 
                for palabra in self.PALABRAS_CLAVE_ASUNTO
            )
            
            if not tiene_palabra_clave_asunto:
                return False, "No contiene palabras clave en asunto"
            
            palabras_encontradas = sum(
                1 for palabra in self.PALABRAS_CLAVE_CUERPO 
                if palabra in cuerpo
            )
            
            if palabras_encontradas < 2:
                return False, f"Solo {palabras_encontradas} palabras clave en cuerpo (mínimo 2)"
            
            if len(cuerpo) < 100:
                return False, f"Cuerpo muy corto ({len(cuerpo)} caracteres)"
            
            info_extraida = self.extraer_informacion_con_ia(correo_info)
            if not info_extraida:
                return False, "No se pudo extraer información"
            
            campos_encontrados = sum([
                1 if info_extraida.get('nombre') else 0,
                1 if info_extraida.get('programa_solicitado') else 0,
                1 if info_extraida.get('correo') else 0,
                1 if info_extraida.get('telefono') else 0,
            ])
            
            if campos_encontrados < self.CAMPOS_MINIMOS_REQUERIDOS:
                return False, f"Campos insuficientes ({campos_encontrados}/{self.CAMPOS_MINIMOS_REQUERIDOS})"
            
            return True, "Correo válido"
            
        except Exception as e:
            return False, f"Error en validación: {str(e)}"
    
    # =========================================================================
    # MÉTODOS DE EXTRACCIÓN (MEJORADOS)
    # =========================================================================
    
    def limpiar_texto(self, texto):
        """Limpia asteriscos, espacios extras y caracteres no deseados"""
        if not texto:
            return None
        
        texto = texto.replace('*', '')
        texto = re.sub(r'\s+', ' ', texto)
        texto = texto.strip()
        
        if not texto or texto.lower() in ['sin especificar', 'no especificado', 'n/a', 'na']:
            return None
        
        return texto
    
    def validar_nit(self, nit):
        """
        Valida y limpia el NIT - MEJORADO
        Formato colombiano: 9-10 dígitos + dígito verificación
        """
        if not nit: 
            return None
        
        nit_limpio = nit.replace(' ', '').replace('-', '').replace('.', '')
        
        if not nit_limpio.isdigit():
            print(f"   ⚠️ NIT inválido (contiene caracteres no numéricos): {nit}")
            return None
        
        if len(nit_limpio) < 8:
            print(f"   ⚠️ NIT inválido (menos de 8 dígitos): {nit_limpio}")
            return None
        
        if len(nit_limpio) > 12:
            print(f"   ⚠️ NIT inválido (más de 12 dígitos): {nit_limpio}")
            return None
        
        # CORREGIDO: Descartar si es celular (empieza con 3 Y tiene 10 dígitos)
        if nit_limpio.startswith('3') and len(nit_limpio) == 10:
            print(f"   ⚠️ Posible teléfono celular, no NIT: {nit_limpio}")
            return None
        
        print(f"   ✅ NIT validado: {nit_limpio}")
        return nit_limpio
    
    def extraer_informacion_con_ia(self, correo_info):
        """Extrae informacion del correo con multiples estrategias"""
        try:
            cuerpo = correo_info.get('cuerpo', '')
            remitente = correo_info.get('remitente', '')
            asunto = correo_info.get('asunto', '')
            
            if not cuerpo:
                return None
            
            print("   Extrayendo informacion...")
            
            info = {
                'nombre': None,
                'nit': None,
                'contacto': None,
                'correo': None,
                'telefono': None,
                'municipio': None,
                'direccion': None,
                'numero_trabajadores': None,
                'programa_solicitado': None,
                'observaciones': None,
            }
            
            # ========== NOMBRE DE EMPRESA ==========
            print("\n   === BUSCANDO NOMBRE DE EMPRESA ===")
            
            nombre_nit_match = re.search(
                r'Nombre:\s*([^\n]+?)(?:\s*NIT:\s*([0-9\s\.\-]+))?(?:\n|$)',
                cuerpo,
                re.IGNORECASE
            )
            if nombre_nit_match:
                nombre = self.limpiar_texto(nombre_nit_match.group(1))
                if nombre:
                    info['nombre'] = nombre[:200]
                    print("   METODO 1 - Campo Nombre: " + info['nombre'])
                
                if nombre_nit_match.group(2):
                    nit_candidato = nombre_nit_match.group(2).strip()
                    nit_validado = self.validar_nit(nit_candidato)
                    if nit_validado:
                        info['nit'] = nit_validado
                        print("   METODO 1 - NIT junto al nombre: " + info['nit'])
            
            if not info['nombre']:
                empresa_match = re.search(
                    r'(?:la\s+empresa|empresa)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s&\.]+?(?:S\.A\.S|S\.A|LTDA|SAS|SA))',
                    cuerpo,
                    re.IGNORECASE
                )
                if empresa_match:
                    nombre = self.limpiar_texto(empresa_match.group(1))
                    if nombre:
                        info['nombre'] = nombre[:200]
                        print("   METODO 2 - Texto narrativo: " + info['nombre'])
            
            if not info['nombre']:
                primeras_lineas = '\n'.join(cuerpo.split('\n')[:10])
                empresa_match = re.search(
                    r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s&\.,]+(?:S\.A\.S|S\.A|LTDA|SAS|SA))',
                    primeras_lineas
                )
                if empresa_match:
                    nombre_candidato = self.limpiar_texto(empresa_match.group(1))
                    if nombre_candidato and len(nombre_candidato) > 8 and 'SENA' not in nombre_candidato.upper():
                        info['nombre'] = nombre_candidato[:200]
                        print("   METODO 3 - Mayusculas: " + info['nombre'])
            
            if not info['nombre']:
                print("   ⚠️ NO SE ENCONTRO NOMBRE DE EMPRESA")
            
            # ========== NIT ==========
            print("\n   === BUSCANDO NIT ===")
            
            if not info['nit']:
                nit_match = re.search(
                    r'NIT:\s*([0-9\s\.\-]+)',
                    cuerpo,
                    re.IGNORECASE
                )
                if nit_match:
                    nit_candidato = nit_match.group(1).strip()
                    nit_validado = self.validar_nit(nit_candidato)
                    if nit_validado:
                        info['nit'] = nit_validado
                        print("   METODO 1 - Campo NIT: " + info['nit'])
            
            if not info['nit']:
                nit_match = re.search(
                    r'NIT\s*[:\-]?\s*([0-9\s\.\-]{8,15})',
                    cuerpo,
                    re.IGNORECASE
                )
                if nit_match:
                    nit_candidato = nit_match.group(1).strip()
                    nit_validado = self.validar_nit(nit_candidato)
                    if nit_validado:
                        info['nit'] = nit_validado
                        print("   METODO 2 - Texto con NIT: " + info['nit'])
            
            if not info['nit']:
                nit_match = re.search(r'\b([0-9]{8,11})\b', cuerpo)
                if nit_match:
                    nit_candidato = nit_match.group(1)
                    nit_validado = self.validar_nit(nit_candidato)
                    if nit_validado:
                        info['nit'] = nit_validado
                        print("   METODO 3 - Secuencia numerica: " + info['nit'])
            
            if not info['nit']:
                print("   ⚠️ NO SE ENCONTRO NIT")
            
            # ========== CONTACTO ==========
            contacto_match = re.search(
                r'(?:Contacto|Representante\s+de\s+contacto):\s*([^\n]+)',
                cuerpo,
                re.IGNORECASE
            )
            if contacto_match:
                contacto = self.limpiar_texto(contacto_match.group(1))
                if contacto:
                    contacto = re.sub(r'^Nombre:\s*', '', contacto, flags=re.IGNORECASE).strip()
                    info['contacto'] = contacto[:100]
                    print("   Contacto: " + info['contacto'])
            
            # ========== EMAIL ==========
            email_match = re.search(
                r'(?:Correo|Email):\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                cuerpo,
                re.IGNORECASE
            )
            if email_match:
                info['correo'] = email_match.group(1).strip().lower()
                print("   Email (campo): " + info['correo'])
            
            if not info['correo']:
                email_match = re.search(
                    r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                    cuerpo
                )
                if email_match:
                    info['correo'] = email_match.group(1).strip().lower()
                    print("   Email (texto): " + info['correo'])
            
            if not info['correo']:
                email_match = re.search(
                    r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                    remitente
                )
                if email_match:
                    email_extraido = email_match.group(1).strip().lower()
                    if not any(dom in email_extraido for dom in self.DOMINIOS_EXCLUIDOS):
                        info['correo'] = email_extraido
                        print("   Email (remitente): " + info['correo'])
            
            # ========== TELEFONO ==========
            print("\n   === BUSCANDO TELEFONO ===")
            
            tel_match = re.search(
                r'(?:Tel[eéÉ]fono|Tel|Celular|Móvil|Movil):\s*([0-9\s\-\(\)+]+)',
                cuerpo,
                re.IGNORECASE
            )
            if tel_match:
                telefono = tel_match.group(1).strip()
                telefono_limpio = re.sub(r'[\s\-\(\)]', '', telefono)
                if len(telefono_limpio) >= 7 and telefono_limpio.isdigit():
                    info['telefono'] = telefono_limpio[:20]
                    print("   Telefono encontrado: " + info['telefono'])
            
            if not info['telefono']:
                tel_match = re.search(r'\b(3\d{9})\b', cuerpo)
                if tel_match:
                    info['telefono'] = tel_match.group(1)
                    print("   Telefono (celular): " + info['telefono'])
            
            if not info['telefono']:
                tel_match = re.search(r'\b([2-8]\d{6})\b', cuerpo)
                if tel_match:
                    info['telefono'] = tel_match.group(1)
                    print("   Telefono (fijo): " + info['telefono'])
            
            if not info['telefono']:
                print("   ⚠️ NO SE ENCONTRO TELEFONO")
            
            # ========== MUNICIPIO ==========
            municipio_match = re.search(
                r'Municipio:\s*([^\n]+)',
                cuerpo,
                re.IGNORECASE
            )
            if municipio_match:
                municipio = self.limpiar_texto(municipio_match.group(1))
                if municipio:
                    municipio = re.split(r'\s*[-–]\s*', municipio)[0]
                    info['municipio'] = municipio[:100]
                    print("   Municipio: " + info['municipio'])
            
            # ========== DIRECCION ==========
            print("\n   === BUSCANDO DIRECCION ===")
            
            dir_match = re.search(
                r'(?:Direcci[oó]n|Direccion):\s*([^\n]+)',
                cuerpo,
                re.IGNORECASE
            )
            if dir_match:
                direccion = self.limpiar_texto(dir_match.group(1))
                if direccion:
                    info['direccion'] = direccion[:250]
                    print("   Direccion encontrada: " + info['direccion'])
            
            if not info['direccion']:
                print("   ⚠️ NO SE ENCONTRO DIRECCION")
            
            # ========== TRABAJADORES ==========
            trab_match = re.search(
                r'N[uúÚ]mero\s+de\s+trabajadores:\s*([0-9]+)',
                cuerpo,
                re.IGNORECASE
            )
            if trab_match:
                num_trab = int(trab_match.group(1))
                if num_trab > 0:
                    info['numero_trabajadores'] = num_trab
                    print("   Trabajadores: " + str(info['numero_trabajadores']))
            
            # ========== PROGRAMA (MEJORADO CON KEYWORDS) ==========
            print("\n   === BUSCANDO PROGRAMA ===")
            
            prog_match = re.search(
                r'(?:programa|formaci[oó]n|curso)\s+(?:de\s+)?([a-záéíóúñ\s]+)',
                asunto.lower()
            )
            if prog_match:
                programa = self.limpiar_texto(prog_match.group(1))
                if programa:
                    programa = re.sub(r'\s+en\s+.*$', '', programa, flags=re.IGNORECASE)
                    info['programa_solicitado'] = programa
                    print("   METODO 1 - Asunto: " + info['programa_solicitado'])
            
            if not info['programa_solicitado']:
                prog_match = re.search(
                    r'programa\s+de\s+formaci[oó]n\s+([A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)(?:\s+para|,|\.|\n)',
                    cuerpo,
                    re.IGNORECASE
                )
                if prog_match:
                    programa = self.limpiar_texto(prog_match.group(1))
                    if programa:
                        info['programa_solicitado'] = programa
                        print("   METODO 2 - Texto: " + info['programa_solicitado'])
            
            if not info['programa_solicitado']:
                cuerpo_lower = cuerpo.lower()
                for keyword, programa_nombre in self.KEYWORDS_PROGRAMAS.items():
                    if keyword in cuerpo_lower:
                        info['programa_solicitado'] = programa_nombre
                        print(f"   METODO 3 - Keyword '{keyword}': {programa_nombre}")
                        break
            
            if not info['programa_solicitado']:
                print("   ⚠️ NO SE ENCONTRO PROGRAMA")
            
            print("\n   === RESUMEN ===")
            print("   Empresa: " + (info['nombre'] or 'NO ENCONTRADA'))
            print("   NIT: " + (info['nit'] or 'NO ENCONTRADO'))
            print("   Contacto: " + (info['contacto'] or 'NO ENCONTRADO'))
            print("   Telefono: " + (info['telefono'] or 'NO ENCONTRADO'))
            print("   Direccion: " + (info['direccion'] or 'NO ENCONTRADA'))
            print("   Programa: " + (info['programa_solicitado'] or 'NO ENCONTRADO'))
            print("   " + "=" * 50)
            
            return info
            
        except Exception as e:
            print("   Error: " + str(e))
            import traceback
            traceback.print_exc()
            return None
    
    # =========================================================================
    # BUSCAR/CREAR EMPRESA (MEJORADO CON TRANSACCIONES)
    # =========================================================================
    
    @transaction.atomic
    def buscar_o_crear_empresa(self, info):
        """
        Busca o crea empresa con manejo de duplicados MEJORADO
        """
        try:
            nombre = info.get('nombre')
            correo = info.get('correo')
            nit = info.get('nit')
            
            if not nombre and not correo:
                print("   ❌ ERROR: No hay nombre ni correo para crear empresa")
                return None, False
            
            # ESTRATEGIA 1: Búsqueda por NIT
            if nit:
                try:
                    empresa = Empresa.objects.filter(nit=nit).first()
                    if empresa:
                        print(f"   ✅ Empresa ENCONTRADA por NIT: {empresa.nombre} (NIT: {empresa.nit})")
                        
                        actualizado = False
                        
                        if info.get('nombre') and (not empresa.nombre or empresa.nombre.startswith('Empresa')):
                            empresa.nombre = info.get('nombre')[:200]
                            actualizado = True
                            print(f"   📝 Nombre actualizado: {empresa.nombre}")
                        
                        if not empresa.contacto and info.get('contacto'):
                            empresa.contacto = info.get('contacto')[:100]
                            actualizado = True
                        
                        if not empresa.correo and info.get('correo'):
                            empresa.correo = info.get('correo')
                            actualizado = True
                        
                        if not empresa.telefono and info.get('telefono'):
                            empresa.telefono = info.get('telefono')[:20]
                            actualizado = True
                        
                        if not empresa.municipio and info.get('municipio'):
                            empresa.municipio = info.get('municipio')[:100]
                            actualizado = True
                        
                        if not empresa.direccion and info.get('direccion'):
                            empresa.direccion = info.get('direccion')[:250]
                            actualizado = True
                        
                        if (not empresa.numero_trabajadores or empresa.numero_trabajadores == 0) and info.get('numero_trabajadores'):
                            empresa.numero_trabajadores = info.get('numero_trabajadores')
                            actualizado = True
                        
                        if actualizado:
                            empresa.save()
                            print("   📝 Empresa actualizada con nuevos datos")
                        
                        return empresa, False
                        
                except Exception as e:
                    logger.error(f"Error buscando empresa por NIT: {str(e)}")
            
            # ESTRATEGIA 2: Búsqueda por nombre
            if nombre:
                empresas_mismo_nombre = Empresa.objects.filter(nombre__iexact=nombre)
                
                if empresas_mismo_nombre.exists():
                    if nit:
                        empresa = empresas_mismo_nombre.filter(nit=nit).first()
                        if empresa:
                            print(f"   ✅ Empresa ENCONTRADA por nombre + NIT: {empresa.nombre}")
                            return empresa, False
                        else:
                            print(f"   ⚠️ ALERTA: Ya existe empresa '{nombre}' pero con NIT diferente")
                            print(f"   🆕 Creando NUEVA empresa (mismo nombre, NIT diferente)")
                    else:
                        empresa = empresas_mismo_nombre.first()
                        print(f"   ✅ Empresa ENCONTRADA por nombre (sin NIT): {empresa.nombre}")
                        
                        actualizado = False
                        
                        if not empresa.contacto and info.get('contacto'):
                            empresa.contacto = info.get('contacto')[:100]
                            actualizado = True
                        
                        if not empresa.correo and info.get('correo'):
                            empresa.correo = info.get('correo')
                            actualizado = True
                        
                        if not empresa.telefono and info.get('telefono'):
                            empresa.telefono = info.get('telefono')[:20]
                            actualizado = True
                        
                        if not empresa.municipio and info.get('municipio'):
                            empresa.municipio = info.get('municipio')[:100]
                            actualizado = True
                        
                        if not empresa.direccion and info.get('direccion'):
                            empresa.direccion = info.get('direccion')[:250]
                            actualizado = True
                        
                        if (not empresa.numero_trabajadores or empresa.numero_trabajadores == 0) and info.get('numero_trabajadores'):
                            empresa.numero_trabajadores = info.get('numero_trabajadores')
                            actualizado = True
                        
                        if actualizado:
                            empresa.save()
                            print("   📝 Empresa actualizada con nuevos datos")
                        
                        return empresa, False
            
            # ESTRATEGIA 3: Crear nueva empresa
            print("   🆕 Creando NUEVA empresa...")
            
            nombre_empresa = nombre if nombre else f"Empresa {correo.split('@')[0]}"
            nit_empresa = nit if nit else None
            contacto_empresa = info.get('contacto') if info.get('contacto') else 'Sin contacto'
            telefono_empresa = info.get('telefono', '')
            correo_empresa = correo if correo else f"sin-correo-{timezone.now().timestamp()}@ejemplo.com"
            municipio_empresa = info.get('municipio', '')
            direccion_empresa = info.get('direccion', '')
            num_trabajadores = info.get('numero_trabajadores', 0)
            
            if nombre and Empresa.objects.filter(nombre__iexact=nombre_empresa).exists():
                timestamp = timezone.now().strftime('%Y%m%d-%H%M%S')
                nombre_empresa = f"{nombre_empresa} ({timestamp})"
                print(f"   ⚠️ Nombre duplicado detectado, usando: {nombre_empresa}")
            
            try:
                empresa = Empresa.objects.create(
                    nombre=nombre_empresa[:200],
                    nit=nit_empresa,
                    contacto=contacto_empresa[:100],
                    telefono=telefono_empresa[:20],
                    correo=correo_empresa,
                    municipio=municipio_empresa[:100],
                    direccion=direccion_empresa[:250],
                    numero_trabajadores=num_trabajadores
                )
                
                print("   ✅ Empresa CREADA: " + empresa.nombre)
                print("   - NIT: " + (empresa.nit or 'NO REGISTRADO'))
                print("   - Contacto: " + empresa.contacto)
                print("   - Teléfono: " + (empresa.telefono or 'NO REGISTRADO'))
                print("   - Dirección: " + (empresa.direccion or 'NO REGISTRADA'))
                
                return empresa, True
                
            except IntegrityError as e:
                print(f"   ❌ Error de integridad al crear empresa: {str(e)}")
                if nit:
                    print(f"   🔄 Recuperando empresa existente con NIT {nit}")
                    empresa = Empresa.objects.filter(nit=nit).first()
                    if empresa:
                        return empresa, False
                raise
                
        except Exception as e:
            print("   ❌ Error en buscar_o_crear_empresa: " + str(e))
            import traceback
            traceback.print_exc()
            return None, False
    
    # =========================================================================
    # BÚSQUEDA DE PROGRAMA (MEJORADO)
    # =========================================================================
    
    def normalizar_texto(self, texto):
        """Normaliza texto para comparaciones"""
        if not texto:
            return ""
        texto = texto.lower()
        texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
        texto = re.sub(r'[^a-z0-9\s]', '', texto)
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto
    
    def buscar_programa(self, nombre_programa):
        """
        Busca programa con scoring de similitud MEJORADO v2
        """
        try:
            if not nombre_programa:
                return None
        
            print("   Buscando programa: " + nombre_programa)
            nombre_norm = self.normalizar_texto(nombre_programa)
            tokens_busqueda = set(nombre_norm.split())
        
            programas = Programa.objects.filter(activo=True)
        
            mejor_match = None
            mejor_score = 0
        
            for programa in programas:
                prog_norm = self.normalizar_texto(programa.nombre)
                tokens_programa = set(prog_norm.split())
            
                score = 0
            
                # NIVEL 1: Coincidencia exacta (100%)
                if prog_norm == nombre_norm:
                    score = 100
            
                # NIVEL 2: Contención completa (90%)
                elif nombre_norm in prog_norm or prog_norm in nombre_norm:
                    score = 90
            
                # NIVEL 3: Coincidencia de palabras clave importantes (70-85%)
                else:
                    tokens_comunes = tokens_busqueda.intersection(tokens_programa)
                
                    if tokens_comunes:
                        # Calcular score basado en tokens comunes
                        cobertura_busqueda = len(tokens_comunes) / len(tokens_busqueda) if len(tokens_busqueda) > 0 else 0
                        cobertura_programa = len(tokens_comunes) / len(tokens_programa) if len(tokens_programa) > 0 else 0
                    
                        # Promedio de coberturas
                        score = ((cobertura_busqueda + cobertura_programa) / 2) * 85
                    
                        # BONUS: Si contiene palabras clave importantes (hidráulico, sistemas, maquinaria, etc.)
                        palabras_importantes = {'sistemas', 'hidraulicos', 'maquinaria', 'pesada', 
                                                'operador', 'excavadora', 'retrocargador', 'montacargas',
                                                'minicargador', 'interpretacion', 'planos'}
                    
                        tokens_importantes_busqueda = tokens_busqueda.intersection(palabras_importantes)
                        tokens_importantes_programa = tokens_programa.intersection(palabras_importantes)
                        tokens_importantes_comunes = tokens_importantes_busqueda.intersection(tokens_importantes_programa)
                    
                        if tokens_importantes_comunes:
                            bonus = (len(tokens_importantes_comunes) / len(tokens_importantes_busqueda)) * 15 if len(tokens_importantes_busqueda) > 0 else 0
                            score = min(score + bonus, 95)  # Máximo 95% para evitar superar exacta
            
                # DEBUG: Mostrar scoring
                if score > 30:
                    print(f"   Candidato: {programa.nombre} (score: {score:.0f}%)")
            
                if score > mejor_score:
                    mejor_score = score
                    mejor_match = programa
        
            # UMBRAL: Reducir de 40% a 35% para ser más permisivo
            if mejor_match and mejor_score >= 35:
                print(f"   ✅ Programa encontrado: {mejor_match.nombre} (similitud: {mejor_score:.0f}%)")
                return mejor_match
        
            print(f"   ❌ Programa NO encontrado en BD (mejor score: {mejor_score:.0f}%)")
            print(f"   💡 Tokens buscados: {tokens_busqueda}")
            return None
        
        except Exception as e:
            print("   Error buscando programa: " + str(e))
            return None
    
    # =========================================================================
    # PROCESAMIENTO INDIVIDUAL (LIMPIO - TU LÓGICA)
    # =========================================================================
    
    def procesar_correo_individual(self, correo_info):
        """Procesa un solo correo - MANTIENE TU LÓGICA ORIGINAL"""
        try:
            asunto_corto = correo_info['asunto'][:50]
            
            print(f"\n{'='*60}")
            print(f"📧 Procesando: {asunto_corto}")
            print(f"{'='*60}")
            
            # PASO 1: Validar
            es_valido, razon = self.es_correo_valido(correo_info)
            
            if not es_valido:
                print(f"❌ CORREO FILTRADO: {razon}")
                print(f"   Asunto: {asunto_corto}")
                print(f"   Remitente: {correo_info['remitente'][:50]}")
                self.stats['correos_filtrados'] += 1
                return None
            
            print(f"✅ CORREO VÁLIDO: {razon}")
            
            # PASO 2: Extraer información
            info = self.extraer_informacion_con_ia(correo_info)
            if not info:
                print("❌ ERROR: No se pudo extraer información")
                self.stats['errores'] += 1
                return None
            
            # PASO 3: Buscar o crear empresa
            empresa, es_nueva = self.buscar_o_crear_empresa(info)
            if not empresa:
                print("❌ ERROR: No se pudo crear empresa")
                self.stats['errores'] += 1
                return None
            
            # PASO 4: Buscar programa
            programa = None
            if info.get('programa_solicitado'):
                programa = self.buscar_programa(info.get('programa_solicitado'))
            
            # TU LÓGICA: Si no hay programa, NO se crea solicitud
            if not programa:
                print("❌ ERROR: Programa no encontrado - No se puede crear solicitud")
                print(f"   Programa solicitado: {info.get('programa_solicitado')}")
                self.stats['errores'] += 1
                return None
            
            # PASO 5: Crear solicitud (TU ESTRUCTURA)
            solicitud = Solicitud.objects.create(
                empresa=empresa,
                programa=programa,
                estado='RECIBIDA',
                fecha_recepcion=timezone.now(),
                observaciones=f"Creada automáticamente desde correo: {asunto_corto}",
                numero_aprendices=info.get('numero_trabajadores'),
                correo_remitente=self._extraer_email_limpio(correo_info['remitente'])
            )
            
            print(f"✅ SOLICITUD CREADA: #{solicitud.id}")
            self.stats['solicitudes_creadas'] += 1
            
            # PASO 6: Enviar respuesta automática
            #self.enviar_respuesta_automatica(empresa, solicitud, correo_info)
            
            self.stats['correos_procesados'] += 1
            return solicitud
            
        except Exception as e:
            print(f"❌ Error procesando correo: {str(e)}")
            import traceback
            traceback.print_exc()
            self.stats['errores'] += 1
            return None
    
    # =========================================================================
    # PROCESAMIENTO MASIVO (SEGURO POR DEFECTO)
    # =========================================================================
    
    def procesar_correos(self, limite=20, procesar_en_paralelo=False, max_workers=3):
        """
        Procesa correos - CONFIGURACIÓN SEGURA POR DEFECTO
        
        Args:
            limite: Máximo de correos (20 por defecto = SEGURO)
            procesar_en_paralelo: False por defecto (SEGURO)
            max_workers: 3 workers máximo (SEGURO)
        """
        print("\n" + "="*60)
        print("🚀 INICIANDO PROCESAMIENTO DE CORREOS")
        print("="*60)
        print(f"📋 Configuración:")
        print(f"   - Límite: {limite if limite else 'Sin límite'}")
        print(f"   - Paralelo: {'Sí' if procesar_en_paralelo else 'No (más seguro)'}")
        if procesar_en_paralelo:
            print(f"   - Workers: {max_workers}")
        print("="*60)
        
        self.stats = {
            'total_correos': 0,
            'correos_filtrados': 0,
            'correos_procesados': 0,
            'solicitudes_creadas': 0,
            'errores': 0,
        }
        
        correos = self.leer_correos_no_leidos(limite=limite)
        
        if not correos:
            print("\n📭 No hay correos nuevos para procesar")
            return []
        
        solicitudes_creadas = []
        
        if procesar_en_paralelo and len(correos) > 1:
            print(f"\n⚡ Procesando {len(correos)} correos en paralelo...")
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self.procesar_correo_individual, correo): correo 
                    for correo in correos
                }
                
                for future in as_completed(futures):
                    try:
                        solicitud = future.result()
                        if solicitud:
                            solicitudes_creadas.append(solicitud)
                    except Exception as e:
                        logger.error(f"Error en paralelo: {str(e)}")
        else:
            print(f"\n📝 Procesando {len(correos)} correos secuencialmente...")
            
            for idx, correo in enumerate(correos, 1):
                print(f"\n{'='*60}")
                print(f"CORREO {idx}/{len(correos)}")
                print(f"{'='*60}")
                
                solicitud = self.procesar_correo_individual(correo)
                if solicitud:
                    solicitudes_creadas.append(solicitud)
        
        self.mostrar_resumen()
        
        return solicitudes_creadas
    
    def mostrar_resumen(self):
        """Muestra un resumen estadístico del procesamiento"""
        print("\n" + "="*60)
        print("📊 RESUMEN DE PROCESAMIENTO")
        print("="*60)
        print(f"📬 Total correos leídos:      {self.stats['total_correos']}")
        print(f"🚫 Correos filtrados:         {self.stats['correos_filtrados']}")
        print(f"✅ Correos procesados:        {self.stats['correos_procesados']}")
        print(f"📝 Solicitudes creadas:       {self.stats['solicitudes_creadas']}")
        print(f"❌ Errores:                   {self.stats['errores']}")
        print("="*60)
        
        if self.stats['total_correos'] > 0:
            tasa_exito = (self.stats['solicitudes_creadas'] / self.stats['total_correos']) * 100
            print(f"📈 Tasa de éxito: {tasa_exito:.1f}%")
        
        print("="*60)
    
    def enviar_respuesta_automatica(self, empresa, solicitud, correo_info):
        """Envía respuesta automática usando SMTP"""
        try:
            asunto = "RE: " + correo_info['asunto']
            mensaje = f"""Estimado/a {empresa.contacto},

Hemos recibido correctamente su solicitud de formación.

Detalles de su solicitud:
- Número de Solicitud: #{solicitud.id}
- Empresa: {empresa.nombre}
- Programa: {solicitud.programa.nombre}
- Estado: Recibida

En breve nos pondremos en contacto con ustedes para coordinar los siguientes pasos.

Cordialmente,
Servicio Nacional de Aprendizaje (SENA)
Coordinación de Formación Empresarial"""
            
            email_match = re.search(r'[\w\.-]+@[\w\.-]+', correo_info['remitente'])
            destinatario = email_match.group(0) if email_match else empresa.correo
            
            if destinatario and '@ejemplo.com' not in destinatario:
                send_mail(
                    subject=asunto,
                    message=mensaje,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[destinatario],
                    fail_silently=False
                )
                print(f"   ✅ Respuesta automática enviada a: {destinatario}")
            else:
                print(f"   ⚠️ Correo no válido, no se envió respuesta: {destinatario}")
                
        except Exception as e:
            print(f"   ❌ Error enviando respuesta automática: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def marcar_como_leido(self, email_id):
        """Marca un correo específico como leído"""
        try:
            mail = self.conectar_email()
            if mail:
                mail.select('INBOX')
                mail.store(email_id, '+FLAGS', '\\Seen')
                mail.close()
                mail.logout()
                return True
        except Exception as e:
            print(f"⚠️ Error marcando correo como leído: {str(e)}")
        return False
    def _extraer_email_limpio(self, remitente):
        """Extrae solo el email del remitente (sin nombre)"""
        try:
            # Formato: "Nombre Apellido <email@ejemplo.com>" o solo "email@ejemplo.com"
            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', remitente)
            if email_match:
                return email_match.group(0).lower()
            return None
        except:
            return None