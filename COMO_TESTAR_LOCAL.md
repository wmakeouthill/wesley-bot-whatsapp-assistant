# Como Testar o Bot Localmente 🚀

Este guia rápido explica como conectar o seu número do WhatsApp Business com o projeto local através da Evolution API e testar o envio de mensagens.

## 1. Subindo a Arquitetura
Certifique-se de que o Docker está aberto e rodando no seu computador (como você já fez!). Em seguida, no terminal da pasta do projeto, execute:
```bash
docker compose up -d
```
*Isso irá inicializar o serviço da Evolution API no seu `localhost:8080` de forma isolada.*

## 2. Ligando o Backend Python
Em outro terminal (com o Docker já rodando), inicie o seu backend em FastAPI pela raiz do projeto:
```bash
poetry run python -m app.main
```
*(Se você estiver usando o Uvicorn diretamente, o comando é `poetry run uvicorn app.main:app --reload`)*

Seu backend agora estará ouvindo na porta `8000`.

## 3. Conectando o WhatsApp (A MáGICA 🪄)

A melhor forma de testar no momento é através da interface Swagger autogerada pelo FastAPI.

1. Abra seu navegador e acesse: [http://localhost:8000/docs](http://localhost:8000/docs)
2. Você verá a seção **`WhatsApp Connection`**.
3. Clique na rota `POST /whatsapp/conectar`.
4. Clique em **"Try it out"** (Tentar) e depois no botão grande azul **"Execute"**.

O processo demorará cerca de 2 segundos. Se der tudo certo, a resposta exibirá um grande texto em `base64`. É o seu **QR Code**. 

### 3.1 Escaneando o QR Code
Como a resposta do Swagger é em texto, você precisa visualizar a imagem para escanear com seu celular:
- Pegue o campo `base64` do JSON gerado.
- Cole em um site conversor gratuito como o [base64-image.de](https://www.base64-image.de/) para visualizar a imagem do QRCode.
- Abra o seu WhatsApp Business (ou padrão) no celular > "Aparelhos Conectados" > Escaneie a engrenagem preta!

Pronto! **"Sessão Conectada!"** aparecerá nos logs.

## 4. Disparando uma Mensagem de Teste

Agora que o celular já está ligado ao "bot_evolution_api", volte ao Swagger ([http://localhost:8000/docs](http://localhost:8000/docs)).

1. Vá até a rota secundária `POST /whatsapp/enviar-teste`
2. Clique em **Try it out** e monte sua mensagem no corpo:
```json
{
  "numero": "5511999999999", 
  "texto": "Testando a conectividade com o meu bot em python limpo!"
}
```
*(Troque `5511...` pelo seu próprio número ou de um amigo. IMPORTANTE: coloque o código do país + DDD, mas **não coloque** o nono dígito em alguns estados se der ERRO, o WhatsApp as vezes quebra isso, mas tente normalmente com 9 primeiro).*

3. Pressione **"Execute"**. Em cerca de `1` segundo, no seu próprio celular, a mensagem aparecerá enviada sozinha!

---

💡 *Nas próximas fases do plano, nós vamos configurar a "Via Oposta": Fazer com que o WhatsApp nos avise (`Webhook`) de novas mensagens para processarmos.*
