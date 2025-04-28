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

# Configuración
load_dotenv()
PIPEFY_TOKEN = os.getenv("PIPEFY_TOKEN")
VISION_AGENT_API_KEY = os.getenv("VISION_AGENT_API_KEY")
PIPEFY_WEBHOOK_SECRET = os.getenv("RENDER_SERVICE_SECRET")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data/output")
PIPEFY_GRAPHQL_ENDPOINT = "https://api.pipefy.com/graphql"
ATTACHMENT_FIELD_ID = os.getenv("PIPEFY_ATTACHMENT_FIELD_ID", "id_del_campo_adjunto")

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
    query = f"""
    query GetCardAttachmentUrl {{
      card(id: "{card_id}") {{
        fields(id: "{ATTACHMENT_FIELD_ID}") {{
          name
          value
          url_value
          array_value
        }}
      }}
    }}
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            logger.info(f"Consultando API GraphQL de Pipefy para adjunto de tarjeta {card_id} (campo: {ATTACHMENT_FIELD_ID})...")
            response = await client.post(PIPEFY_GRAPHQL_ENDPOINT, json={'query': query}, headers=headers)
            response.raise_for_status()
            data = response.json()

            if 'errors' in data:
                logger.error(f"Error en GraphQL al obtener adjunto para tarjeta {card_id}: {data['errors']}")
                return None

            card_data = data.get('data', {}).get('card')
            if not card_data or not card_data.get('fields'):
                logger.warning(f"No se encontraron campos o la tarjeta {card_id} en la respuesta GraphQL.")
                return None

            base_url_pipefy = "https://app.pipefy.com"
            for field_info in card_data['fields']:
                 if field_info.get('url_value'):
                     logger.info(f"URL encontrada en 'url_value' para tarjeta {card_id}.")
                     return field_info['url_value']
                 if isinstance(field_info.get('value'), str) and field_info['value'].startswith('http'):
                      logger.info(f"URL encontrada en 'value' para tarjeta {card_id}.")
                      return field_info['value']
                 if field_info.get('array_value') and isinstance(field_info['array_value'], list) and len(field_info['array_value']) > 0:
                     relative_path = field_info['array_value'][0]
                     if isinstance(relative_path, str):
                         if relative_path.startswith('http'):
                             logger.info(f"URL absoluta encontrada en 'array_value' para tarjeta {card_id}.")
                             return relative_path
                         elif '/' in relative_path:
                             full_url = f"{base_url_pipefy}{relative_path if relative_path.startswith('/') else '/' + relative_path}"
                             logger.info(f"URL relativa construida desde 'array_value' para tarjeta {card_id}: {full_url}")
                             return full_url
                 logger.warning(f"Campo de adjunto {ATTACHMENT_FIELD_ID} encontrado para tarjeta {card_id}, pero no se pudo extraer una URL válida de: {field_info}")
                 return None

            logger.warning(f"Campo de adjunto con ID '{ATTACHMENT_FIELD_ID}' no encontrado para tarjeta {card_id}.")
            return None

        except httpx.RequestError as e:
            logger.error(f"Error de red llamando a API Pipefy para tarjeta {card_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error inesperado procesando respuesta GraphQL para tarjeta {card_id}: {e}")
            return None

def download_file(url: str, card_id: str) -> Optional[str]:
    """Descarga un archivo desde una URL (puede ser firmada o no)."""
    if not PIPEFY_TOKEN:
        logger.error("Variable de entorno PIPEFY_TOKEN no configurada.")
        return None
    if not url:
        logger.warning(f"No se proporcionó URL de adjunto para la tarjeta {card_id}.")
        return None
        
    headers = {"Authorization": f"Bearer {PIPEFY_TOKEN}"}
    local_filepath = None
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        try:
             file_ext = os.path.splitext(url.split('?')[0].split('/')[-1])[1] or ".tmp"
        except Exception:
             file_ext = ".tmp"
        temp_filename = f"{card_id}_{uuid.uuid4()}{file_ext}"
        local_filepath = os.path.join(OUTPUT_DIR, temp_filename)

        logger.info(f"Intentando descargar adjunto para tarjeta {card_id} desde {url} a {local_filepath}")
        with requests.get(url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(local_filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Adjunto descargado exitosamente para tarjeta {card_id} en {local_filepath}")
            return local_filepath

    except requests.exceptions.RequestException as e:
        logger.error(f"Error descargando archivo para tarjeta {card_id} desde {url}: {e}")
        if local_filepath and os.path.exists(local_filepath):
            os.remove(local_filepath)
        return None
    except Exception as e:
        logger.error(f"Error inesperado durante la descarga para tarjeta {card_id}: {e}")
        if local_filepath and os.path.exists(local_filepath):
            os.remove(local_filepath)
        return None

def save_results(card_id: str, markdown_content: str, chunks: list):
    """Guarda los resultados procesados."""
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        md_filename = os.path.join(OUTPUT_DIR, f"{card_id}_extracted.md")
        with open(md_filename, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Resultados Markdown guardados para tarjeta {card_id} en {md_filename}")

    except Exception as e:
        logger.error(f"Error guardando resultados para tarjeta {card_id}: {e}")

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
        logger.info(raw_body.decode('utf-8'))
    except Exception as e:
        logger.error(f"Error decodificando body como UTF-8: {e}")
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

    downloaded_file_path = download_file(attachment_url, card_id)

    if not downloaded_file_path:
        logger.error(f"Fallo al descargar adjunto desde {attachment_url} para tarjeta {card_id}. Abortando.")
        raise HTTPException(status_code=500, detail="Error al descargar archivo adjunto de Pipefy.")

    try:
        logger.info(f"Iniciando procesamiento con agentic-doc para archivo: {downloaded_file_path}")
        
        if not VISION_AGENT_API_KEY:
            logger.warning("Variable de entorno VISION_AGENT_API_KEY no configurada. agentic-doc podría fallar o tener funcionalidad limitada.")

        results = parse_documents([downloaded_file_path])

        if not results or len(results) == 0:
            logger.error(f"agentic-doc no retornó resultados para {downloaded_file_path}")
            raise HTTPException(status_code=500, detail="El procesamiento con agentic-doc no produjo resultados.")

        parsed_doc = results[0]
        logger.info(f"Documento procesado exitosamente para tarjeta {card_id} con agentic-doc.")

        save_results(card_id, parsed_doc.markdown, parsed_doc.chunks)

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