import requests
import json
import os

print("=== TEST DE WEBHOOK DE PIPEFY EN RENDER ===")

# URL del servidor en Render (usando directamente la URL proporcionada)
RENDER_URL = "https://pipefy-agentic-processor.onrender.com/webhook/pipefy"
print(f"Usando URL: {RENDER_URL}")

# Token de autorización
AUTH_TOKEN = "Pipefy17570000"  # Valor proporcionado por el usuario

# Cabeceras de la solicitud
headers = {
    "Authorization": f"Bearer {AUTH_TOKEN}",
    "Content-Type": "application/json"
}

# Simular un payload de card.move
payload = {
    "data": {
        "action": "card.move",
        "from": {
            "id": "123",
            "name": "Fase 1"
        },
        "to": {
            "id": "338000020", # ID de la fase configurada en el webhook
            "name": "Fase de procesamiento"
        },
        "moved_by": {
            "id": 12345,
            "name": "Usuario de Prueba",
            "username": "usuario_prueba",
            "email": "usuario@ejemplo.com"
        },
        "card": {
            "id": "67890",
            "title": "Tarjeta de Prueba",
            "pipe_id": "306294445" # ID real del pipe
        }
    }
}

print("\n1. Enviando solicitud al webhook con:")
print(f"  - URL: {RENDER_URL}")
print(f"  - Token de autorización: Bearer {AUTH_TOKEN}")
print(f"  - Tipo de evento: {payload['data']['action']}")
print(f"  - ID de tarjeta: {payload['data']['card']['id']}")

try:
    # Realizar la solicitud POST
    print("\n2. Respuesta del servidor:")
    print("  Envío de solicitud...")
    
    response = requests.post(RENDER_URL, json=payload, headers=headers, timeout=10)
    
    print(f"  - Código de estado: {response.status_code}")
    print(f"  - Cabeceras de respuesta: {dict(response.headers)}")
    
    # Intentar parsear respuesta como JSON
    try:
        response_json = response.json()
        print(f"  - Respuesta JSON: {json.dumps(response_json, indent=2)}")
    except json.JSONDecodeError:
        print(f"  - Cuerpo de respuesta: {response.text[:500]}")
        if len(response.text) > 500:
            print("    (respuesta truncada a 500 caracteres)")

    # Evaluación de la respuesta
    print("\n3. Evaluación:")
    if response.status_code >= 200 and response.status_code < 300:
        print("  ✅ El servidor respondió con éxito (código 2xx)")
        print("  ✅ El webhook parece estar funcionando correctamente")
    else:
        print("  ❌ El servidor respondió con error")
        if response.status_code == 401:
            print("  ❌ Error de autenticación. Verifica que el token de autorización sea correcto")
        elif response.status_code == 404:
            print("  ❌ Endpoint no encontrado. Verifica la URL del webhook")
        else:
            print(f"  ❌ Error desconocido (código {response.status_code})")

except requests.exceptions.ConnectionError:
    print("  ❌ No se pudo conectar al servidor. Verifica que la URL sea correcta y el servidor esté en línea")
except requests.exceptions.Timeout:
    print("  ❌ Tiempo de espera agotado. El servidor está tardando demasiado en responder")
except Exception as e:
    print(f"  ❌ Error inesperado: {str(e)}")

print("\n=== FIN DEL TEST ===") 