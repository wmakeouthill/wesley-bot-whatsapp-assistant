import logging
from typing import Optional
from app.domain.schemas.webhook import WebhookBody
from app.infrastructure.external.evolution_client import EvolutionClient
from app.domain.services.rag_service import PortfolioRAG
from google import genai
from app.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)

class AtendimentoService:
    """Serviço Orquestrador do fluxo conversacional"""
    
    def __init__(self, evolution_client: EvolutionClient):
        self.evolution_client = evolution_client
        self.rag = PortfolioRAG()
        self.rag.initialize_or_build()
        self.llm_client = genai.Client(api_key=settings.gemini_api_key)
        
    async def processar_webhook(self, body: WebhookBody) -> None:
        """Ponto de entrada do Webhook."""
        
        # Ignora status de mensagens como 'lido' ou 'recebido' 
        # e foca apenas em 'messages.upsert'
        if body.event != "messages.upsert":
            return
            
        # Ignora mensagens enviadas pelo próprio bot ('fromMe': true)
        if body.data.key.fromMe:
            return
            
        telefone = body.data.key.remoteJid.split('@')[0]
        nome_cliente = body.data.pushName or "Cliente"
        id_mensagem = body.data.key.id
        
        texto_recebido = self._extrair_texto(body)
        if not texto_recebido:
            return
            
        logger.info(f"[{telefone} / {nome_cliente}]: {texto_recebido}")
        
        # 1. Puxa contexto do RAG local via similaridade (FAISS)
        contexto = self.rag.retrieve(texto_recebido, top_k=3)
        
        # 2. Monta Prompt final (Para o bot ser um assistente do Wesley)
        prompt = f"""
Você é o Assistente Virtual Oficial do Wesley no WhatsApp.
Seja amigável, direto, e natural em suas respostas. O usuário se chama {nome_cliente}.
O usuário enviou a seguinte mensagem: "{texto_recebido}"

Abaixo está o CONTEXTO contendo as informações sobre os certificados, habilidades e currículo do Wesley.
Baseado ESTREITAMENTE nesse contexto, responda a pergunta do usuário.
Se a informação não estiver no contexto, diga que você vai anotar a dúvida para o próprio Wesley responder depois, e NUNCA invente informações.

CONTEXTO DEDUZIDO DO PORTFÓLIO:
{contexto}
"""
        # 3. Manda para a Gemini gerar a resposta
        try:
            response = self.llm_client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
            )
            resposta_ia = response.text
        except Exception as e:
            logger.error(f"Erro chamando IA: {e}")
            resposta_ia = "Ops, dei uma travadinha processando seu portfólio. Manda de novo?"
        
        # Envia a resposta final para o cliente
        await self.evolution_client.send_text_message(telefone, resposta_ia)
        
    def _extrair_texto(self, body: WebhookBody) -> Optional[str]:
        """Tenta achar texto em mensagem simples ou formatada."""
        msg_obj = body.data.message
        if not msg_obj:
            return None
            
        if msg_obj.conversation:
            return msg_obj.conversation
            
        if msg_obj.extendedTextMessage and "text" in msg_obj.extendedTextMessage:
            return msg_obj.extendedTextMessage["text"]
            
        return None
