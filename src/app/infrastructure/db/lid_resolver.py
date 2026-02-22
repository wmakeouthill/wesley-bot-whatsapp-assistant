"""
Resolve LID (@lid) para número de telefone real consultando o banco da Evolution API.

O WhatsApp introduziu LIDs (Linked Identity) por privacidade. O webhook entrega
`remoteJid` no formato `219602130833594@lid` em vez de `5521983866676`. Para enviar
resposta, precisamos do número real que a Evolution salva na tabela Contact.
"""

import logging
import asyncpg
from typing import Optional
from app.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)

# Cache em memória: lid_jid → telefone (evita queries repetidas por mensagem)
_lid_cache: dict[str, str] = {}


async def resolver_lid(lid_jid: str, instance_name: str) -> Optional[str]:
    """
    Busca o número de telefone real de um LID JID.

    Estratégia:
    1. Verifica o cache em memória
    2. Consulta tabela Contact da Evolution (remoteJid = lid_jid → campo phone)
    3. Consulta tabela Message buscando mensagens fromMe=false desse LID (tem sender real)
    4. Retorna None se não achar (primeira mensagem antes do contato ser salvo)

    Args:
        lid_jid: JID no formato "219602130833594@lid"
        instance_name: nome da instância Evolution, ex: "wesley_bot_session"

    Returns:
        Número de telefone sem @, ex: "5521983866676", ou None se não mapeado
    """
    # 1. Cache hit
    if lid_jid in _lid_cache:
        logger.debug(f"LID cache hit: {lid_jid} → {_lid_cache[lid_jid]}")
        return _lid_cache[lid_jid]

    try:
        conn = await asyncpg.connect(settings.evolution_db_url)
        try:
            telefone = await _buscar_no_banco(conn, lid_jid, instance_name)
            if telefone:
                _lid_cache[lid_jid] = telefone
                logger.info(f"LID resolvido: {lid_jid} → {telefone}")
            return telefone
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"Erro ao resolver LID {lid_jid}: {e}")
        return None


async def _buscar_no_banco(
    conn: asyncpg.Connection, lid_jid: str, instance_name: str
) -> Optional[str]:
    """Executa as queries no banco da Evolution para resolver o LID."""

    # Pega o instanceId pelo nome da instância
    instance_id = await conn.fetchval(
        'SELECT id FROM "Instance" WHERE name = $1', instance_name
    )
    if not instance_id:
        logger.warning(f"Instância '{instance_name}' não encontrada no banco da Evolution")
        return None

    # Tentativa 1: tabela Contact, campo phone ou phoneNumber
    # (Evolution API salva contatos com o número real quando DATABASE_SAVE_DATA_CONTACTS=true)
    row = await conn.fetchrow(
        '''
        SELECT "remoteJid", "phone", "pushName"
        FROM "Contact"
        WHERE "instanceId" = $1
          AND ("remoteJid" = $2 OR "lid" = $2)
        LIMIT 1
        ''',
        instance_id,
        lid_jid,
    )
    if row:
        # Tenta campo "phone" direto
        phone = row.get("phone")
        if phone:
            return _normalizar_numero(phone)
        # Fallback: se o remoteJid salvo for o número real (não o LID)
        jid = row.get("remoteJid", "")
        if "@s.whatsapp.net" in jid:
            return jid.split("@")[0]

    # Tentativa 2: tabela Message — mensagens recebidas com sender = número real
    # Quando a Evolution salva mensagens, o campo "sender" pode ter o número real
    msg_row = await conn.fetchrow(
        '''
        SELECT sender
        FROM "Message"
        WHERE "instanceId" = $1
          AND "remoteJid" = $2
          AND "fromMe" = false
          AND sender IS NOT NULL
          AND sender NOT LIKE '%@lid%'
        LIMIT 1
        ''',
        instance_id,
        lid_jid,
    )
    if msg_row:
        sender = msg_row.get("sender", "")
        if sender and "@s.whatsapp.net" in sender:
            return sender.split("@")[0]

    return None


def _normalizar_numero(phone: str) -> str:
    """Remove sufixos @... e caracteres não numéricos."""
    if "@" in phone:
        phone = phone.split("@")[0]
    return "".join(c for c in phone if c.isdigit())
