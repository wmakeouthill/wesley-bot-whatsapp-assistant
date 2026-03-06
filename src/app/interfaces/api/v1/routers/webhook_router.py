from fastapi import APIRouter, Request, BackgroundTasks
import asyncio
import logging
import json

from app.domain.schemas.webhook import WebhookBody
from app.infrastructure.external.evolution_client import EvolutionClient
from app.application.services.bot_service import AtendimentoService
from app.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# ---------------------------------------------------------------------------
# Controle de concorrência: evita acúmulo ilimitado de tasks em memória
# sob flood de webhooks (muitas mensagens simultâneas).
# ---------------------------------------------------------------------------
MAX_CONCURRENT_WEBHOOKS = 10
_webhook_semaphore = asyncio.Semaphore(MAX_CONCURRENT_WEBHOOKS)

# ---------------------------------------------------------------------------
# Guard de reconexão: evita reconexões paralelas para a mesma instância.
# Compartilhado com o watchdog (main.py importa este set).
# ---------------------------------------------------------------------------
_reconnecting: set[str] = set()


async def _reconectar_por_evento(client: EvolutionClient, nome: str) -> None:
    """
    Tenta uma reconexão imediata ao receber CONNECTION_UPDATE com state=close.

    Faz apenas UMA tentativa — sem retry loop. O watchdog (main.py) é o
    responsável por retentativas persistentes a cada 10 minutos. Essa função
    serve apenas para recuperação rápida de quedas pontuais.
    """
    if nome in _reconnecting:
        logger.info(f"[ConexãoEvento] {nome}: reconexão já em andamento, ignorando.")
        return

    _reconnecting.add(nome)
    try:
        logger.warning(f"[ConexãoEvento] {nome}: desconexão detectada via webhook. Tentando reconexão rápida...")

        # Aguarda o Baileys estabilizar antes de solicitar conexão
        await asyncio.sleep(5)

        try:
            result = await client.connect_instance()
            if result.get("base64"):
                logger.critical(
                    f"[ConexãoEvento] {nome}: sessão WhatsApp EXPIRADA — QR Code necessário! "
                    f"Acesse o painel para escanear o novo QR."
                )
                return
        except Exception as e:
            logger.error(f"[ConexãoEvento] {nome}: erro ao solicitar reconexão: {e}")
            return

        # Verifica resultado após 15s
        await asyncio.sleep(15)
        try:
            data = await client.connection_state()
            state = data.get("instance", {}).get("state", "unknown")
            if state == "open":
                logger.info(f"[ConexãoEvento] {nome}: reconectado com sucesso ✓")
            else:
                logger.warning(
                    f"[ConexãoEvento] {nome}: estado '{state}' após tentativa rápida. "
                    f"Watchdog continuará monitorando a cada 10 min."
                )
        except Exception as e:
            logger.error(f"[ConexãoEvento] {nome}: erro ao verificar estado: {e}")
    finally:
        _reconnecting.discard(nome)


async def _processar_com_limite(
    service: AtendimentoService, body: WebhookBody, client: EvolutionClient
) -> None:
    """Wrapper que garante no máximo MAX_CONCURRENT_WEBHOOKS processamentos simultâneos."""
    async with _webhook_semaphore:
        await service.processar_webhook(body, client)

# ---------------------------------------------------------------------------
# Instâncias dos clientes para cada número/instância do Evolution API
# ---------------------------------------------------------------------------
# Instância 1: bot portfólio (número principal)
evolution_client_1 = EvolutionClient(settings.evolution_instance_name)

# Instância 2: número pessoal do Wesley (vazio se EVOLUTION_INSTANCE_TWO_NAME não configurado)
evolution_client_2 = (
    EvolutionClient(settings.evolution_instance_two_name)
    if settings.evolution_instance_two_name
    else None
)

# Serviço orquestrador compartilhado (a instância correta é passada no processamento)
atendimento_service = AtendimentoService(evolution_client_1)


@router.post("/evolution", summary="Recebe eventos da Evolution API")
async def receive_evolution_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Endpoint de escuta para o WhatsApp.
    Tudo que acontece nas sessões (mensagens, leitura, etc) bate aqui.
    Roteia automaticamente para o EvolutionClient correto conforme body.instance.
    """
    try:
        body_bytes = await request.body()
        if not body_bytes:
            return {"status": "ignored"}
        payload = await request.json()
    except Exception as e:
        logger.warning(f"Webhook com body inválido: {e}")
        return {"status": "ignored"}

    if "event" not in payload:
        logger.info(f"Webhook sem 'event' ignorado. Keys: {list(payload.keys())}")
        return {"status": "ignored"}

    event = payload.get("event", "")
    instance_name = payload.get("instance", "")

    logger.info(f"Webhook recebido: event={event} instance={instance_name}")
    logger.info(f"PAYLOAD: {json.dumps(payload, ensure_ascii=False, default=str)[:2000]}")

    # -----------------------------------------------------------------------
    # Tratamento prioritário: connection.update — reconecta imediatamente
    # sem tentar parsear como WebhookBody (schema diferente).
    # -----------------------------------------------------------------------
    if event == "connection.update":
        state = payload.get("data", {}).get("state", "")
        logger.info(f"[ConnectionUpdate] {instance_name}: state={state}")

        if state == "close":
            if (
                evolution_client_2 is not None
                and instance_name == settings.evolution_instance_two_name
            ):
                target_client = evolution_client_2
            else:
                target_client = evolution_client_1

            background_tasks.add_task(_reconectar_por_evento, target_client, instance_name)

        return {"status": "ok"}

    try:
        body = WebhookBody(**payload)

        # Seleciona o EvolutionClient correto baseado na instância que originou o webhook
        if (
            evolution_client_2 is not None
            and body.instance == settings.evolution_instance_two_name
        ):
            client = evolution_client_2
            logger.info(f"Roteando para instância PESSOAL: {body.instance}")
        else:
            client = evolution_client_1
            logger.info(f"Roteando para instância PORTFÓLIO: {body.instance}")

        # Passa o client correto para o service processar em background,
        # respeitando o semáforo de concorrência máxima
        background_tasks.add_task(_processar_com_limite, atendimento_service, body, client)

    except ValueError as e:
        logger.warning(
            f"Schema do Webhook diferente do esperado ou não implementado: {e}"
        )

    return {"status": "ok"}
