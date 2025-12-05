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
        # Configuración IMAP para RECIBIR correos
        self.imap_server = getattr(settings, 'IMAP_HOST', 'imap.gmail.com')
        self.imap_port = getattr(settings, 'IMAP_PORT', 993)
        self.email_account = getattr(settings, 'IMAP_USER', settings.EMAIL_HOST_USER)
        self.email_password = getattr(settings, 'IMAP_PASSWORD', settings.EMAIL_HOST_PASSWORD)
        
        print(f"🔧 Configuración IMAP: {self.imap_server}:{self.imap_port}")
        print(f"📧 Cuenta: {self.email_account}")
    
    def limpiar_texto(self, texto):
        """Limpia asteriscos, espacios extras y caracteres no deseados"""
        if not texto:
            return None
        
        # Eliminar asteriscos
        texto = texto.replace('*', '')
        
        # Eliminar espacios múltiples
        texto = re.sub(r'\s+', ' ', texto)
        
        # Eliminar espacios al inicio y final
        texto = texto.strip()
        
        # Si queda vacío, retornar None
        if not texto or texto.lower() in ['sin especificar', 'no especificado', 'n/a', 'na']:
            return None
        
        return texto
    
    def validar_nit(self, nit):
        """
        Valida y limpia el NIT segun las reglas de tu aplicacion.
        Retorna el NIT limpio o None si no es valido.
        """
        if not nit: 
            return None
        
        # Limpiar espacios, guiones y puntos (CORREGIDO: espacio vacío '')
        nit_limpio = nit.replace(' ', '').replace('-', '').replace('.', '')
        
        # Validar que solo contenga digitos
        if not nit_limpio.isdigit():
            print(f"   ⚠️ NIT invalido (contiene caracteres no numericos): {nit}")
            return None
        
        # Validar longitud minima (8 digitos - corregido de 9 a 8)
        if len(nit_limpio) < 8:
            print(f"   ⚠️ NIT invalido (menos de 8 digitos): {nit_limpio}")
            return None
        
        # Validar longitud maxima (20 segun tu modelo)
        if len(nit_limpio) > 20:
            print(f"   ⚠️ NIT invalido (mas de 20 digitos): {nit_limpio}")
            return None
        
        print(f"   ✅ NIT validado: {nit_limpio}")
        return nit_limpio
        
    def conectar_email(self):
        """Conecta al servidor IMAP para RECIBIR correos"""
        try:
            if not self.email_account or not self.email_password:
                print("❌ ERROR: EMAIL_HOST_USER o EMAIL_HOST_PASSWORD no configurados")
                return None
                
            print(f"🔌 Intentando conectar a {self.imap_server}:{self.imap_port}")
            
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            mail.login(self.email_account, self.email_password)
            print(f"✅ Conectado exitosamente a {self.email_account} (IMAP)")
            return mail
            
        except Exception as e:
            print(f"❌ Error conectando al correo IMAP: {str(e)}")
            import traceback
            traceback.print_exc()
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
            
            # ========== EXTRACCION DE NOMBRE DE EMPRESA Y NIT ==========
            print("\n   === BUSCANDO NOMBRE DE EMPRESA Y NIT ===")
            
            # METODO 1: Buscar "Nombre:" seguido opcionalmente de "NIT:"
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
                
                # Si encontró NIT en la misma línea
                if nombre_nit_match.group(2):
                    nit_candidato = nombre_nit_match.group(2).strip()
                    nit_validado = self.validar_nit(nit_candidato)
                    if nit_validado:
                        info['nit'] = nit_validado
                        print("   METODO 1 - NIT junto al nombre: " + info['nit'])
            
            # METODO 2: Buscar "la empresa NOMBRE" en el texto
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
            
            # METODO 3: Buscar empresas en mayusculas al inicio del correo
            if not info['nombre']:
                primeras_lineas = '\n'.join(cuerpo.split('\n')[:10])
                empresa_match = re.search(
                    r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s&\.,]+(?:S\.A\.S|S\.A|LTDA|SAS|SA))',
                    primeras_lineas
                )
                if empresa_match:
                    nombre_candidato = self.limpiar_texto(empresa_match.group(1))
                    # Excluir si es muy corto o parece firma
                    if nombre_candidato and len(nombre_candidato) > 8 and 'SENA' not in nombre_candidato.upper():
                        info['nombre'] = nombre_candidato[:200]
                        print("   METODO 3 - Mayusculas: " + info['nombre'])
            
            if not info['nombre']:
                print("   ⚠️ NO SE ENCONTRO NOMBRE DE EMPRESA")
            
            # ========== EXTRACCION DE NIT (si no se encontró antes) ==========
            print("\n   === BUSCANDO NIT ===")
            
            if not info['nit']:
                # METODO 1: Campo "NIT:" explicito
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
                # METODO 2: Buscar "NIT" seguido de numeros (con formatos variados)
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
                # METODO 3: Buscar secuencia de 8-11 digitos (formato tipico del NIT colombiano)
                nit_match = re.search(r'\b([0-9]{8,11})\b', cuerpo)
                if nit_match:
                    nit_candidato = nit_match.group(1)
                    # Verificar que no sea un telefono (los telefonos moviles empiezan con 3)
                    if not nit_candidato.startswith('3') or len(nit_candidato) != 10:
                        nit_validado = self.validar_nit(nit_candidato)
                        if nit_validado:
                            info['nit'] = nit_validado
                            print("   METODO 3 - Secuencia numerica: " + info['nit'])
            
            if not info['nit']:
                print("   ⚠️ NO SE ENCONTRO NIT")
            
            # ========== EXTRACCION DE CONTACTO ==========
            contacto_match = re.search(
                r'(?:Contacto|Representante\s+de\s+contacto):\s*([^\n]+)',
                cuerpo,
                re.IGNORECASE
            )
            if contacto_match:
                contacto = self.limpiar_texto(contacto_match.group(1))
                if contacto:
                    # Limpiar si viene con "Nombre:" o similar
                    contacto = re.sub(r'^Nombre:\s*', '', contacto, flags=re.IGNORECASE).strip()
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
                info['correo'] = email_match.group(1).strip().lower()
                print("   Email (campo): " + info['correo'])
            
            # METODO 2: Cualquier email en el texto
            if not info['correo']:
                email_match = re.search(
                    r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                    cuerpo
                )
                if email_match:
                    info['correo'] = email_match.group(1).strip().lower()
                    print("   Email (texto): " + info['correo'])
            
            # METODO 3: Email del remitente
            if not info['correo']:
                email_match = re.search(
                    r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                    remitente
                )
                if email_match:
                    info['correo'] = email_match.group(1).strip().lower()
                    print("   Email (remitente): " + info['correo'])
            
            # ========== EXTRACCION DE TELEFONO ==========
            print("\n   === BUSCANDO TELEFONO ===")
            
            # METODO 1: Campo "Telefono:" o "Tel:"
            tel_match = re.search(
                r'(?:Tel[eéÉ]fono|Tel|Celular|Móvil|Movil):\s*([0-9\s\-\(\)+]+)',
                cuerpo,
                re.IGNORECASE
            )
            if tel_match:
                telefono = tel_match.group(1).strip()
                # Limpiar espacios, guiones y paréntesis
                telefono_limpio = re.sub(r'[\s\-\(\)]', '', telefono)
                # Validar que tenga al menos 7 dígitos
                if len(telefono_limpio) >= 7 and telefono_limpio.isdigit():
                    info['telefono'] = telefono_limpio[:20]
                    print("   Telefono encontrado: " + info['telefono'])
            
            # METODO 2: Buscar números de 10 dígitos (celular colombiano)
            if not info['telefono']:
                tel_match = re.search(r'\b(3\d{9})\b', cuerpo)
                if tel_match:
                    info['telefono'] = tel_match.group(1)
                    print("   Telefono (celular): " + info['telefono'])
            
            # METODO 3: Buscar números de 7 dígitos (fijo)
            if not info['telefono']:
                tel_match = re.search(r'\b([2-8]\d{6})\b', cuerpo)
                if tel_match:
                    info['telefono'] = tel_match.group(1)
                    print("   Telefono (fijo): " + info['telefono'])
            
            if not info['telefono']:
                print("   ⚠️ NO SE ENCONTRO TELEFONO")
            
            # ========== EXTRACCION DE MUNICIPIO ==========
            municipio_match = re.search(
                r'Municipio:\s*([^\n]+)',
                cuerpo,
                re.IGNORECASE
            )
            if municipio_match:
                municipio = self.limpiar_texto(municipio_match.group(1))
                if municipio:
                    # Limpiar si viene con guion o más texto
                    municipio = re.split(r'\s*[-–]\s*', municipio)[0]
                    info['municipio'] = municipio[:100]
                    print("   Municipio: " + info['municipio'])
            
            # ========== EXTRACCION DE DIRECCION ==========
            print("\n   === BUSCANDO DIRECCION ===")
            
            # METODO 1: Campo "Dirección:"
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
            
            # ========== EXTRACCION DE TRABAJADORES ==========
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
            
            # ========== EXTRACCION DE PROGRAMA ==========
            print("\n   === BUSCANDO PROGRAMA ===")
            
            # METODO 1: En el asunto del correo
            prog_match = re.search(
                r'(?:programa|formaci[oó]n|curso)\s+(?:de\s+)?([a-záéíóúñ\s]+)',
                asunto.lower()
            )
            if prog_match:
                programa = self.limpiar_texto(prog_match.group(1))
                if programa:
                    # Limpiar palabras comunes
                    programa = re.sub(r'\s+en\s+.*$', '', programa, flags=re.IGNORECASE)
                    info['programa_solicitado'] = programa
                    print("   METODO 1 - Asunto: " + info['programa_solicitado'])
            
            # METODO 2: Buscar "programa de formacion NOMBRE"
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
    
    def buscar_o_crear_empresa(self, info):
        """Busca o crea empresa con validaciones mejoradas"""
        try:
            nombre = info.get('nombre')
            correo = info.get('correo')
            nit = info.get('nit')
            
            # Validar que al menos tengamos nombre o correo
            if not nombre and not correo:
                print("   ❌ ERROR: No hay nombre ni correo para crear empresa")
                return None, False
            
            # Busqueda Mejorada por NIT
            if nit:
                empresa = Empresa.objects.filter(nit=nit).first()
                if empresa:
                    print(f"   ✅ Empresa ENCONTRADA por NIT: {empresa.nombre} (NIT: {empresa.nit})")
                    # Actualizar solo campos vacios o por defecto
                    actualizado = False
                    
                    # Actualizar nombre si el actual esta vacio y tenemos uno nuevo
                    if info.get('nombre') and (not empresa.nombre or empresa.nombre.startswith('Empresa')):
                        empresa.nombre = info.get('nombre')[:200]
                        actualizado = True
                    
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
                        print("   📝 Empresa Actualizada con nuevos datos")
                        
                    return empresa, False
            
            # Buscar por nombre exacto si no se encontro por NIT
            if nombre:
                empresa = Empresa.objects.filter(nombre__iexact=nombre).first()
                if empresa:
                    print("   ✅ Empresa ENCONTRADA por nombre: " + empresa.nombre)
                    actualizado = False
                    
                    if nit and not empresa.nit:
                        empresa.nit = nit
                        actualizado = True
                        print(f"   📝 NIT actualizado en empresa existente: {nit}")
                    
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
                        print("   📝 Empresa ACTUALIZADA con nuevos datos")
                    
                    return empresa, False
            
            # Crear nueva empresa con validaciones
            print("   🆕 Creando NUEVA empresa...")
            
            # Preparar datos con valores por defecto solo si es necesario
            nombre_empresa = nombre if nombre else f"Empresa {correo.split('@')[0]}"
            nit_empresa = nit if nit else ''
            contacto_empresa = info.get('contacto') if info.get('contacto') else 'Sin contacto'
            telefono_empresa = info.get('telefono') if info.get('telefono') else ''
            correo_empresa = correo if correo else f"sin-correo-{timezone.now().timestamp()}@ejemplo.com"
            municipio_empresa = info.get('municipio') if info.get('municipio') else ''
            direccion_empresa = info.get('direccion') if info.get('direccion') else ''
            num_trabajadores = info.get('numero_trabajadores') if info.get('numero_trabajadores') else 0
            
            empresa = Empresa.objects.create(
                nombre=nombre_empresa[:200],
                nit=nit_empresa[:20],
                contacto=contacto_empresa[:100],
                telefono=telefono_empresa[:20],
                correo=correo_empresa,
                municipio=municipio_empresa[:100],
                direccion=direccion_empresa[:250],
                numero_trabajadores=num_trabajadores
            )
            
            print("   ✅ Empresa CREADA: " + empresa.nombre)
            print("   - NIT: " + (empresa.nit or 'NO REGISTRADO'))
            print("   - Telefono: " + (empresa.telefono or 'NO REGISTRADO'))
            print("   - Direccion: " + (empresa.direccion or 'NO REGISTRADA'))
            
            return empresa, True
            
        except Exception as e:
            print("   ❌ Error creando empresa: " + str(e))
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
            
            print("   Buscando programa: " + nombre_programa)
            nombre_norm = self.normalizar_texto(nombre_programa)
            
            programas = Programa.objects.filter(activo=True)
            
            for programa in programas:
                prog_norm = self.normalizar_texto(programa.nombre)
                if prog_norm == nombre_norm or nombre_norm in prog_norm or prog_norm in nombre_norm:
                    print("   Programa encontrado: " + programa.nombre)
                    return programa
            
            print("   Programa NO encontrado en BD")
            return None
            
        except Exception as e:
            print("   Error buscando programa: " + str(e))
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
                print("   ERROR: Programa no encontrado - No se puede crear solicitud")
                return None
            
            solicitud = Solicitud.objects.create(
                empresa=empresa,
                programa=programa,
                estado='RECIBIDA',
                fecha_recepcion=timezone.now(),
                observaciones=''
            )
            
            print("   Solicitud creada exitosamente: #" + str(solicitud.id))
            self.enviar_respuesta_automatica(empresa, solicitud, correo_info)
            return solicitud
            
        except Exception as e:
            print("Error creando solicitud: " + str(e))
            import traceback
            traceback.print_exc()
            return None
    
    def enviar_respuesta_automatica(self, empresa, solicitud, correo_info):
        """Envia respuesta automatica usando SMTP"""
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
            
            # Extraer email del remitente
            email_match = re.search(r'[\w\.-]+@[\w\.-]+', correo_info['remitente'])
            destinatario = email_match.group(0) if email_match else empresa.correo
            
            if destinatario and '@ejemplo.com' not in destinatario:
                # Usar send_mail de Django que usa la configuración SMTP
                send_mail(
                    subject=asunto,
                    message=mensaje,
                    from_email=settings.EMAIL_HOST_USER,  # ← Usa EMAIL_HOST_USER (SMTP)
                    recipient_list=[destinatario],
                    fail_silently=False
                )
                print(f"   ✅ Respuesta automatica enviada a: {destinatario}")
            else:
                print(f"   ⚠️ Correo no válido, no se envió respuesta: {destinatario}")
                
        except Exception as e:
            print(f"   ❌ Error enviando respuesta automatica: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def procesar_correos(self):
        """Procesa todos los correos no leídos"""
        print("\n" + "=" * 60)
        print("INICIANDO PROCESAMIENTO DE CORREOS")
        print("=" * 60)
        
        correos = self.leer_correos_no_leidos()
        if not correos:
            print("\nNo hay correos nuevos para procesar")
            return []
        
        solicitudes_creadas = []
        for idx, correo in enumerate(correos, 1):
            print("\n" + "=" * 60)
            print(f"PROCESANDO CORREO {idx}/{len(correos)}")
            print("=" * 60)
            
            solicitud = self.crear_solicitud(correo)
            if solicitud:
                solicitudes_creadas.append(solicitud)
        
        print("\n" + "=" * 60)
        print(f"RESUMEN FINAL: {len(solicitudes_creadas)} solicitudes creadas de {len(correos)} correos")
        print("=" * 60)
        
        return solicitudes_creadas