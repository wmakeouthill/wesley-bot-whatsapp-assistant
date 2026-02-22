import httpx
import logging
from typing import Optional, Dict, Any
from app.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)

class EvolutionClient:
    """Cliente HTTP para comunicação com a Evolution API"""
    
    def __init__(self):
        self.base_url = settings.evolution_api_url
        self.api_key = settings.evolution_api_key
        self.instance_name = settings.evolution_instance_name
        
        self.headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }

    async def _post(self, endpoint: str, payload: dict) -> Dict[str, Any]:
        """Método base para fazer requisições POST para a Evolution API"""
        url = f"{self.base_url}{endpoint}"
        
        # A Evolution usa o nome da instancia no endpoint para a maioria das rotas
        # Exemplo: /message/sendText/wesley_bot_session
        if "{instance}" in url:
            url = url.format(instance=self.instance_name)
            
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=self.headers, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP da Evolution API: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Erro na comunicação com Evolution API: {str(e)}")
            raise

    async def create_instance(self) -> Dict[str, Any]:
        """Cria ou recupera a instância (gera o QR Code caso não exista)"""
        url = "/instance/create"
        payload = {
            "instanceName": self.instance_name,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS"
        }
        return await self._post(url, payload)

    async def send_text_message(self, number: str, text: str) -> Dict[str, Any]:
        """Envia uma mensagem de texto simples"""
        url = "/message/sendText/{instance}"
        payload = {
            "number": number,
            "options": {
                "delay": 1200, # delayzinho para parecer humano
                "presence": "composing" # mostra "digitando"
            },
            "textMessage": {
                "text": text
            }
        }
        return await self._post(url, payload)

    async def send_base64_audio(self, number: str, base64_audio: str) -> Dict[str, Any]:
        """Envia um áudio gravado como PTT (Voice Message)"""
        url = "/message/sendWhatsAppAudio/{instance}"
        payload = {
            "number": number,
            "options": {
                "delay": 2000,
                "presence": "recording",
                "encoding": True
            },
            "audioMessage": {
                "audio": base64_audio
            }
        }
        return await self._post(url, payload)

    async def send_base64_document(self, number: str, base64_doc: str, filename: str) -> Dict[str, Any]:
        """Envia um documento (Excel/PDF) em Base64"""
        url = "/message/sendMedia/{instance}"
        payload = {
            "number": number,
            "options": {
                "delay": 1500,
                "presence": "composing"
            },
            "mediaMessage": {
                "mediatype": "document",
                "fileName": filename,
                "media": base64_doc
            }
        }
        return await self._post(url, payload)
