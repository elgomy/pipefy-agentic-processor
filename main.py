import os
import requests
import logging
from fastapi import FastAPI, Request, HTTPException, Header
from pydantic import BaseModel, Field, HttpUrl, ValidationError
from typing import List, Optional, Dict, Any, Union
from agentic_doc.parse import parse_documents
from dotenv import load_dotenv
import uuid
import httpx
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import sys
import json
import hashlib
from datetime import datetime, timedelta
import time

# Configuración
load_dotenv()
PIPEFY_TOKEN = os.getenv("PIPEFY_TOKEN")
VISION_AGENT_API_KEY = os.getenv("VISION_AGENT_API_KEY")
PIPEFY_WEBHOOK_SECRET = os.getenv("RENDER_SERVICE_SECRET") or os.getenv("PIPEFY_WEBHOOK_SECRET")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data")
PIPEFY_GRAPHQL_ENDPOINT = "https://api.pipefy.com/graphql"
ATTACHMENT_FIELD_ID = os.getenv("PIPEFY_ATTACHMENT_FIELD_ID", "id_del_campo_adjunto")

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Caché para evitar procesamiento múltiple
# Estructura: {hash_archivo: {"timestamp": datetime, "result_path": str}}
DOCUMENT_CACHE = {}
# Tiempo de expiración del caché en horas
CACHE_EXPIRY_HOURS = 24

# Caché para deduplicación de webhooks
# Estructura: {webhook_id: {"timestamp": datetime, "card_id": str}}
WEBHOOK_CACHE = {}
# Tiempo de expiración de la deduplicación de webhooks (en segundos)
WEBHOOK_DEDUP_EXPIRY = 60  # 1 minuto 

# Sistema de caché para documentos
def get_file_hash(filepath: str) -> str:
    """Calcula el hash MD5 de un archivo para usarlo como clave de caché."""
    try:
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        logger.error(f"Error calculando hash para {filepath}: {e}")
        # En caso de error, devolvemos un hash único basado en nombre y timestamp
        return hashlib.md5(f"{filepath}_{datetime.now().isoformat()}".encode()).hexdigest()

def is_cached_document(filepath: str) -> tuple[bool, Optional[str]]:
    """
    Verifica si un documento ya está en caché.
    Retorna (está_en_caché, ruta_resultado_anterior)
    """
    try:
        file_hash = get_file_hash(filepath)
        
        # Limpiar entradas expiradas
        clean_expired_cache_entries()
        
        if file_hash in DOCUMENT_CACHE:
            cache_entry = DOCUMENT_CACHE[file_hash]
            logger.info(f"Documento encontrado en caché: {filepath} -> {file_hash}")
            return True, cache_entry.get("result_path")
        
        return False, None
    except Exception as e:
        logger.error(f"Error verificando caché para {filepath}: {e}")
        return False, None

def add_to_cache(filepath: str, result_path: str) -> None:
    """Añade un documento procesado a la caché."""
    try:
        file_hash = get_file_hash(filepath)
        DOCUMENT_CACHE[file_hash] = {
            "timestamp": datetime.now(),
            "result_path": result_path
        }
        logger.info(f"Documento añadido a caché: {filepath} -> {file_hash}")
    except Exception as e:
        logger.error(f"Error añadiendo documento a caché {filepath}: {e}")

def clean_expired_cache_entries() -> None:
    """Limpia entradas expiradas del caché."""
    try:
        now = datetime.now()
        expired_keys = []
        
        for file_hash, entry in DOCUMENT_CACHE.items():
            cache_time = entry.get("timestamp")
            if cache_time and (now - cache_time) > timedelta(hours=CACHE_EXPIRY_HOURS):
                expired_keys.append(file_hash)
        
        for key in expired_keys:
            del DOCUMENT_CACHE[key]
            
        if expired_keys:
            logger.info(f"Limpiadas {len(expired_keys)} entradas expiradas de caché")
    except Exception as e:
        logger.error(f"Error limpiando entradas expiradas de caché: {e}")

# Sistema de deduplicación de webhooks
def generate_webhook_id(payload: dict, card_id: str) -> str:
    """Genera un ID único para un webhook basado en su contenido y tarjeta."""
    webhook_data = f"{card_id}_{json.dumps(payload, sort_keys=True)}"
    return hashlib.md5(webhook_data.encode()).hexdigest()

def is_duplicate_webhook(webhook_id: str, card_id: str) -> bool:
    """Verifica si un webhook es duplicado basado en su ID."""
    try:
        clean_expired_webhook_entries()
        
        if webhook_id in WEBHOOK_CACHE:
            webhook_info = WEBHOOK_CACHE[webhook_id]
            elapsed = time.time() - webhook_info.get("timestamp", 0)
            logger.info(f"Webhook duplicado detectado para tarjeta {card_id}, ID: {webhook_id}, hace {elapsed:.2f} segundos")
            return True
        
        # No está en caché, lo añadimos
        WEBHOOK_CACHE[webhook_id] = {
            "timestamp": time.time(),
            "card_id": card_id
        }
        return False
    except Exception as e:
        logger.error(f"Error verificando duplicación de webhook {webhook_id}: {e}")
        return False  # En caso de error, procesamos el webhook

def clean_expired_webhook_entries() -> None:
    """Limpia entradas expiradas del caché de webhooks."""
    try:
        now = time.time()
        expired_keys = []
        
        for webhook_id, entry in WEBHOOK_CACHE.items():
            cache_time = entry.get("timestamp", 0)
            if now - cache_time > WEBHOOK_DEDUP_EXPIRY:
                expired_keys.append(webhook_id)
        
        for key in expired_keys:
            del WEBHOOK_CACHE[key]
            
        if expired_keys:
            logger.info(f"Limpiadas {len(expired_keys)} entradas expiradas de caché de webhooks")
    except Exception as e:
        logger.error(f"Error limpiando entradas expiradas de caché de webhooks: {e}")

# --- Nuevos Modelos Pydantic para el Payload card.move ---

class PhaseInfo(BaseModel):
    id: Union[str, int]  # Acepta tanto strings como integers
    name: str

class CardInfo(BaseModel):
    id: Union[str, int]  # Acepta tanto strings como integers
    title: Optional[str] = None
    pipe_id: Union[str, int]  # Acepta tanto strings como integers

class UserInfo(BaseModel):
    id: Union[str, int]  # Acepta tanto strings como integers
    name: str
    username: Optional[str] = None
    email: Optional[str] = None

class CardMoveData(BaseModel):
    action: str
    from_phase: PhaseInfo = Field(..., alias='from')
    to_phase: PhaseInfo = Field(..., alias='to')
    moved_by: UserInfo
    card: CardInfo

class PipefyWebhookInput(BaseModel):
    data: CardMoveData
    timestamp: Optional[str] = None
    webhook_id: Optional[str] = None

# --------------------------------------------------------

# Aplicación FastAPI
app = FastAPI(
    title="Procesador Pipefy Agentic-Doc v2",
    description="Recibe webhooks card.move de Pipefy, obtiene adjuntos vía GraphQL y los procesa con agentic-doc."
)

async def get_pipefy_attachment_url(card_id: str) -> Optional[str]:
    """Obtiene la URL del adjunto de una tarjeta específica vía GraphQL."""
    if not PIPEFY_TOKEN:
        logger.error(f"PIPEFY_TOKEN no configurado. No se puede obtener detalles para tarjeta {card_id}.")
        return None
    if not ATTACHMENT_FIELD_ID or ATTACHMENT_FIELD_ID == "id_del_campo_adjunto":
         logger.error(f"PIPEFY_ATTACHMENT_FIELD_ID no configurado o sigue con el valor por defecto. No se puede obtener adjunto para tarjeta {card_id}.")
         return None

    headers = {
        "Authorization": f"Bearer {PIPEFY_TOKEN}",
        "Content-Type": "application/json",
    }
    # Primer paso: Obtener los IDs de los adjuntos disponibles para esta tarjeta
    query = f"""
    query GetCardAttachments {{
      card(id: "{card_id}") {{
        attachments {{
          path
          url
        }}
        fields {{
          name
          field {{
            id
          }}
          value
          array_value
        }}
      }}
    }}
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            logger.info(f"Consultando API GraphQL de Pipefy para adjuntos de tarjeta {card_id}...")
            response = await client.post(PIPEFY_GRAPHQL_ENDPOINT, json={'query': query}, headers=headers)
            response.raise_for_status()
            data = response.json()

            if 'errors' in data:
                logger.error(f"Error en GraphQL al obtener adjuntos para tarjeta {card_id}: {data['errors']}")
                return None

            card_data = data.get('data', {}).get('card')
            if not card_data:
                logger.warning(f"No se encontró la tarjeta {card_id} en la respuesta GraphQL.")
                return None
            
            # Primero verificamos si hay attachments directos
            if card_data.get('attachments') and len(card_data['attachments']) > 0:
                for attachment in card_data['attachments']:
                    if attachment.get('url'):
                        logger.info(f"URL de adjunto encontrada para tarjeta {card_id}: {attachment['url']}")
                        return attachment['url']
            
            # Si no hay attachments directos, buscamos en los campos
            if not card_data.get('fields'):
                logger.warning(f"No se encontraron campos para la tarjeta {card_id}.")
                return None

            # Buscar el campo de archivo adjunto por su ID
            for field_info in card_data['fields']:
                field_id = field_info.get('field', {}).get('id')
                if field_id == ATTACHMENT_FIELD_ID:
                    logger.info(f"Campo de adjunto encontrado para tarjeta {card_id}.")
                    
                    # Si hay un valor de array que contiene archivos
                    if field_info.get('array_value') and isinstance(field_info['array_value'], list) and len(field_info['array_value']) > 0:
                        attachment_info = field_info['array_value'][0]
                        logger.info(f"Información de adjunto en array_value: {attachment_info}")
                        # Podría ser una URL directa o un identificador
                        if isinstance(attachment_info, str):
                            if attachment_info.startswith('http'):
                                return attachment_info
                    
                    # Si hay un valor simple que es una URL
                    if isinstance(field_info.get('value'), str) and field_info['value'].startswith('http'):
                        logger.info(f"URL encontrada en 'value' para tarjeta {card_id}.")
                        return field_info['value']
                    
                    logger.warning(f"Campo de adjunto {ATTACHMENT_FIELD_ID} encontrado para tarjeta {card_id}, pero no se pudo extraer URL.")
                    return None

            logger.warning(f"Campo de adjunto con ID '{ATTACHMENT_FIELD_ID}' no encontrado para tarjeta {card_id}.")
            return None

        except httpx.RequestError as e:
            logger.error(f"Error de red llamando a API Pipefy para tarjeta {card_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error inesperado procesando respuesta GraphQL para tarjeta {card_id}: {e}")
            return None

async def get_pipefy_attachment_download_url(attachment_id: str) -> Optional[str]:
    """Obtiene la URL firmada de descarga para un adjunto de Pipefy utilizando su ID."""
    if not PIPEFY_TOKEN:
        logger.error("PIPEFY_TOKEN no configurado. No se puede obtener URL de descarga.")
        return None
    
    headers = {
        "Authorization": f"Bearer {PIPEFY_TOKEN}",
        "Content-Type": "application/json",
    }
    
    # Query GraphQL para obtener la URL de descarga directa usando getPresignedUrl
    query = f"""
    query GetPresignedUrl {{
      getPresignedUrl(input: {{ attachableId: "{attachment_id}" }}) {{
        signedUrl
      }}
    }}
    """
    
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            logger.info(f"Consultando API GraphQL de Pipefy para URL firmada del adjunto: {attachment_id}...")
            response = await client.post(PIPEFY_GRAPHQL_ENDPOINT, json={'query': query}, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if 'errors' in data:
                logger.error(f"Error en GraphQL al obtener URL firmada: {data['errors']}")
                return None
            
            signed_url = data.get('data', {}).get('getPresignedUrl', {}).get('signedUrl')
            if not signed_url:
                logger.warning(f"No se pudo obtener URL firmada para el adjunto {attachment_id}")
                return None
            
            logger.info(f"URL firmada obtenida exitosamente para adjunto {attachment_id}")
            return signed_url
            
        except httpx.RequestError as e:
            logger.error(f"Error de red obteniendo URL firmada para adjunto {attachment_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error inesperado obteniendo URL firmada para adjunto {attachment_id}: {e}")
            return None

async def download_file(attachment_url: str, card_id: str) -> Optional[str]:
    """Descarga un archivo de Pipefy usando la URL del adjunto."""
    if not PIPEFY_TOKEN:
        logger.error("Variable de entorno PIPEFY_TOKEN no configurada.")
        return None
    if not attachment_url:
        logger.warning(f"No se proporcionó URL de adjunto para la tarjeta {card_id}.")
        return None
    
    headers = {"Authorization": f"Bearer {PIPEFY_TOKEN}"}
    local_filepath = None
    
    try:
        # Crear directorio de salida si no existe
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Determinar la extensión del archivo
        try:
            # Intentar extraer la extensión de la URL
            url_parts = attachment_url.split('?')[0].split('/')[-1]
            file_ext = os.path.splitext(url_parts)[1] or ".tmp"
        except Exception:
            file_ext = ".tmp"
            
        temp_filename = f"{card_id}_{uuid.uuid4()}{file_ext}"
        local_filepath = os.path.join(OUTPUT_DIR, temp_filename)

        logger.info(f"Intentando descargar adjunto para tarjeta {card_id} desde {attachment_url} a {local_filepath}")
        
        # Descargar usando la URL
        with requests.get(attachment_url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(local_filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Adjunto descargado exitosamente para tarjeta {card_id} en {local_filepath}")
            return local_filepath

    except requests.exceptions.RequestException as e:
        logger.error(f"Error descargando archivo para tarjeta {card_id}: {e}")
        if local_filepath and os.path.exists(local_filepath):
            os.remove(local_filepath)
        return None
    except Exception as e:
        logger.error(f"Error inesperado durante la descarga para tarjeta {card_id}: {e}")
        if local_filepath and os.path.exists(local_filepath):
            os.remove(local_filepath)
        return None

def save_results(card_id: str, markdown_content: str, chunks: list) -> str:
    """
    Guarda los resultados procesados.
    Retorna la ruta del archivo Markdown generado.
    """
    try:
        logger.info(f"Creando directorio de salida: {OUTPUT_DIR}")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        
        # Verificar que el directorio existe realmente
        if not os.path.exists(OUTPUT_DIR):
            logger.error(f"¡ALERTA! No se pudo crear el directorio {OUTPUT_DIR}")
            # Intentar crear directamente /data
            os.makedirs("/data", exist_ok=True)
            if os.path.exists("/data"):
                logger.info("Directorio /data existe y es accesible")
            else:
                logger.error("¡ALERTA! No se puede acceder al directorio /data")

        md_filename = os.path.join(OUTPUT_DIR, f"{card_id}_extracted.md")
        logger.info(f"Guardando resultados en: {md_filename}")
        
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        
        # Verificar que el archivo se ha creado
        if os.path.exists(md_filename):
            logger.info(f"Archivo guardado exitosamente: {md_filename} ({os.path.getsize(md_filename)} bytes)")
        else:
            logger.error(f"¡ALERTA! No se pudo verificar la existencia del archivo: {md_filename}")
            
        return md_filename

    except Exception as e:
        logger.error(f"Error guardando resultados para tarjeta {card_id}: {e}", exc_info=True)
        return ""

@app.post("/webhook/pipefy")
async def handle_pipefy_webhook(
    payload: PipefyWebhookInput,
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    Recibe notificaciones webhook card.move de Pipefy.
    Obtiene la URL del adjunto vía GraphQL y lo procesa usando agentic-doc.
    """
    # También mantenemos el logging del cuerpo para diagnóstico
    raw_body = await request.body()
    logger.info("--- INICIO RAW BODY RECIBIDO ---")
    try:
        raw_body_str = raw_body.decode('utf-8')
        logger.info(raw_body_str)
        
        # Verificar duplicación del webhook
        card_id = str(payload.data.card.id)
        webhook_id = generate_webhook_id(json.loads(raw_body_str), card_id)
        
        if is_duplicate_webhook(webhook_id, card_id):
            logger.info(f"Omitiendo procesamiento de webhook duplicado para tarjeta {card_id}")
            return {"status": "success", "message": f"Webhook duplicado para tarjeta {card_id}, ignorado", "duplicate": True}
            
    except Exception as e:
        logger.error(f"Error procesando raw body o verificando duplicación: {e}")
        # Continuamos con el procesamiento normal en caso de error
    logger.info("--- FIN RAW BODY RECIBIDO ---")
    
    # Convertir IDs a string si es necesario
    card_id = str(payload.data.card.id)
    logger.info(f"Webhook '{payload.data.action}' recibido para tarjeta ID: {card_id}")

    if PIPEFY_WEBHOOK_SECRET:
        if not authorization:
            logger.warning(f"Falta encabezado de Autorización para tarjeta {card_id}")
            raise HTTPException(status_code=401, detail="Falta encabezado de Autorización")
        if authorization != f"Bearer {PIPEFY_WEBHOOK_SECRET}":
            logger.warning(f"Encabezado de Autorización inválido para tarjeta {card_id}")
            raise HTTPException(status_code=403, detail="Token de autorización inválido")
        logger.info(f"Webhook autenticado exitosamente para tarjeta {card_id}.")
    else:
         logger.warning("PIPEFY_WEBHOOK_SECRET (o RENDER_SERVICE_SECRET) no configurado. El webhook no está protegido.")

    attachment_url = await get_pipefy_attachment_url(card_id)

    if not attachment_url:
        logger.warning(f"No se pudo obtener URL de adjunto para tarjeta {card_id} o no existe. Omitiendo procesamiento del adjunto.")
        return {"status": "success", "message": f"Webhook recibido para tarjeta {card_id}, pero no se procesó adjunto."}

    downloaded_file_path = await download_file(attachment_url, card_id)

    if not downloaded_file_path:
        logger.error(f"Fallo al descargar adjunto desde {attachment_url} para tarjeta {card_id}. Abortando.")
        raise HTTPException(status_code=500, detail="Error al descargar archivo adjunto de Pipefy.")

    try:
        # Verificar caché
        is_cached, cached_result_path = is_cached_document(downloaded_file_path)
        
        if is_cached and cached_result_path and os.path.exists(cached_result_path):
            logger.info(f"Usando resultado en caché para tarjeta {card_id}: {cached_result_path}")
            
            # Copiar resultado cacheado a un nuevo archivo específico para esta tarjeta
            md_filename = os.path.join(OUTPUT_DIR, f"{card_id}_extracted.md")
            with open(cached_result_path, 'r', encoding='utf-8') as src:
                with open(md_filename, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
            
            logger.info(f"Resultado cacheado copiado para tarjeta {card_id} en {md_filename}")
            return {"status": "success", "message": f"Adjunto procesado desde caché para tarjeta {card_id}", "cached": True}
        
        # Si no está en caché, procesar normalmente
        logger.info(f"Iniciando procesamiento con agentic-doc para archivo: {downloaded_file_path}")
        
        if not VISION_AGENT_API_KEY:
            logger.warning("Variable de entorno VISION_AGENT_API_KEY no configurada. agentic-doc podría fallar o tener funcionalidad limitada.")

        results = parse_documents([downloaded_file_path])

        if not results or len(results) == 0:
            logger.error(f"agentic-doc no retornó resultados para {downloaded_file_path}")
            raise HTTPException(status_code=500, detail="El procesamiento con agentic-doc no produjo resultados.")

        parsed_doc = results[0]
        logger.info(f"Documento procesado exitosamente para tarjeta {card_id} con agentic-doc.")

        # Guardar resultados y añadir a caché
        md_filename = save_results(card_id, parsed_doc.markdown, parsed_doc.chunks)
        if md_filename:
            add_to_cache(downloaded_file_path, md_filename)

    except Exception as e:
        logger.error(f"Error durante el procesamiento con agentic-doc o guardando resultados para {downloaded_file_path}: {e}", exc_info=True)
        if downloaded_file_path and os.path.exists(downloaded_file_path):
            try:
                os.remove(downloaded_file_path)
                logger.info(f"Archivo temporal limpiado tras error: {downloaded_file_path}")
            except OSError as rm_err:
                logger.error(f"Error eliminando archivo temporal {downloaded_file_path} tras error: {rm_err}")
        raise HTTPException(status_code=500, detail=f"Error procesando documento: {e}")

    finally:
        if downloaded_file_path and os.path.exists(downloaded_file_path):
            try:
                os.remove(downloaded_file_path)
                logger.info(f"Archivo temporal limpiado al final: {downloaded_file_path}")
            except OSError as e:
                logger.error(f"Error eliminando archivo temporal {downloaded_file_path} al final: {e}")

    logger.info(f"Procesamiento completado exitosamente para tarjeta {card_id}")
    return {"status": "success", "message": f"Adjunto procesado exitosamente para tarjeta {card_id}"}

@app.get("/health")
async def health_check():
    """Endpoint básico de verificación de salud."""
    return {"status": "ok"}

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Manejador personalizado para errores de validación de Pydantic.
    Proporciona un mensaje de error más amigable con detalles específicos.
    """
    logger.error(f"Error de validación: {exc}")
    
    # Formatea los errores
    errors = []
    for error in exc.errors():
        error_loc = " -> ".join([str(loc) for loc in error["loc"]])
        error_msg = error["msg"]
        error_type = error.get("type", "unknown_error")
        errors.append(f"Ubicación: {error_loc}, Error: {error_msg}, Tipo: {error_type}")
    
    error_detail = "\n".join(errors)
    logger.error(f"Detalles del error de validación:\n{error_detail}")
    
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Error al procesar la solicitud del webhook. Por favor, verifique el formato de los datos.",
            "errors": exc.errors(),
            "suggestion": "Asegúrese de que todos los campos del webhook tienen el formato correcto."
        },
    )

@app.get("/archivos")
async def list_files():
    """Endpoint para listar los archivos disponibles en el directorio de salida."""
    try:
        if not os.path.exists(OUTPUT_DIR):
            logger.warning(f"El directorio {OUTPUT_DIR} no existe")
            return {"status": "error", "message": f"El directorio {OUTPUT_DIR} no existe"}
            
        files = []
        for filename in os.listdir(OUTPUT_DIR):
            filepath = os.path.join(OUTPUT_DIR, filename)
            if os.path.isfile(filepath):
                file_info = {
                    "nombre": filename,
                    "tamaño": os.path.getsize(filepath),
                    "modificado": os.path.getmtime(filepath),
                    "ruta": filepath
                }
                files.append(file_info)
                
        # Verifica también el directorio raíz /data por si acaso
        data_files = []
        if os.path.exists("/data") and OUTPUT_DIR != "/data":
            for filename in os.listdir("/data"):
                filepath = os.path.join("/data", filename)
                if os.path.isfile(filepath):
                    file_info = {
                        "nombre": filename,
                        "tamaño": os.path.getsize(filepath),
                        "modificado": os.path.getmtime(filepath),
                        "ruta": filepath
                    }
                    data_files.append(file_info)
                    
        return {
            "status": "success", 
            "archivos": files,
            "archivos_data": data_files if OUTPUT_DIR != "/data" else [],
            "directorio": OUTPUT_DIR,
            "disco_persistente": "/data"
        }
    except Exception as e:
        logger.error(f"Error listando archivos: {e}", exc_info=True)
        return {"status": "error", "message": f"Error listando archivos: {str(e)}"}

@app.get("/archivo/{card_id}")
async def get_file_content(card_id: str):
    """Endpoint para obtener el contenido de un archivo específico."""
    try:
        filename = f"{card_id}_extracted.md"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        if not os.path.exists(filepath):
            logger.warning(f"Archivo no encontrado: {filepath}")
            # Buscar en directorio raíz como plan B
            alt_filepath = os.path.join("/data", filename)
            if os.path.exists(alt_filepath):
                filepath = alt_filepath
                logger.info(f"Archivo encontrado en ruta alternativa: {filepath}")
            else:
                return {"status": "error", "message": "Archivo no encontrado"}
                
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        return {
            "status": "success",
            "card_id": card_id,
            "filename": filename,
            "content": content,
            "filepath": filepath
        }
    except Exception as e:
        logger.error(f"Error leyendo archivo para tarjeta {card_id}: {e}", exc_info=True)
        return {"status": "error", "message": f"Error leyendo archivo: {str(e)}"} 