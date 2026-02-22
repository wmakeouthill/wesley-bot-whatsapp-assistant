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
            
        # Em mensagens com LID (@lid), resolver para número real via banco da Evolution
        # Em mensagens de grupo (@g.us), ignorar por ora
        # Em mensagens normais (@s.whatsapp.net), usar só o número
        remote_jid = body.data.key.remoteJid
        if '@g.us' in remote_jid:
            logger.info(f"Mensagem de grupo ignorada: {remote_jid}")
            return
        elif '@lid' in remote_jid:
            # Evolution API v2.3.7+ resolve @lid internamente no envio — passa o JID completo
            telefone = remote_jid
        else:
            # @s.whatsapp.net: extrair só o número
            telefone = remote_jid.split('@')[0]
        nome_cliente = body.data.pushName or "Cliente"
        id_mensagem = body.data.key.id
        
        texto_recebido = self._extrair_texto(body)
        if not texto_recebido:
            return
            
        logger.info(f"[{telefone} / {nome_cliente}]: {texto_recebido}")
        
        texto_lower = texto_recebido.lower()

        # ---------------------------------------------------------------
        # Detecção de FORMATO agêntico
        # Regras: palavra de formato OBRIGATÓRIA para evitar falsos positivos.
        # "fala", "fale", "falar" são verbos comuns em PT — NÃO são sinal de áudio
        # sozinhos. Requer "áudio", "audio", "voz" ou "voice" explícito.
        # "tabela" sozinha pode ser parte de pergunta normal; exige verbo de ação.
        # ---------------------------------------------------------------
        _FORMATO_AUDIO = {"áudio", "audio", "voz", "voice"}
        _FORMATO_PLANILHA = {"planilha", "excel", "spreadsheet", "xlsx", "xls"}
        _VERBOS_ACAO = {"manda", "mandar", "envia", "enviar", "me manda", "me envia",
                        "gera", "gerar", "cria", "criar", "faz", "fazer", "quero",
                        "preciso", "pode", "consegue", "testa", "teste"}

        _quer_audio = any(k in texto_lower for k in _FORMATO_AUDIO)
        _quer_planilha = any(k in texto_lower for k in _FORMATO_PLANILHA) or (
            "tabela" in texto_lower and any(v in texto_lower for v in _VERBOS_ACAO)
        )

        # ---------------------------------------------------------------
        # Extrai o tópico real removendo os indicadores de formato da query
        # antes de ir ao RAG, evitando poluir os embeddings com "áudio", "planilha" etc.
        # ---------------------------------------------------------------
        _REMOVER_DA_QUERY = _FORMATO_AUDIO | _FORMATO_PLANILHA | {
            "me envia", "me manda", "me envie", "me mande",
            "manda", "envia", "gera", "cria", "faz",
            "em formato de", "em formato", "como", "no formato",
            "por favor", "pfv", "pf",
        }
        topico_query = texto_lower
        for rem in _REMOVER_DA_QUERY:
            topico_query = topico_query.replace(rem, " ")
        topico_query = " ".join(topico_query.split()).strip() or texto_recebido

        logger.info(f"RAG query topic: '{topico_query}' (audio={_quer_audio}, planilha={_quer_planilha})")

        # 1. Contexto RAG com top_k dinâmico — usa o tópico sem ruído de formato
        contexto_rag = self.rag.retrieve_smart(topico_query)

        # 2. Injeta markdown completo do projeto se mencionado (on-demand)
        projeto_md = self.rag.load_project_if_mentioned(topico_query)
        if projeto_md:
            contexto = projeto_md + "\n---\n" + contexto_rag
        else:
            contexto = contexto_rag

        if _quer_planilha:
            await self._responder_como_planilha(telefone, nome_cliente, texto_recebido, contexto)
            return

        if _quer_audio:
            await self._responder_como_audio(telefone, nome_cliente, texto_recebido, contexto)
            return

        # Resposta em texto normal — usa texto_recebido original no Gemini (contexto completo)
        resposta_ia = await self._gerar_resposta_texto(nome_cliente, texto_recebido, contexto)
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

    async def _gerar_resposta_texto(self, nome_cliente: str, texto: str, contexto: str) -> str:
        """Gera resposta em texto via Gemini com contexto RAG."""
        prompt = f"""
Você é o Assistente Virtual Oficial do Wesley no WhatsApp.
Seja amigável, direto, e natural em suas respostas. O usuário se chama {nome_cliente}.
O usuário enviou a seguinte mensagem: "{texto}"

Abaixo está o CONTEXTO contendo as informações sobre os certificados, habilidades e currículo do Wesley.
Baseado ESTREITAMENTE nesse contexto, responda a pergunta do usuário.
Se a informação não estiver no contexto, diga que você vai anotar a dúvida para o próprio Wesley responder depois, e NUNCA invente informações.

CONTEXTO DEDUZIDO DO PORTFÓLIO:
{contexto}
"""
        try:
            response = self.llm_client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
            )
            return response.text
        except Exception as e:
            logger.error(f"Erro chamando IA: {e}")
            return "Ops, dei uma travadinha processando seu portfólio. Manda de novo?"

    async def _responder_como_audio(self, telefone: str, nome: str, texto: str, contexto: str):
        """Gera resposta via RAG+Gemini e envia como áudio de voz (TTS)."""
        resposta_texto = await self._gerar_resposta_texto(nome, texto, contexto)
        logger.info(f"Gerando áudio TTS para {telefone}: {resposta_texto[:60]}...")
        try:
            tts = gTTS(text=resposta_texto, lang='pt', slow=False)
            audio_io = io.BytesIO()
            tts.write_to_fp(audio_io)
            audio_io.seek(0)
            b64 = base64.b64encode(audio_io.read()).decode('utf-8')
            await self.evolution_client.send_base64_audio(telefone, b64)
        except Exception as e:
            logger.error(f"Erro enviando áudio para {telefone}: {e}")
            # Fallback: envia como texto
            await self.evolution_client.send_text_message(telefone, resposta_texto)

    async def _responder_como_planilha(self, telefone: str, nome: str, texto: str, contexto: str):
        """Gera planilha real via Gemini a partir do contexto RAG e envia como Excel."""
        prompt_planilha = f"""
Você é o Assistente do Wesley. O usuário pediu: "{texto}"

Com base neste contexto do portfólio do Wesley:
{contexto}

Extraia as informações pedidas e retorne SOMENTE as linhas da planilha, sem texto extra.
Formato obrigatório: cada linha separada por \n, colunas separadas por | (pipe).
A primeira linha é o cabeçalho. Exemplo:
Tecnologia | Nível | Categoria
Python | Avançado | Backend
"""
        try:
            response = self.llm_client.models.generate_content(
                model=settings.gemini_model, contents=prompt_planilha
            )
            linhas_raw = response.text.strip().split('\n')

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Portfolio Wesley"
            for linha in linhas_raw:
                if '|' in linha:
                    colunas = [c.strip() for c in linha.split('|')]
                    ws.append(colunas)

            excel_io = io.BytesIO()
            wb.save(excel_io)
            excel_io.seek(0)
            b64 = base64.b64encode(excel_io.read()).decode('utf-8')
            caption = f"Planilha gerada para {nome} com base no portfólio do Wesley!"
            await self.evolution_client.send_base64_document(telefone, b64, "Wesley_Portfolio.xlsx", caption)
        except Exception as e:
            logger.error(f"Erro enviando planilha para {telefone}: {e}")
            # Fallback: envia como texto
            resposta = await self._gerar_resposta_texto(nome, texto, contexto)
            await self.evolution_client.send_text_message(telefone, resposta)

    async def _enviar_audio_teste(self, telefone: str, nome: str):
        """Compat: delega para _responder_como_audio com mensagem genérica."""
        await self._responder_como_audio(telefone, nome, "Fale sobre o Wesley e suas habilidades", "")

    async def _enviar_planilha_teste(self, telefone: str, nome: str):
        """Compat: delega para _responder_como_planilha com pedido genérico."""
        contexto = self.rag.retrieve_smart("stacks tecnologias habilidades Wesley")
        await self._responder_como_planilha(telefone, nome, "Liste as principais tecnologias e stacks do Wesley", contexto)
