from fastapi import APIRouter, Request, BackgroundTasks
import logging
import json

from app.domain.schemas.webhook import WebhookBody
from app.infrastructure.external.evolution_client import EvolutionClient
from app.application.services.bot_service import AtendimentoService
from app.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

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

    logger.info(
        f"Webhook recebido: event={payload.get('event')} instance={payload.get('instance')}"
    )
    logger.info(f"PAYLOAD: {json.dumps(payload, ensure_ascii=False, default=str)[:2000]}")

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

        # Passa o client correto para o service processar em background
        background_tasks.add_task(atendimento_service.processar_webhook, body, client)

    except ValueError as e:
        logger.warning(
            f"Schema do Webhook diferente do esperado ou não implementado: {e}"
        )

    return {"status": "ok"}
