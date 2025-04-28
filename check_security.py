import os
from dotenv import load_dotenv

# Cargar variables de entorno si existe un archivo .env
load_dotenv()

print("=== VERIFICACIÓN DE SEGURIDAD DEL WEBHOOK DE PIPEFY ===")

# Comprobar configuración de variables de entorno en el sistema
pipefy_token = os.getenv("PIPEFY_TOKEN")
render_service_secret = os.getenv("RENDER_SERVICE_SECRET")
pipefy_webhook_secret = os.getenv("PIPEFY_WEBHOOK_SECRET")
vision_agent_api_key = os.getenv("VISION_AGENT_API_KEY")
attachment_field_id = os.getenv("PIPEFY_ATTACHMENT_FIELD_ID")

print("\n1. Verificando variables de entorno:")
print(f"  - PIPEFY_TOKEN: {'Configurado ✅' if pipefy_token else 'No configurado ❌'}")
print(f"  - RENDER_SERVICE_SECRET: {'Configurado ✅' if render_service_secret else 'No configurado ❌'}")
print(f"  - PIPEFY_WEBHOOK_SECRET: {'Configurado ✅' if pipefy_webhook_secret else 'No configurado ❌'}")
print(f"  - VISION_AGENT_API_KEY: {'Configurado ✅' if vision_agent_api_key else 'No configurado ❌'}")
print(f"  - PIPEFY_ATTACHMENT_FIELD_ID: {'Configurado ✅' if attachment_field_id and attachment_field_id != 'id_del_campo_adjunto' else 'No configurado o valor por defecto ❌'}")

print("\n2. Verificando congruencia entre variables:")
webhook_secret = render_service_secret or pipefy_webhook_secret
if webhook_secret:
    print(f"  - Valor de secreto para autenticación de webhook: {webhook_secret}")
    
    if webhook_secret == "Pipefy17570000":
        print("  - ✅ El secreto coincide con el valor esperado (Pipefy17570000)")
    else:
        print("  - ❌ El secreto NO coincide con el valor esperado (Pipefy17570000)")
else:
    print("  - ❌ No hay secreto configurado para la autenticación del webhook")

print("\n3. Recomendaciones:")
if not pipefy_token:
    print("  - ❌ Configure PIPEFY_TOKEN para poder acceder a la API de Pipefy")

if not webhook_secret:
    print("  - ❌ Configure RENDER_SERVICE_SECRET o PIPEFY_WEBHOOK_SECRET con el valor 'Pipefy17570000'")
elif webhook_secret != "Pipefy17570000":
    print(f"  - ❌ Actualice el valor de {'RENDER_SERVICE_SECRET' if render_service_secret else 'PIPEFY_WEBHOOK_SECRET'} a 'Pipefy17570000'")

if not vision_agent_api_key:
    print("  - ❌ Configure VISION_AGENT_API_KEY para usar agentic-doc")

if not attachment_field_id or attachment_field_id == "id_del_campo_adjunto":
    print("  - ❌ Configure PIPEFY_ATTACHMENT_FIELD_ID con el ID correcto del campo de adjuntos")

print("\n4. Estado del servidor de webhook:")
print("  - URL del webhook: /webhook/pipefy")
print("  - Método: POST")
print("  - Cabecera de autenticación esperada: Authorization: Bearer Pipefy17570000")

print("\n5. Configuración en Pipefy:")
print("Asegúrese de que el webhook en Pipefy:")
print("  - Apunte a la URL correcta del servidor de Render")
print("  - Tenga configurada la cabecera 'Authorization: Bearer Pipefy17570000'")
print("  - Esté configurado para escuchar los eventos relevantes (card.move, etc.)")

print("\n=== FIN DE LA VERIFICACIÓN ===") 