import requests
import json
import os

# Consultar el token en GraphiQL
print("Para verificar tus webhooks actuales en Pipefy, sigue estos pasos:")
print("1. Ve a https://app.pipefy.com/graphiql")
print("2. Ejecuta esta consulta (reemplaza EFRxKPhq con tu Pipe ID si es diferente):")
print("""
query GetWebhooks {
  pipe(id: "EFRxKPhq") {
    webhooks {
      id
      name
      url
      actions
      headers
      filters
    }
  }
}
""")
print("\nLuego, verifica si los webhooks tienen configurado el encabezado 'headers'.")
print("Si no tienen headers o no incluyen 'Authorization', debes actualizar el webhook con esta mutación:")
print("""
mutation UpdateWebhook {
  updateWebhook(input: {
    id: "ID_DEL_WEBHOOK"  # Reemplaza con el ID del webhook que quieres actualizar
    headers: "{\\\"Authorization\\\": \\\"Bearer Pipefy17570000\\\"}"  # Este es el token configurado en RENDER_SERVICE_SECRET
  }) {
    webhook {
      id
      name
      headers
    }
  }
}
""")

print("\nAdemás, asegúrate de que estas variables de entorno estén configuradas en Render:")
print("1. PIPEFY_TOKEN - Para acceder a la API de Pipefy")
print("2. RENDER_SERVICE_SECRET (o PIPEFY_WEBHOOK_SECRET) - Para autenticar las llamadas webhook (Configurado como: Pipefy17570000)")
print("3. VISION_AGENT_API_KEY - Para usar agentic-doc")
print("4. PIPEFY_ATTACHMENT_FIELD_ID - El ID del campo donde están los documentos adjuntos")
print("\nTodos estos valores deben coincidir entre Pipefy y Render para que el webhook funcione correctamente.")

# Reemplaza estos valores con los tuyos
PIPEFY_TOKEN = os.getenv("PIPEFY_TOKEN", "REEMPLAZA_CON_TU_TOKEN")  # Tu token de API de Pipefy
PIPE_ID = "EFRxKPhq"  # ID del pipe donde está configurado el webhook

# Consulta GraphQL para obtener los webhooks
query = """
query GetWebhooks {
  pipe(id: "%s") {
    webhooks {
      id
      name
      url
      actions
      headers
      filters
    }
  }
}
""" % PIPE_ID

# Configurar headers
headers = {
    "Authorization": f"Bearer {PIPEFY_TOKEN}",
    "Content-Type": "application/json"
}

# Realizar la solicitud
response = requests.post(
    "https://api.pipefy.com/graphql",
    json={"query": query},
    headers=headers
)

# Procesar la respuesta
if response.status_code == 200:
    data = response.json()
    if "errors" in data:
        print("Error en la consulta GraphQL:", data["errors"])
    else:
        webhooks = data.get("data", {}).get("pipe", {}).get("webhooks", [])
        if not webhooks:
            print("No se encontraron webhooks configurados para este pipe.")
        else:
            print(f"Se encontraron {len(webhooks)} webhook(s):")
            for i, webhook in enumerate(webhooks, 1):
                print(f"\n--- Webhook #{i} ---")
                print(f"ID: {webhook.get('id')}")
                print(f"Nombre: {webhook.get('name')}")
                print(f"URL: {webhook.get('url')}")
                print(f"Acciones: {webhook.get('actions')}")
                
                # Verificar si hay headers configurados
                headers_value = webhook.get('headers')
                if headers_value:
                    try:
                        # Los headers se almacenan como string JSON en Pipefy
                        parsed_headers = json.loads(headers_value)
                        print(f"Headers: {json.dumps(parsed_headers, indent=2)}")
                        
                        # Verificar si existe el header de autenticación
                        auth_header = parsed_headers.get("Authorization")
                        if auth_header:
                            print("✅ El header de Authorization está configurado correctamente.")
                            # Verificar si coincide con el valor esperado
                            if auth_header == "Bearer Pipefy17570000":
                                print("✅ El valor del token coincide con el configurado en Render (Pipefy17570000).")
                            else:
                                print("❌ El token no coincide con el valor configurado en Render (Pipefy17570000).")
                        else:
                            print("❌ No se encontró el header de Authorization.")
                    except json.JSONDecodeError:
                        print(f"Headers (formato no válido): {headers_value}")
                else:
                    print("❌ No hay headers configurados en este webhook.")
                
                # Verificar filtros
                filters_value = webhook.get('filters')
                if filters_value:
                    print(f"Filtros: {filters_value}")
                else:
                    print("No hay filtros configurados.")
else:
    print(f"Error en la solicitud HTTP: {response.status_code}")
    print(response.text)

print("\nSi necesitas actualizar el webhook con los headers correctos, usa esta mutación:")
print("""
mutation UpdateWebhook {
  updateWebhook(input: {
    id: "ID_DEL_WEBHOOK"  # Reemplaza con el ID del webhook que quieres actualizar
    headers: "{\\\"Authorization\\\": \\\"Bearer Pipefy17570000\\\"}"  # Este es el token configurado en RENDER_SERVICE_SECRET
  }) {
    webhook {
      id
      name
      headers
    }
  }
}
""") 