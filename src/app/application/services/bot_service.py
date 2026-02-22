import logging
from typing import Optional
from app.domain.schemas.webhook import WebhookBody
from app.infrastructure.external.evolution_client import EvolutionClient
from app.domain.services.rag_service import PortfolioRAG
from google import genai
from app.infrastructure.config.settings import settings
import base64
import io
import openpyxl
from gtts import gTTS

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
            
        # Usa o sender do topo do payload (JID do remetente na API v2)
        # remoteJid pode ser ID de grupo; sender é sempre o número real
        remote_jid = body.data.key.remoteJid
        if '@g.us' in remote_jid:
            # Mensagem de grupo - por ora ignora
            logger.info(f"Mensagem de grupo ignorada: {remote_jid}")
            return
        telefone = body.sender.split('@')[0] if '@' in body.sender else body.sender
        if not telefone:
            telefone = remote_jid.split('@')[0]
        nome_cliente = body.data.pushName or "Cliente"
        id_mensagem = body.data.key.id
        
        texto_recebido = self._extrair_texto(body)
        if not texto_recebido:
            return
            
        logger.info(f"[{telefone} / {nome_cliente}]: {texto_recebido}")
        
        # EASTER EGGS - Testando planilhas e áudio dinâmicos!
        texto_lower = texto_recebido.lower()
        if "mandar áudio" in texto_lower or "mandar audio" in texto_lower:
            await self._enviar_audio_teste(telefone, nome_cliente)
            return
            
        if "criar planilha" in texto_lower:
            await self._enviar_planilha_teste(telefone, nome_cliente)
            return

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
        try:
            await self.evolution_client.send_text_message(telefone, resposta_ia)
        except Exception as e:
            logger.error(f"Erro ao enviar resposta para {telefone}: {e}")
        
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

    async def _enviar_audio_teste(self, telefone: str, nome: str):
        """Usa Google TTS para gerar voz de baixa latência em RAM"""
        mensagem = f"Claro, {nome}! Eu sou um robô que economiza sua memória e consigo te mandar um áudio da Oracle em tempo real."
        logger.info(f"Gerando áudio TTS para {telefone}...")
        
        tts = gTTS(text=mensagem, lang='pt', slow=False)
        audio_io = io.BytesIO()
        tts.write_to_fp(audio_io)
        audio_io.seek(0)
        
        base64_audio = base64.b64encode(audio_io.read()).decode('utf-8')
        base16_header = f"data:audio/mp3;base64,{base64_audio}"
        await self.evolution_client.send_base64_audio(telefone, base16_header)
        
    async def _enviar_planilha_teste(self, telefone: str, nome: str):
        """Usa OpenPyXL para gerar uma tabela Excel limpa em RAM"""
        logger.info(f"Gerando planilha em memória para {telefone}...")
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Relatório Oracle"
        
        ws.append(["Nome do Servidor", "RAM", "Uso CPU", "Status"])
        ws.append(["Oracle A1", "1 GB (Usado)", "5%", "Online"])
        ws.append(["Evolution API", "Dispensada", "0%", "Offline (Storage Mode)"])
        ws.append(["Faiss RAG", "2 MB", "1%", "Leve e Rápido"])
        
        excel_io = io.BytesIO()
        wb.save(excel_io)
        excel_io.seek(0)
        
        base64_excel = base64.b64encode(excel_io.read()).decode('utf-8')
        base16_header = f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{base64_excel}"
        await self.evolution_client.send_base64_document(telefone, base16_header, "Resumo_Performance.xlsx")
