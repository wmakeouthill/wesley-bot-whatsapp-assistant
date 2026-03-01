"""
Router do Painel de Gestão Admin.
Serve tanto os templates HTML (GET /panel/*) quanto os endpoints REST JSON (POST|GET /api/panel/*).
"""
import uuid
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Form, Response, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select, func, desc, or_, delete

from app.infrastructure.auth.panel_auth import (
    verify_password,
    create_access_token,
    get_current_user,
    hash_password,
)
from app.infrastructure.database.session import async_session
from app.domain.entities.models import AdminUser, Cliente, Mensagem, BotConfig, AllowBlockEntry
from app.infrastructure.config.settings import settings
from app.infrastructure.external.evolution_client import EvolutionClient

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="src/app/templates")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client_for_instance(instance_name: str) -> EvolutionClient:
    return EvolutionClient(instance_name)


# ---------------------------------------------------------------------------
# Pydantic schemas do painel
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str

class IAToggleRequest(BaseModel):
    instancia: str
    chat_jid: Optional[str] = None   # None = global
    ia_ativa: bool

class AllowlistUpdateRequest(BaseModel):
    instancia: str  # nome da instância (ex: wesley_bot_session)
    allowlist: str  # números separados por vírgula
    blocklist: str  # números separados por vírgula

class ResetarChatRequest(BaseModel):
    instancia: str
    chat_jid: str


# ===========================================================================
# PÁGINAS HTML
# ===========================================================================

@router.get("/panel/login", response_class=HTMLResponse, include_in_schema=False)
async def panel_login_page(request: Request):
    return templates.TemplateResponse("panel/login.html", {"request": request})


@router.get("/panel", response_class=HTMLResponse, include_in_schema=False)
@router.get("/panel/", response_class=HTMLResponse, include_in_schema=False)
async def panel_dashboard_page(request: Request):
    """Serve o dashboard. Autenticação verificada via JWT cookie no frontend."""
    return templates.TemplateResponse("panel/dashboard.html", {"request": request})


# ===========================================================================
# API REST — autenticação
# ===========================================================================

@router.post("/api/panel/login", tags=["Painel Admin"])
async def panel_login(body: LoginRequest, response: Response):
    """Login do painel. Retorna JWT e seta cookie de sessão."""
    async with async_session() as session:
        stmt = select(AdminUser).where(AdminUser.username == body.username)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos",
        )

    token = create_access_token({"sub": user.username})
    response.set_cookie(
        key="panel_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=settings.panel_jwt_expire_minutes * 60,
    )
    return {"access_token": token, "token_type": "bearer", "username": user.username}


@router.post("/api/panel/logout", tags=["Painel Admin"])
async def panel_logout(response: Response):
    response.delete_cookie("panel_token")
    return {"status": "ok"}


# ===========================================================================
# API REST — dashboard stats
# ===========================================================================

@router.get("/api/panel/dashboard", tags=["Painel Admin"])
async def panel_dashboard(current_user: str = Depends(get_current_user)):
    """Retorna estatísticas gerais para o dashboard."""
    async with async_session() as session:
        total_clientes = (await session.execute(select(func.count(Cliente.id)))).scalar_one()
        total_mensagens = (await session.execute(select(func.count(Mensagem.id)))).scalar_one()

        # Mensagens hoje
        hoje = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        total_hoje = (
            await session.execute(
                select(func.count(Mensagem.id)).where(Mensagem.data_hora >= hoje)
            )
        ).scalar_one()

        # Status IA global das instâncias
        configs = (await session.execute(
            select(BotConfig).where(BotConfig.chat_jid.is_(None))
        )).scalars().all()
        ia_status = {c.instancia: c.ia_ativa for c in configs}

    instancias = [settings.evolution_instance_name]
    if settings.evolution_instance_two_name:
        instancias.append(settings.evolution_instance_two_name)

    return {
        "total_conversas": total_clientes,
        "total_mensagens": total_mensagens,
        "mensagens_hoje": total_hoje,
        "instancias": instancias,
        "ia_status_global": ia_status,
    }


# ===========================================================================
# API REST — conversas e histórico
# ===========================================================================

@router.get("/api/panel/conversations", tags=["Painel Admin"])
async def panel_conversations(
    instancia: str,
    page: int = 1,
    per_page: int = 10,
    search: Optional[str] = None,
    current_user: str = Depends(get_current_user),
):
    """Lista de conversas com paginação (10 por página), pesquisa por número/nome e status de IA por instância."""
    offset = (page - 1) * per_page

    async with async_session() as session:
        # Base: todos os clientes (com filtro opcional por nome/número)
        base_stmt = select(Cliente)
        count_stmt = select(func.count(Cliente.id))
        if search and search.strip():
            termo = f"%{search.strip()}%"
            filtro = or_(
                Cliente.nome.ilike(termo),
                Cliente.whatsapp_id.ilike(termo),
            )
            base_stmt = base_stmt.where(filtro)
            count_stmt = count_stmt.where(filtro)

        # Total (com filtro)
        total = (await session.execute(count_stmt)).scalar_one()

        # Últimas mensagens por cliente (subquery para pegar a mais recente)
        # Busca clientes ordenados pela mensagem mais recente
        stmt = (
            select(
                Cliente,
                func.max(Mensagem.data_hora).label("ultima_msg"),
            )
            .outerjoin(Mensagem, Mensagem.id_cliente == Cliente.id)
            .group_by(Cliente.id)
        )
        if search and search.strip():
            termo = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Cliente.nome.ilike(termo),
                    Cliente.whatsapp_id.ilike(termo),
                )
            )
        stmt = (
            stmt.order_by(desc("ultima_msg"))
            .offset(offset)
            .limit(per_page)
        )
        result = await session.execute(stmt)
        rows = result.all()

        # Busca configs de IA desta instância
        jids_numeros = []
        for row in rows:
            jid = row[0].whatsapp_id
            num = jid.split("@")[0] if "@" in jid else jid
            jids_numeros.append(num)

        stmt_cfg = select(BotConfig).where(
            BotConfig.instancia == instancia,
            or_(
                BotConfig.chat_jid.in_(jids_numeros),
                BotConfig.chat_jid.is_(None),
            ),
        )
        cfgs = (await session.execute(stmt_cfg)).scalars().all()
        cfg_map: dict = {c.chat_jid: c.ia_ativa for c in cfgs}

        # Busca última mensagem de cada cliente
        ultima_msgs = {}
        for row in rows:
            cliente = row[0]
            stmt_last = (
                select(Mensagem)
                .where(Mensagem.id_cliente == cliente.id)
                .order_by(desc(Mensagem.data_hora))
                .limit(1)
            )
            last = (await session.execute(stmt_last)).scalar_one_or_none()
            ultima_msgs[cliente.id] = last

    conversas = []
    for row in rows:
        cliente = row[0]
        ultima_msg_dt = row[1]
        jid = cliente.whatsapp_id
        num = jid.split("@")[0] if "@" in jid else jid

        ia_global = cfg_map.get(None, True)
        ia_ativa = cfg_map.get(num, ia_global)

        last = ultima_msgs.get(cliente.id)
        conversas.append({
            "id": cliente.id,
            "whatsapp_id": jid,
            "numero": num,
            "nome": cliente.nome or "Desconhecido",
            "ia_ativa": ia_ativa,
            "ultima_mensagem": last.texto[:80] if last else None,
            "ultima_mensagem_direcao": last.direcao if last else None,
            "ultima_mensagem_dt": ultima_msg_dt.isoformat() if ultima_msg_dt else None,
        })

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "conversas": conversas,
    }


@router.get("/api/panel/conversations/{chat_jid_encoded}/history", tags=["Painel Admin"])
async def panel_conversation_history(
    chat_jid_encoded: str,
    limite: int = 50,
    current_user: str = Depends(get_current_user),
):
    """Retorna histórico de mensagens de uma conversa."""
    chat_jid = chat_jid_encoded.replace("__at__", "@")

    async with async_session() as session:
        stmt = select(Cliente).where(
            or_(
                Cliente.whatsapp_id == chat_jid,
                Cliente.whatsapp_id == chat_jid.split("@")[0],
            )
        )
        result = await session.execute(stmt)
        cliente = result.scalar_one_or_none()

        if not cliente:
            return {"mensagens": [], "cliente": None}

        stmt_msg = (
            select(Mensagem)
            .where(Mensagem.id_cliente == cliente.id)
            .order_by(desc(Mensagem.data_hora))
            .limit(limite)
        )
        msgs = (await session.execute(stmt_msg)).scalars().all()

    return {
        "cliente": {
            "id": cliente.id,
            "whatsapp_id": cliente.whatsapp_id,
            "nome": cliente.nome,
        },
        "mensagens": [
            {
                "id": m.id,
                "texto": m.texto,
                "direcao": m.direcao,
                "data_hora": m.data_hora.isoformat() if m.data_hora else None,
            }
            for m in reversed(msgs)
        ],
    }


# ===========================================================================
# API REST — controle de IA
# ===========================================================================

@router.get("/api/panel/ia/config", tags=["Painel Admin"])
async def panel_ia_config(current_user: str = Depends(get_current_user)):
    """Retorna todas as configurações de IA (global e por chat)."""
    async with async_session() as session:
        cfgs = (await session.execute(select(BotConfig).order_by(BotConfig.instancia))).scalars().all()
    return [
        {
            "id": c.id,
            "instancia": c.instancia,
            "chat_jid": c.chat_jid,
            "ia_ativa": c.ia_ativa,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in cfgs
    ]


@router.post("/api/panel/ia/toggle", tags=["Painel Admin"])
async def panel_ia_toggle(
    body: IAToggleRequest,
    current_user: str = Depends(get_current_user),
):
    """Ativa ou desativa a IA (globalmente ou para um chat específico)."""
    async with async_session() as session:
        if body.chat_jid:
            stmt = select(BotConfig).where(
                BotConfig.instancia == body.instancia,
                BotConfig.chat_jid == body.chat_jid,
            )
        else:
            stmt = select(BotConfig).where(
                BotConfig.instancia == body.instancia,
                BotConfig.chat_jid.is_(None),
            )
        result = await session.execute(stmt)
        cfg = result.scalar_one_or_none()

        if cfg:
            cfg.ia_ativa = body.ia_ativa
            cfg.updated_at = datetime.utcnow()
        else:
            cfg = BotConfig(
                id=str(uuid.uuid4()),
                instancia=body.instancia,
                chat_jid=body.chat_jid,
                ia_ativa=body.ia_ativa,
                updated_at=datetime.utcnow(),
            )
            session.add(cfg)

        await session.commit()

    return {
        "ok": True,
        "instancia": body.instancia,
        "chat_jid": body.chat_jid,
        "ia_ativa": body.ia_ativa,
    }


@router.post("/api/panel/ia/reset", tags=["Painel Admin"])
async def panel_ia_reset(
    body: ResetarChatRequest,
    current_user: str = Depends(get_current_user),
):
    """Remove o override de IA de um chat específico (volta ao global)."""
    async with async_session() as session:
        stmt = select(BotConfig).where(
            BotConfig.instancia == body.instancia,
            BotConfig.chat_jid == body.chat_jid,
        )
        result = await session.execute(stmt)
        cfg = result.scalar_one_or_none()
        if cfg:
            await session.delete(cfg)
            await session.commit()
    return {"ok": True}


# ===========================================================================
# API REST — allowlist / blocklist
# ===========================================================================

@router.get("/api/panel/allowlist", tags=["Painel Admin"])
async def panel_get_allowlist(
    instancia: str,
    current_user: str = Depends(get_current_user),
):
    """Retorna allowlist e blocklist atuais da instância (persistidas em bot_allow_block)."""
    async with async_session() as session:
        stmt = select(AllowBlockEntry).where(AllowBlockEntry.instancia == instancia)
        result = await session.execute(stmt)
        entries = result.scalars().all()

    allow_numbers = {e.numero for e in entries if e.tipo == "allow"}
    block_numbers = {e.numero for e in entries if e.tipo == "block"}

    return {
        "allowlist": ",".join(sorted(allow_numbers)),
        "blocklist": ",".join(sorted(block_numbers)),
        "note": f"Editar aqui atualiza allowlist/blocklist persistidos na tabela bot_allow_block para a instância '{instancia}'.",
    }


@router.post("/api/panel/allowlist", tags=["Painel Admin"])
async def panel_update_allowlist(
    body: AllowlistUpdateRequest,
    current_user: str = Depends(get_current_user),
):
    """
    Atualiza allowlist e blocklist da instância persistidos em banco (tabela bot_allow_block).
    Os números são separados por vírgula.
    """
    def _parse_numbers(raw: str) -> set[str]:
        return {n.strip() for n in raw.split(",") if n.strip()}

    allow_set = _parse_numbers(body.allowlist)
    block_set = _parse_numbers(body.blocklist)

    async with async_session() as session:
        # Remove configurações anteriores dessa instância
        await session.execute(
            delete(AllowBlockEntry).where(AllowBlockEntry.instancia == body.instancia)
        )

        now = datetime.utcnow()
        novas_entradas: list[AllowBlockEntry] = []

        for numero in allow_set:
            novas_entradas.append(
                AllowBlockEntry(
                    id=str(uuid.uuid4()),
                    instancia=body.instancia,
                    numero=numero,
                    tipo="allow",
                    created_at=now,
                    updated_at=now,
                )
            )

        for numero in block_set:
            novas_entradas.append(
                AllowBlockEntry(
                    id=str(uuid.uuid4()),
                    instancia=body.instancia,
                    numero=numero,
                    tipo="block",
                    created_at=now,
                    updated_at=now,
                )
            )

        if novas_entradas:
            session.add_all(novas_entradas)

        await session.commit()

    logger.info(
        "[PAINEL] Allowlist/blocklist atualizado para instância %s por %s",
        body.instancia,
        current_user,
    )
    return {
        "ok": True,
        "allowlist": ",".join(sorted(allow_set)),
        "blocklist": ",".join(sorted(block_set)),
    }


# ===========================================================================
# API REST — instâncias
# ===========================================================================

@router.get("/api/panel/instances", tags=["Painel Admin"])
async def panel_instances(current_user: str = Depends(get_current_user)):
    """Retorna o status de conexão de cada instância configurada."""
    instancias = [settings.evolution_instance_name]
    if settings.evolution_instance_two_name:
        instancias.append(settings.evolution_instance_two_name)

    resultados = []
    for nome in instancias:
        client = _get_client_for_instance(nome)
        try:
            state = await client.connection_state()
            status_conn = state.get("instance", {}).get("state", "unknown")
        except Exception as e:
            status_conn = f"erro: {str(e)[:50]}"
        resultados.append({"nome": nome, "status": status_conn})

    return resultados


@router.post("/api/panel/instances/{instance_name}/connect", tags=["Painel Admin"])
async def panel_instance_connect(
    instance_name: str,
    current_user: str = Depends(get_current_user),
):
    """Cria/reconecta uma instância e retorna o QR Code em base64."""
    client = _get_client_for_instance(instance_name)
    try:
        result = await client.create_instance()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
