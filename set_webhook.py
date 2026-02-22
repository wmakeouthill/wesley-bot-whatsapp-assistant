import urllib.request, json, urllib.error

data = json.dumps({
    "webhook": {
        "enabled": True,
        "url": "http://163.176.194.195:8000/webhooks/evolution",
        "byEvents": False,
        "base64": False,
        "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"]
    }
}).encode()

# Verificar webhook atual
req_get = urllib.request.Request(
    "http://localhost:8080/webhook/find/wesley_bot_session",
    headers={"apikey": "Angel2008pam1202@.!!"},
    method="GET"
)
try:
    r = urllib.request.urlopen(req_get)
    print("Webhook atual:", r.read().decode())
except Exception as e:
    print("GET error:", e)

# Configurar webhook
req = urllib.request.Request(
    "http://localhost:8080/webhook/set/wesley_bot_session",
    data=data,
    headers={"Content-Type": "application/json", "apikey": "Angel2008pam1202@.!!"},
    method="POST"
)
try:
    r = urllib.request.urlopen(req)
    print("OK:", r.read().decode())
except urllib.error.HTTPError as e:
    print("ERRO body:", e.read().decode())
except Exception as e:
    print("ERRO:", e)
