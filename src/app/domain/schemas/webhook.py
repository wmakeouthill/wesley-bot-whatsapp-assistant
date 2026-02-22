from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class MessageKey(BaseModel):
    remoteJid: str # O número de quem mandou (ex: 5511999999999@s.whatsapp.net)
    fromMe: bool
    id: str # ID único da mensagem gerado pelo WhatsApp

class MessageContent(BaseModel):
    conversation: Optional[str] = None # Mensagem de texto simples
    extendedTextMessage: Optional[Dict[str, Any]] = None # Mensagem longa ou com formatação

class MessageInfo(BaseModel):
    message: Optional[MessageContent] = None
    key: MessageKey
    pushName: Optional[str] = None # Nome do usuário no WhatsApp

class WebhookData(BaseModel):
    key: MessageKey
    pushName: Optional[str] = None
    message: Optional[MessageContent] = None
    messageType: str
    
class WebhookBody(BaseModel):
    event: str # Ex: "messages.upsert"
    instance: str
    data: WebhookData
    destination: str
    date_time: str
    sender: str
    server_url: str
    apikey: str
