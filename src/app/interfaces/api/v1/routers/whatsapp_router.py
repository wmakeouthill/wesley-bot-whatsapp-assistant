from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, Any

from app.infrastructure.external.evolution_client import EvolutionClient

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Connection"])
evolution_client = EvolutionClient()

class SendMessageRequest(BaseModel):
    numero: str = Field(..., description="Número do WhatsApp com DDI e sem caracteres especiais. Ex: 5511999999999")
    texto: str = Field(..., description="Texto da mensagem que será enviada")

@router.post("/conectar", summary="Gera QR Code do Bot")
async def gerar_qrcode() -> Dict[str, Any]:
    """
    Aciona a Evolution API para gerar um QR Code novo pro WhatsApp do Bot,
    ou retorna o status se já estiver conectado.
    """
    try:
        response = await evolution_client.create_instance()
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/enviar-teste", summary="Envia mensagem teste via Evolution")
async def enviar_mensagem(request: SendMessageRequest, background_tasks: BackgroundTasks):
    """
    Usa o client para enviar um texto para qualquer número diretamente no Swagger local.
    """
    try:
        # Enviando via BackgroundTask pra não segurar a API travada (Assincronia)
        background_tasks.add_task(
            evolution_client.send_text_message,
            request.numero,
            request.texto
        )
        return {"status": "enviado para background process"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
