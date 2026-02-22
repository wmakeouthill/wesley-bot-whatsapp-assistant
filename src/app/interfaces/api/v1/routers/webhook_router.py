from fastapi import APIRouter, Request, BackgroundTasks, status
from typing import Dict, Any
import logging
from pprint import pprint

from app.domain.schemas.webhook import WebhookBody
from app.infrastructure.external.evolution_client import EvolutionClient
from app.application.services.bot_service import AtendimentoService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

evolution_client = EvolutionClient()
atendimento_service = AtendimentoService(evolution_client)

@router.post("/evolution", summary="Recebe eventos da Evolution API")
async def receive_evolution_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Endpoint de escuta para o WhatsApp.
    Tudo que acontece na sessão (mensagens, leitura, etc) baterá aqui.
    """
    try:
        body_bytes = await request.body()
        if not body_bytes:
            return {"status": "ignored"}
        payload = await request.json()
    except Exception as e:
        logger.warning(f"Webhook com body inválido: {e}")
        return {"status": "ignored"}
    
    # Validação segura (ignora eventos estranhos da api antes de serializar)
    if "event" not in payload:
        logger.debug(f"Webhook sem campo 'event' ignorado. Keys: {list(payload.keys())}")
        return {"status": "ignored"}

    logger.info(f"Webhook recebido: event={payload.get('event')} instance={payload.get('instance')}")

    # LOG TEMPORÁRIO: ver estrutura completa do payload
    if payload.get('event') == 'messages.upsert':
        import json
        logger.info(f"PAYLOAD COMPLETO: {json.dumps(payload, ensure_ascii=False, default=str)}")

    try:
        # Tenta popular o schema
        body = WebhookBody(**payload)
        
        # Envia para a service processar em Background
        # (O WhatsApp requer que respondamos com 200 OK IMEDIATAMENTE, 
        # senão a API do telefone reenvia a mensagem)
        background_tasks.add_task(atendimento_service.processar_webhook, body)
        
    except ValueError as e:
        logger.warning(f"Schema do Webhook diferente do esperado ou não implementado: {e}")
        # Apenas ignorar graciosamente pacotes complexos do wpp que não mapeamos
        pass
        
    return {"status": "ok"}
