# Procesador Pipefy Agentic-Doc

Este servicio procesa documentos adjuntos de Pipefy usando agentic-doc cuando las tarjetas son movidas entre fases específicas.

## Requisitos

- Python 3.10 o superior
- Cuenta en Render.com
- Token de API de Pipefy
- Clave de API de Vision Agent
- Disco persistente en Render (para almacenar resultados)

## Variables de Entorno Requeridas

- `PIPEFY_TOKEN`: Token de API de Pipefy
- `VISION_AGENT_API_KEY`: Clave de API de Vision Agent
- `RENDER_SERVICE_SECRET`: Secreto compartido para autenticación del webhook (opcional)

## Configuración Local

1. Clonar el repositorio
2. Crear un archivo `.env` en la raíz del proyecto con las variables de entorno requeridas
3. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Ejecutar el servidor:
   ```bash
   uvicorn main:app --reload
   ```

## Configuración en Render

1. Crear nuevo Web Service
2. Conectar con el repositorio
3. Configurar:
   - Runtime: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Configurar variables de entorno
5. Añadir disco persistente en `/data`

## Configuración del Webhook en Pipefy

1. Ir a Automatizaciones en Pipefy
2. Crear nueva automatización:
   - Trigger: "Cuando una tarjeta es movida"
   - Fase origen: ID 338000016
   - Fase destino: ID 338000020
   - Acción: HTTP Request
   - Método: POST
   - URL: `https://tu-servicio.onrender.com/webhook/pipefy`
   - Headers:
     ```
     Content-Type: application/json
     Authorization: Bearer TU_RENDER_SERVICE_SECRET
     ```
   - Body:
     ```json
     {
       "card_id": "{{card.id}}",
       "card_title": "{{card.title}}",
       "moved_to_phase_name": "{{card.current_phase.name}}",
       "moved_to_phase_id": "{{card.current_phase.id}}",
       "pipe_id": "{{card.pipe.id}}",
       "attachment_url": "{{card.attachments[0].signedUrl}}"
     }
     ```

## Endpoints

- `POST /webhook/pipefy`: Endpoint principal para recibir webhooks de Pipefy
- `GET /health`: Endpoint de verificación de salud

## Estructura de Archivos

```
.
├── main.py           # Código principal del servidor
├── requirements.txt  # Dependencias del proyecto
├── .env             # Variables de entorno (local)
└── README.md        # Este archivo
```

## Logs y Monitoreo

- Los logs incluyen información detallada sobre cada paso del proceso
- Usar la sección de Logs en Render para monitorear la actividad
- Los errores son registrados con nivel ERROR para fácil identificación

## Manejo de Errores

- Validación de payload del webhook
- Verificación de autenticación
- Manejo de errores en descarga de archivos
- Limpieza de archivos temporales
- Registro detallado de errores

## Seguridad

- Autenticación opcional del webhook con secreto compartido
- Uso seguro de variables de entorno
- Limpieza automática de archivos temporales
- No se almacenan archivos originales, solo resultados procesados 