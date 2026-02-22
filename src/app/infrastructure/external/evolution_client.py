import asyncio
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

    async def _get(self, endpoint: str) -> Dict[str, Any]:
        """Método base para fazer requisições GET para a Evolution API"""
        url = f"{self.base_url}{endpoint}"
        if "{instance}" in url:
            url = url.format(instance=self.instance_name)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP da Evolution API: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Erro na comunicação com Evolution API: {str(e)}")
            raise

    async def connect_instance(self) -> Dict[str, Any]:
        """Busca o QR Code de uma instância já existente"""
        return await self._get("/instance/connect/{instance}")

    async def delete_instance(self) -> Dict[str, Any]:
        """Deleta a instância atual para permitir recriação com novo QR"""
        url = f"{self.base_url}/instance/delete/{self.instance_name}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(url, headers=self.headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro ao deletar instância: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Erro ao deletar instância: {str(e)}")
            raise

    async def connection_state(self) -> Dict[str, Any]:
        """Retorna o estado de conexão atual da instância"""
        return await self._get("/instance/connectionState/{instance}")

    async def _await_qr(self, retries: int = 10, interval: float = 2.0) -> Dict[str, Any]:
        """Aguarda o QR Code ficar disponível, tentando até `retries` vezes com `interval` segundos entre cada."""
        for attempt in range(retries):
            await asyncio.sleep(interval)
            try:
                data = await self.connect_instance()
                if data.get("base64"):
                    logger.info(f"QR Code obtido na tentativa {attempt + 1}.")
                    return data
                logger.info(f"QR ainda não disponível (tentativa {attempt + 1}/{retries}), aguardando...")
            except Exception as e:
                logger.warning(f"Erro ao buscar QR na tentativa {attempt + 1}: {e}")
        raise RuntimeError("QR Code não ficou disponível após múltiplas tentativas. Tente novamente.")

    async def create_instance(self) -> Dict[str, Any]:
        """Cria a instância se não existir, senão reconecta ou recria para gerar QR.
        
        Fluxo:
        1. Tenta criar → retorna JSON com qrcode.base64 (instância nova)
        2. Se 403 (já existe) → verifica estado:
           - "open"       → já conectado, retorna estado
           - qualquer outro → deleta e recria para gerar QR fresco
        """
        payload = {
            "instanceName": self.instance_name,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS"
        }
        try:
            await self._post("/instance/create", payload)
            # QR é gerado de forma assíncrona pela Evolution — aguarda ficar disponível
            return await self._await_qr()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.info("Instância já existe, verificando estado...")
                try:
                    state = await self.connection_state()
                    status = state.get("instance", {}).get("state", "")
                except Exception:
                    status = ""

                if status == "open":
                    logger.info("Instância já conectada.")
                    return {"status": "already_connected", "instance": state}

                # Desconectada/connecting — deleta e recria para QR fresco
                logger.info(f"Instância no estado '{status}', deletando para recriar QR...")
                await self.delete_instance()
                await self._post("/instance/create", payload)
                return await self._await_qr()
            raise

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
