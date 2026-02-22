# 🚀 Guia de Deploy (Oracle Always Free)

A arquitetura do seu robô WhatsApp foi projetada para rodar liso, com pouquíssima RAM, focado no backend em **Python FastAPI**, no **Banco SQLite em arquivo** (dentro do Volume) e na ponte de mensagens **Evolution API**.

## 1. Enviando o código para a Oracle VPS

Você pode mandar pro seu Github e clonar na VPS, ou usar  via SSH:
```bash
git clone <url-do-seu-repo-no-github>
cd wesley-bot-whatsapp-assistant
```

## 2. Inserindo as Senhas (Obrigatório)

No terminal da Oracle, antes de subir tudo, você precisa exportar as duas chaves que farão a mágica. O Docker vai ler essas duas variáveis secretas:

```bash
export GEMINI_API_KEY="SUA_CHAVE_DO_GOOGLE_AI_STUDIO"
```

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
