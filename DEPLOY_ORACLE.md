# 🚀 Guia de Deploy (Oracle Always Free)

A arquitetura do seu robô WhatsApp foi projetada para rodar liso, com pouquíssima RAM, focado no backend em **Python FastAPI**, no **Banco SQLite em arquivo** (dentro do Volume) e na ponte de mensagens **Evolution API**.

## 1. Enviando o código para a Oracle VPS

Você pode mandar pro seu Github e clonar na VPS, ou usar  via SSH:
```bash
git clone <url-do-seu-repo-no-github>
cd wesley-bot-whatsapp-assistant
```

## 2. Inserindo as Senhas (Segurança)

Em vez de jogar as chaves diretamente no terminal como variáveis flutuantes, a forma mais segura na Oracle é criar o arquivo `.env`. Este arquivo já foi devidamente ignorado e não subiu para o git (como checamos anteriormente).

Você pode criar esse arquivo diretamente pelo terminal da Oracle usando o comando `echo` passando as suas chaves reais:

```bash
echo "GEMINI_API_KEY=sua_chave_real_do_google_ai_aqui
EVOLUTION_API_KEY=crie_uma_senha_forte_aqui_para_blindar_sua_evolution" > .env
```

O arquivo ` .env` será criado instantaneamente com os dados dentro. O Docker injetará essas credenciais de forma segura dentro dos contêineres no momento da execução!

## 3. Rodando NATIVAMENTE pelo Docker

Com todo o código no Linux da Oracle, nós vamos pedir pro Docker **Buildar** o container Python na hora lendo o seu `Dockerfile`, e depois acionar a Evolution API:

```bash
docker compose up -d --build
```
> Obs: Como é uma máquina pequena, a primeira "build" (instalação das dezenas de bibliotecas do Python) pode demorar alguns minutinhos. Deixe rodar.

## 4. Testando Logado
1. Acesse o IP Público da sua Oracle Cloud na porta 8000 (Ex: `http://198.11.22.33:8000/docs`).
2. Vá em `/whatsapp/conectar` como você testou localmente e capture o "Base64" gerado no Swagger para escanear com seu celular.

## 5. (Passo Final) Configurando o Webhook

A Evolution API precisa saber para onde mandar as mensagens quando seu público falar com você no celular! 
*O seu Backend FastApi (serviço `bot_api`) roda dentro do mesmo ambiente de rede do Docker que a `Evolution_api`.* 

Basta você avisá-la que a URL interna do Webhook é:
**`http://bot_api:8000/webhooks/evolution`**

Você pode colar o código cUrl num terminal para configurar a Evolution na porta dela (8080):

```bash
curl --request POST \
  --url http://localhost:8080/webhook/set/wesley_bot_session \
  --header 'apikey: B7F499252EE14C8AAA0BA53ED71C0F73' \
  --header 'content-type: application/json' \
  --data '{
    "webhook": {
      "enabled": true,
      "url": "http://bot_api:8000/webhooks/evolution",
      "byEvents": false,
      "base64": false,
      "events": [
        "MESSAGES_UPSERT"
      ]
    }
}'
```

🎉 **PRONTO!** TUDO 100% ONLINE E ASSISTENTE INTELIGENTE! O Robô do Wesley receberá a mensagem vinda do Node da Evolution API, passará na rede interna para o Python, o Python rodará o RAG consultando seus Certificados lidos no start pelo LangChain/Faiss e disparará de volta para o Bot Node avisando o app do WhatsApp!

---

## 6. Configurando o Segundo Número (Número Pessoal)

O bot suporta **duas instâncias** da Evolution API. A segunda usa uma personalidade informal, como se fosse o próprio Wesley respondendo.

### 6.1 — Crie a segunda instância

```bash
curl --request POST \
  --url http://localhost:8080/instance/create \
  --header 'apikey: SUA_EVOLUTION_API_KEY' \
  --header 'content-type: application/json' \
  --data '{
    "instanceName": "wesley_bot_pessoal",
    "qrcode": true,
    "integration": "WHATSAPP-BAILEYS",
    "webhook": {
      "enabled": true,
      "url": "http://bot_api:8000/webhooks/evolution",
      "byEvents": false,
      "base64": false,
      "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"]
    }
  }'
```

### 6.2 — Pegue o QR Code e conecte

```bash
curl http://localhost:8080/instance/connect/wesley_bot_pessoal \
  --header 'apikey: SUA_EVOLUTION_API_KEY'
```

Abra o WhatsApp do número pessoal → Aparelhos conectados → escaneie o QR.

### 6.3 — Adicione ao `.env` da VPS

```bash
EVOLUTION_INSTANCE_TWO_NAME=wesley_bot_pessoal
INSTANCE_TWO_OWNER_JID=5521983866676@s.whatsapp.net
OWNER_JID=5521983866676@s.whatsapp.net
```

### 6.4 — Reinicie o bot

```bash
docker compose restart api
```

---

## 7. Controlando a IA por chat (Comandos /ia)

No WhatsApp do número dono do bot, vá em **"Mensagens Salvas"** e envie:

| Comando | O que faz |
|---|---|
| `/ia off` | Desativa IA para todos os chats |
| `/ia on` | Reativa IA para todos |
| `/ia off 5511999999999` | Desativa só para esse número |
| `/ia on 5511999999999` | Ativa só para esse número |
| `/ia lista` | Lista últimas 10 conversas com status ✅/🔴 |
| `/ia status` | Mostra status global da instância |
| `/ia resetar 5511999999999` | Remove override individual |

### Allowlist / Blocklist (`.env`)

```bash
IA_ALLOWLIST=5521999999999,5511888888888  # Só esses respondem (vazio = todos)
IA_BLOCKLIST=5521000000000               # Esses nunca respondem
```
