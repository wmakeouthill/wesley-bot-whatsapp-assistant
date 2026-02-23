import logging
from typing import Optional
from app.domain.schemas.webhook import WebhookBody
from app.infrastructure.external.evolution_client import EvolutionClient
from app.domain.services.rag_service import PortfolioRAG
from app.infrastructure.database.session import async_session
from app.domain.entities.models import Cliente, Mensagem
from sqlalchemy import select
from google import genai
from app.infrastructure.config.settings import settings
import base64
import io
import openpyxl
from gtts import gTTS
import uuid
from datetime import datetime

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
        
        # Salva a mensagem recebida no SQLite
        await self._salvar_mensagem(telefone, nome_cliente, texto_recebido, "RECEBIDA", id_mensagem)
        
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

        # 3. Busca o histórico recente da conversa (ultimas 5 mensagens)
        historico_str = await self._obter_historico(telefone, limite=5)

        # 4. Trunca o contexto se exceder o orçamento de tokens (30.000 tokens ~ 120k chars)
        contexto = self._aplicar_token_budget(contexto, historico_str, texto_recebido)

        if _quer_planilha:
            await self._responder_como_planilha(telefone, nome_cliente, texto_recebido, contexto, historico_str)
            return

        if _quer_audio:
            await self._responder_como_audio(telefone, nome_cliente, texto_recebido, contexto, historico_str)
            return

        # Resposta em texto normal — usa texto_recebido original no Gemini (contexto completo)
        resposta_ia = await self._gerar_resposta_texto(nome_cliente, texto_recebido, contexto, historico_str)
        try:
            await self.evolution_client.send_text_message(telefone, resposta_ia)
            # Salva resposta gerada no histórico
            await self._salvar_mensagem(telefone, nome_cliente, resposta_ia, "ENVIADA")
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

    async def _gerar_resposta_texto(self, nome_cliente: str, texto: str, contexto: str, historico: str = "") -> str:
        """Gera resposta em texto via Gemini com contexto RAG."""
        historico_prompt = f"HISTÓRICO RECENTE DA CONVERSA:\n{historico}\nUse o histórico para manter a fluidez da conversa, mas FOQUE a sua resposta principalmente na última mensagem abaixo.\n\n" if historico else ""
        prompt = f"""
Você é o Assistente Virtual Oficial do Wesley no WhatsApp.
Seja amigável, direto, e natural em suas respostas. O usuário se chama {nome_cliente}.

Abaixo está o CONTEXTO contendo as informações sobre os certificados, habilidades e currículo do Wesley.
Baseado ESTREITAMENTE nesse contexto, responda a pergunta do usuário.
Se a informação não estiver no contexto, diga que você vai anotar a dúvida para o próprio Wesley responder depois, e NUNCA invente informações.

CONTEXTO DEDUZIDO DO PORTFÓLIO:
{contexto}

{historico_prompt}ÚLTIMA MENSAGEM DO USUÁRIO: "{texto}"
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

    async def _gerar_resposta_audio(self, nome_cliente: str, texto: str, contexto: str, historico: str = "") -> str:
        """Gera resposta em texto otimizada para fala (TTS) via Gemini com contexto RAG."""
        historico_prompt = f"HISTÓRICO RECENTE DA CONVERSA:\n{historico}\nUse o histórico para manter a fluidez da conversa, mas FOQUE a sua resposta principalmente na última mensagem abaixo.\n\n" if historico else ""
        prompt = f"""
Você é o Assistente Virtual Oficial do Wesley no WhatsApp.
O usuário se chama {nome_cliente}.
Sua resposta será convertida em voz (TTS), portanto:
1. Seja extremamente natural, coloquial e amigável.
2. EVITE QUALQUER formatação markdown (sem asteriscos **, sem listas com -, sem hashtags #).
3. Escreva números e siglas de forma pronunciável (ex: "C Sharp" em vez de "C#", "Node J S" em vez de "Node.js", "cem por cento").
4. Seja mais objetivo e direto, fale como um áudio de WhatsApp real.

Abaixo está o CONTEXTO contendo as informações sobre o Wesley.
Baseado ESTREITAMENTE nesse contexto, responda a pergunta do usuário. Se não souber dizer, fale que não sabe. NUNCA invente informações.

CONTEXTO DEDUZIDO DO PORTFÓLIO:
{contexto}

{historico_prompt}ÚLTIMA MENSAGEM DO USUÁRIO: "{texto}"
"""
        try:
            response = self.llm_client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
            )
            # Remove qualquer markdown residual
            clean_text = response.text.replace("**", "").replace("*", "").replace("#", "").replace("- ", "")
            return clean_text
        except Exception as e:
            logger.error(f"Erro chamando IA: {e}")
            return "Putz, deu uma travadinha aqui na hora de carregar meu cérebro. Tenta me pedir de novo?"

    async def _responder_como_audio(self, telefone: str, nome: str, texto: str, contexto: str, historico: str = ""):
        """Gera resposta via RAG+Gemini e envia como áudio de voz (TTS)."""
        resposta_texto = await self._gerar_resposta_audio(nome, texto, contexto, historico)
        logger.info(f"Gerando áudio TTS para {telefone}: {resposta_texto[:60]}...")
        try:
            tts = gTTS(text=resposta_texto, lang='pt', slow=False)
            audio_io = io.BytesIO()
            tts.write_to_fp(audio_io)
            audio_io.seek(0)
            b64 = base64.b64encode(audio_io.read()).decode('utf-8')
            await self.evolution_client.send_base64_audio(telefone, b64)
            await self._salvar_mensagem(telefone, nome, resposta_texto, "ENVIADA")
        except Exception as e:
            logger.error(f"Erro enviando áudio para {telefone}: {e}")
            # Fallback: envia como texto
            await self.evolution_client.send_text_message(telefone, resposta_texto)
            await self._salvar_mensagem(telefone, nome, resposta_texto, "ENVIADA")

    async def _responder_como_planilha(self, telefone: str, nome: str, texto: str, contexto: str, historico: str = ""):
        """Gera planilha real via Gemini a partir do contexto RAG e envia como Excel."""
        prompt_planilha = f"""
Você é o Assistente do Wesley. O usuário pediu: "{texto}"

Com base neste contexto do portfólio do Wesley:
{contexto}

Extraia as informações pedidas e retorne SOMENTE as linhas correspondentes ao pedido do usuário (ignore informações secundárias de RAG), sem texto extra.
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

            from openpyxl.styles import Font, PatternFill, Border, Side
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Portfolio Wesley"
            
            header_font = Font(bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
            thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

            row_idx = 1
            for linha in linhas_raw:
                if '|' in linha:
                    colunas = [c.strip() for c in linha.split('|')]
                    ws.append(colunas)
                    
                    for col_idx in range(1, len(colunas) + 1):
                        cell = ws.cell(row=row_idx, column=col_idx)
                        cell.border = thin_border
                        if row_idx == 1:
                            cell.font = header_font
                            cell.fill = header_fill
                    row_idx += 1

            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if cell.value and len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                ws.column_dimensions[column].width = max_length + 2

            excel_io = io.BytesIO()
            wb.save(excel_io)
            excel_io.seek(0)
            b64 = base64.b64encode(excel_io.read()).decode('utf-8')
            caption = f"Planilha gerada para {nome} com base no portfólio do Wesley!"
            await self.evolution_client.send_base64_document(telefone, b64, "Wesley_Portfolio.xlsx", caption)
            await self._salvar_mensagem(telefone, nome, "[Planilha Excel gerada e enviada]", "ENVIADA")
        except Exception as e:
            logger.error(f"Erro enviando planilha para {telefone}: {e}")
            # Fallback: envia como texto
            resposta = await self._gerar_resposta_texto(nome, texto, contexto, historico)
            await self.evolution_client.send_text_message(telefone, resposta)
            await self._salvar_mensagem(telefone, nome, resposta, "ENVIADA")

    async def _enviar_audio_teste(self, telefone: str, nome: str):
        """Compat: delega para _responder_como_audio com mensagem genérica."""
        await self._responder_como_audio(telefone, nome, "Fale sobre o Wesley e suas habilidades", "")

    async def _enviar_planilha_teste(self, telefone: str, nome: str):
        """Compat: delega para _responder_como_planilha com pedido genérico."""
        contexto = self.rag.retrieve_smart("stacks tecnologias habilidades Wesley")
        await self._responder_como_planilha(telefone, nome, "Liste as principais tecnologias e stacks do Wesley", contexto)
        
    def _aplicar_token_budget(self, contexto: str, historico: str, texto: str, max_tokens: int = 30000) -> str:
        """Limita o tamanho do RAG para caber no orçamento de tokens."""
        max_chars = max_tokens * 4
        base_chars = len(historico) + len(texto) + 1000 # 1000 pras instruções do prompt
        
        if base_chars + len(contexto) <= max_chars:
            return contexto
            
        chars_disponiveis = max_chars - base_chars
        if chars_disponiveis <= 0:
            return ""
            
        logger.warning(f"Token Budget: cortando RAG de {len(contexto)} para {chars_disponiveis} caracteres.")
        return contexto[:chars_disponiveis]
        
    async def _salvar_mensagem(self, whatsapp_id: str, nome: str, texto: str, direcao: str, msg_id: Optional[str] = None):
        """Salva a mensagem no banco de dados, criando cliente se não existir."""
        if not texto:
            return
            
        async with async_session() as session:
            # Busca ou cria cliente
            stmt = select(Cliente).where(Cliente.whatsapp_id == whatsapp_id)
            result = await session.execute(stmt)
            cliente = result.scalar_one_or_none()
            
            if not cliente:
                cliente = Cliente(id=str(uuid.uuid4()), whatsapp_id=whatsapp_id, nome=nome)
                session.add(cliente)
                await session.flush()
                
            # Cria mensagem
            # se tiver msg_id, verifica se ja existe para não duplicar
            if msg_id:
                stmt_msg = select(Mensagem).where(Mensagem.mensagem_id_whatsapp == msg_id)
                result_msg = await session.execute(stmt_msg)
                if result_msg.scalar_one_or_none():
                    return # ja processada
                    
            nova_msg = Mensagem(
                id=str(uuid.uuid4()),
                id_cliente=cliente.id,
                texto=texto,
                mensagem_id_whatsapp=msg_id or str(uuid.uuid4()),
                direcao=direcao,
                data_hora=datetime.utcnow()
            )
            session.add(nova_msg)
            await session.commit()

    async def _obter_historico(self, whatsapp_id: str, limite: int = 5) -> str:
        """Obtém as últimas mensagens do cliente formatadas como string de histórico."""
        async with async_session() as session:
            stmt = select(Cliente).where(Cliente.whatsapp_id == whatsapp_id)
            result = await session.execute(stmt)
            cliente = result.scalar_one_or_none()
            if not cliente:
                return ""
                
            stmt_msg = select(Mensagem).where(Mensagem.id_cliente == cliente.id).order_by(Mensagem.data_hora.desc()).limit(limite)
            result_msg = await session.execute(stmt_msg)
            mensagens = result_msg.scalars().all()
            
            if not mensagens:
                return ""
                
            historico = []
            for m in reversed(mensagens):
                remetente = "Usuário" if m.direcao == "RECEBIDA" else "Assistente"
                historico.append(f"{remetente}: {m.texto}")
                
            return "\n".join(historico)
