import imaplib
import email
from email.header import decode_header
import re
from datetime import datetime
import json
import unicodedata

from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone

from .models import Solicitud
from empresas.models import Empresa
from programas.models import Programa
from instructores.models import Instructor


class EmailSolicitudHandler:
    """Manejador de correos electronicos para solicitudes de formacion"""
    
    def __init__(self):
        self.imap_server = getattr(settings, 'EMAIL_HOST', 'imap.gmail.com')
        self.email_account = getattr(settings, 'EMAIL_HOST_USER', '')
        self.email_password = getattr(settings, 'EMAIL_HOST_PASSWORD', '')
        self.imap_port = getattr(settings, 'EMAIL_PORT', 993)
        
    def conectar_email(self):
        """Conecta al servidor de correo"""
        try:
            if not self.email_account or not self.email_password:
                print("ERROR: EMAIL_HOST_USER o EMAIL_HOST_PASSWORD no configurados")
                return None
                
            print("Intentando conectar a " + self.imap_server + ":" + str(self.imap_port))
            
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_account, self.email_password)
            print("Conectado exitosamente a " + self.email_account)
            return mail
            
        except Exception as e:
            print("Error conectando al correo: " + str(e))
            return None
    
    def leer_correos_no_leidos(self):
        """Lee correos no leidos de la bandeja de entrada"""
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
            print("Correos no leidos encontrados: " + str(len(email_ids)))
            
            if not email_ids:
                return []
            
            correos = []
            
            for idx, email_id in enumerate(email_ids, 1):
                print("\nProcesando correo " + str(idx) + "/" + str(len(email_ids)))
                
                status, msg_data = mail.fetch(email_id, '(RFC822)')
                
                if status != "OK":
                    continue
                
                msg = email.message_from_bytes(msg_data[0][1])
                correo_info = self.parsear_correo(msg)
                
                if correo_info:
                    correos.append(correo_info)
            
            mail.close()
            mail.logout()
            
            return correos
            
        except Exception as e:
            print("Error leyendo correos: " + str(e))
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
            print("Error parseando correo: " + str(e))
            return None
    
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
                'contacto': None,
                'correo': None,
                'telefono': None,
                'municipio': None,
                'numero_trabajadores': 0,
                'programa_solicitado': None,
                'observaciones': cuerpo[:500]
            }
            
            # ========== EXTRACCION DE NOMBRE DE EMPRESA ==========
            print("\n   === BUSCANDO NOMBRE DE EMPRESA ===")
            
            # METODO 1: Buscar "Nombre:" en seccion estructurada
            nombre_match = re.search(r'Nombre:\s*([^\n]+)', cuerpo, re.IGNORECASE)
            if nombre_match:
                nombre = nombre_match.group(1).strip()
                nombre = re.sub(r'\s*NIT:.*', '', nombre, flags=re.IGNORECASE).strip()
                info['nombre'] = nombre[:200]
                print("   METODO 1 - Campo Nombre: " + info['nombre'])
            
            # METODO 2: Buscar "la empresa NOMBRE" en el texto
            if not info['nombre']:
                empresa_match = re.search(
                    r'(?:la\s+empresa|empresa)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s&\.]+?(?:S\.A\.S|S\.A|LTDA|SAS|SA))',
                    cuerpo,
                    re.IGNORECASE
                )
                if empresa_match:
                    info['nombre'] = empresa_match.group(1).strip()[:200]
                    print("   METODO 2 - Texto narrativo: " + info['nombre'])
            
            # METODO 3: Buscar empresas en mayusculas al inicio del correo
            if not info['nombre']:
                primeras_lineas = '\n'.join(cuerpo.split('\n')[:10])
                empresa_match = re.search(
                    r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s&\.,]+(?:S\.A\.S|S\.A|LTDA|SAS|SA))',
                    primeras_lineas
                )
                if empresa_match:
                    nombre_candidato = empresa_match.group(1).strip()
                    # Excluir si es muy corto o parece firma
                    if len(nombre_candidato) > 8 and 'SENA' not in nombre_candidato.upper():
                        info['nombre'] = nombre_candidato[:200]
                        print("   METODO 3 - Mayusculas: " + info['nombre'])
            
            if not info['nombre']:
                print("   NO SE ENCONTRO NOMBRE DE EMPRESA")
            
            # ========== EXTRACCION DE CONTACTO ==========
            # METODO 1: Campo estructurado "Contacto:" o "Representante de contacto:"
            contacto_match = re.search(
                r'(?:Contacto|Representante\s+de\s+contacto):\s*([^\n]+)',
                cuerpo,
                re.IGNORECASE
            )
            if contacto_match:
                contacto = contacto_match.group(1).strip()
                # Limpiar si viene con "Nombre:" o similar
                contacto = re.sub(r'^Nombre:\s*', '', contacto, flags=re.IGNORECASE)
                info['contacto'] = contacto[:100]
                print("   Contacto: " + info['contacto'])
            
            # ========== EXTRACCION DE EMAIL ==========
            # METODO 1: Campo "Correo:" o "Email:"
            email_match = re.search(
                r'(?:Correo|Email):\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                cuerpo,
                re.IGNORECASE
            )
            if email_match:
                info['correo'] = email_match.group(1).strip()
                print("   Email (campo): " + info['correo'])
            
            # METODO 2: Cualquier email en el texto
            if not info['correo']:
                email_match = re.search(
                    r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                    cuerpo
                )
                if email_match:
                    info['correo'] = email_match.group(1).strip()
                    print("   Email (texto): " + info['correo'])
            
            # METODO 3: Email del remitente
            if not info['correo']:
                email_match = re.search(
                    r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                    remitente
                )
                if email_match:
                    info['correo'] = email_match.group(1).strip()
                    print("   Email (remitente): " + info['correo'])
            
            # ========== EXTRACCION DE TELEFONO ==========
            tel_match = re.search(
                r'Tel[eéÉ]fono:\s*([0-9\-\s\(\)]+)',
                cuerpo,
                re.IGNORECASE
            )
            if tel_match:
                telefono = tel_match.group(1).strip()
                # Limpiar espacios y guiones innecesarios
                telefono = re.sub(r'[\s\-\(\)]', '', telefono)
                info['telefono'] = telefono[:20]
                print("   Telefono: " + info['telefono'])
            
            # ========== EXTRACCION DE MUNICIPIO ==========
            municipio_match = re.search(
                r'Municipio:\s*([^\n]+)',
                cuerpo,
                re.IGNORECASE
            )
            if municipio_match:
                municipio = municipio_match.group(1).strip()
                # Limpiar si viene con guion o mas texto
                municipio = re.split(r'\s*[-–]\s*', municipio)[0]
                info['municipio'] = municipio[:100]
                print("   Municipio: " + info['municipio'])
            
            # ========== EXTRACCION DE TRABAJADORES ==========
            trab_match = re.search(
                r'N[uúÚ]mero\s+de\s+trabajadores:\s*([0-9]+)',
                cuerpo,
                re.IGNORECASE
            )
            if trab_match:
                info['numero_trabajadores'] = int(trab_match.group(1))
                print("   Trabajadores: " + str(info['numero_trabajadores']))
            
            # ========== EXTRACCION DE PROGRAMA ==========
            print("\n   === BUSCANDO PROGRAMA ===")
            
            # METODO 1: En el asunto del correo
            prog_match = re.search(
                r'(?:programa|formaci[oó]n|curso)\s+(?:de\s+)?([a-záéíóúñ\s]+)',
                asunto.lower()
            )
            if prog_match:
                programa = prog_match.group(1).strip()
                # Limpiar palabras comunes
                programa = re.sub(r'\s+en\s+.*$', '', programa, flags=re.IGNORECASE)
                info['programa_solicitado'] = programa
                print("   METODO 1 - Asunto: " + info['programa_solicitado'])
            
            # METODO 2: Buscar "programa de formacion NOMBRE" en comillas o negrita
            if not info['programa_solicitado']:
                prog_match = re.search(
                    r'programa\s+de\s+formaci[oó]n\s+([A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)(?:\s+para|,|\.|\n)',
                    cuerpo,
                    re.IGNORECASE
                )
                if prog_match:
                    info['programa_solicitado'] = prog_match.group(1).strip()
                    print("   METODO 2 - Texto: " + info['programa_solicitado'])
            
            # METODO 3: Palabras clave de operadores
            if not info['programa_solicitado']:
                keywords = {
                    'minicargador': 'Operador de Minicargador',
                    'mini cargador': 'Operador de Minicargador',
                    'montacargas': 'Operador de Montacargas',
                    'excavadora': 'Operador de Excavadora',
                    'retrocargador': 'Operador de Retrocargador',
                }
                
                cuerpo_lower = cuerpo.lower()
                for keyword, programa_nombre in keywords.items():
                    if keyword in cuerpo_lower:
                        info['programa_solicitado'] = programa_nombre
                        print("   METODO 3 - Keyword: " + programa_nombre)
                        break
            
            if not info['programa_solicitado']:
                print("   NO SE ENCONTRO PROGRAMA")
            
            print("\n   === RESUMEN ===")
            print("   Empresa: " + (info['nombre'] or 'NO ENCONTRADA'))
            print("   Contacto: " + (info['contacto'] or 'NO ENCONTRADO'))
            print("   Programa: " + (info['programa_solicitado'] or 'NO ENCONTRADO'))
            print("   " + "=" * 50)
            
            return info
            
        except Exception as e:
            print("   Error: " + str(e))
            import traceback
            traceback.print_exc()
            return None
    
    def buscar_o_crear_empresa(self, info):
        """Busca o crea empresa"""
        try:
            nombre = info.get('nombre')
            correo = info.get('correo')
            
            # Buscar por nombre
            if nombre:
                empresa = Empresa.objects.filter(nombre__iexact=nombre).first()
                if empresa:
                    print("   Empresa ENCONTRADA: " + empresa.nombre)
                    
                    # Actualizar datos vacios
                    actualizado = False
                    if empresa.contacto in ['Sin contacto', '', None] and info.get('contacto'):
                        empresa.contacto = info.get('contacto')[:100]
                        actualizado = True
                    if empresa.correo in ['sin-correo@ejemplo.com', '', None] and info.get('correo'):
                        empresa.correo = info.get('correo')
                        actualizado = True
                    if empresa.telefono in ['Sin telefono', '', None] and info.get('telefono'):
                        empresa.telefono = info.get('telefono')[:20]
                        actualizado = True
                    if empresa.municipio in ['No especificado', '', None] and info.get('municipio'):
                        empresa.municipio = info.get('municipio')[:100]
                        actualizado = True
                    if empresa.numero_trabajadores == 0 and info.get('numero_trabajadores', 0) > 0:
                        empresa.numero_trabajadores = info.get('numero_trabajadores', 0)
                        actualizado = True
                    
                    if actualizado:
                        empresa.save()
                        print("   Empresa ACTUALIZADA con nuevos datos")
                    
                    return empresa, False
            
            # Crear nueva
            print("   Creando NUEVA empresa...")
            empresa = Empresa.objects.create(
                nombre=(nombre or 'Empresa sin nombre')[:200],
                contacto=(info.get('contacto') or 'Sin contacto')[:100],
                telefono=(info.get('telefono') or 'Sin telefono')[:20],
                correo=(correo or 'sin-correo@ejemplo.com'),
                municipio=(info.get('municipio') or 'No especificado')[:100],
                numero_trabajadores=info.get('numero_trabajadores', 0)
            )
            print("   Empresa CREADA: " + empresa.nombre)
            return empresa, True
            
        except Exception as e:
            print("   Error: " + str(e))
            import traceback
            traceback.print_exc()
            return None, False
    
    def normalizar_texto(self, texto):
        """Normaliza texto"""
        if not texto:
            return ""
        texto = texto.lower()
        texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
        texto = re.sub(r'[^a-z0-9\s]', '', texto)
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto
    
    def buscar_programa(self, nombre_programa):
        """Busca programa"""
        try:
            if not nombre_programa:
                return None
            
            print("   Buscando: " + nombre_programa)
            nombre_norm = self.normalizar_texto(nombre_programa)
            
            programas = Programa.objects.filter(activo=True)
            
            for programa in programas:
                prog_norm = self.normalizar_texto(programa.nombre)
                if prog_norm == nombre_norm or nombre_norm in prog_norm or prog_norm in nombre_norm:
                    print("   Encontrado: " + programa.nombre)
                    return programa
            
            print("   NO encontrado en BD")
            return None
            
        except Exception as e:
            print("   Error: " + str(e))
            return None
    
    def crear_solicitud(self, correo_info):
        """Crea solicitud"""
        try:
            print("\n" + "-" * 60)
            print("Procesando: " + correo_info['asunto'][:50])
            
            info = self.extraer_informacion_con_ia(correo_info)
            if not info:
                print("ERROR: No se pudo extraer informacion")
                return None
            
            empresa, es_nueva = self.buscar_o_crear_empresa(info)
            if not empresa:
                print("ERROR: No se pudo crear empresa")
                return None
            
            programa = None
            if info.get('programa_solicitado'):
                programa = self.buscar_programa(info.get('programa_solicitado'))
            
            if not programa:
                print("   ERROR: Programa no encontrado")
                return None
            
            solicitud = Solicitud.objects.create(
                empresa=empresa,
                programa=programa,
                estado='RECIBIDA',
                fecha_recepcion=timezone.now(),
                observaciones=info.get('observaciones', '')
            )
            
            print("   Solicitud creada: #" + str(solicitud.id))
            self.enviar_respuesta_automatica(empresa, solicitud, correo_info)
            return solicitud
            
        except Exception as e:
            print("Error: " + str(e))
            import traceback
            traceback.print_exc()
            return None
    
    def enviar_respuesta_automatica(self, empresa, solicitud, correo_info):
        """Envia respuesta"""
        try:
            asunto = "RE: " + correo_info['asunto']
            mensaje = "Estimado/a " + empresa.contacto + ",\n\nSolicitud #" + str(solicitud.id) + " recibida.\n\nSENA"
            
            email_match = re.search(r'[\w\.-]+@[\w\.-]+', correo_info['remitente'])
            destinatario = email_match.group(0) if email_match else empresa.correo
            
            if destinatario and destinatario != 'sin-correo@ejemplo.com':
                send_mail(
                    subject=asunto,
                    message=mensaje,
                    from_email=self.email_account,
                    recipient_list=[destinatario],
                    fail_silently=False
                )
                print("   Respuesta enviada a: " + destinatario)
        except Exception as e:
            print("   Error enviando: " + str(e))
    
    def procesar_correos(self):
        """Procesa correos"""
        print("\n" + "=" * 60)
        print("PROCESANDO CORREOS")
        print("=" * 60)
        
        correos = self.leer_correos_no_leidos()
        if not correos:
            print("\nNo hay correos nuevos")
            return []
        
        solicitudes_creadas = []
        for idx, correo in enumerate(correos, 1):
            print("\n" + "=" * 60)
            print("CORREO " + str(idx) + "/" + str(len(correos)))
            print("=" * 60)
            
            solicitud = self.crear_solicitud(correo)
            if solicitud:
                solicitudes_creadas.append(solicitud)
        
        print("\n" + "=" * 60)
        print("RESUMEN: " + str(len(solicitudes_creadas)) + " creadas")
        print("=" * 60)
        
        return solicitudes_creadas