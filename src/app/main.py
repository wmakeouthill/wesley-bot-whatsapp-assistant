import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.infrastructure.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(name)s - %(message)s"
)

logger = logging.getLogger(__name__)

# Intervalo do watchdog: verifica conexão WhatsApp a cada 10 minutos
_WATCHDOG_INTERVAL_SECONDS = 10 * 60

# Segundos para aguardar o Baileys estabelecer conexão após connect_instance()
_RECONNECT_CHECK_DELAY = 20

# Máximo de tentativas de reconexão antes de desistir e logar alerta crítico
_MAX_RECONNECT_ATTEMPTS = 3

# Mensagens com mais de N dias são deletadas na limpeza automática
_CLEANUP_DAYS = 90

# Intervalo da limpeza automática de mensagens antigas
_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60  # 1 vez por dia


async def _tentar_reconectar(client, nome: str) -> bool:
    """
    Tenta reconectar uma instância WhatsApp com retry e backoff exponencial.

    Trata três cenários distintos:

    1. Reconexão bem-sucedida (Baileys reconecta com sessão existente):
       connect_instance() → aguarda → state == "open" → retorna True

    2. Sessão expirada (WhatsApp invalidou a sessão antiga — exige novo QR):
       connect_instance() retorna {"base64": "..."} → loga CRITICAL → retorna False
       Não adianta continuar tentando: o QR precisa ser escaneado manualmente.

    3. Falha transitória (rede, Evolution API sobrecarregada, etc.):
       Retenta até _MAX_RECONNECT_ATTEMPTS com backoff 20s → 40s → 80s.
       Se ainda falhar, loga ERROR e retorna False.
    """
    for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
        logger.warning(f"[Watchdog] {nome}: tentativa de reconexão {attempt}/{_MAX_RECONNECT_ATTEMPTS}...")

        try:
            result = await client.connect_instance()

            # Cenário 2: sessão expirada → Evolution gerou novo QR
            if result.get("base64"):
                logger.critical(
                    f"[Watchdog] {nome}: sessão WhatsApp EXPIRADA — QR Code necessário! "
                    f"Acesse /whatsapp/conectar ou o painel para escanear o novo QR."
                )
                return False

        except Exception as e:
            logger.error(f"[Watchdog] {nome}: erro ao solicitar reconexão (tentativa {attempt}): {e}")
            # Não interrompe: pode ser falha transitória, tenta de novo com backoff

        # Aguarda o Baileys estabelecer a conexão antes de verificar
        await asyncio.sleep(_RECONNECT_CHECK_DELAY)

        # Verifica se a reconexão funcionou
        try:
            data = await client.connection_state()
            state = data.get("instance", {}).get("state", "unknown")

            if state == "open":
                logger.info(f"[Watchdog] {nome}: reconectado com sucesso ✓")
                return True

            logger.warning(f"[Watchdog] {nome}: ainda '{state}' após tentativa {attempt}.")

        except Exception as e:
            logger.error(f"[Watchdog] {nome}: erro ao verificar estado pós-reconexão: {e}")

        # Backoff exponencial antes da próxima tentativa: 40s, 80s
        if attempt < _MAX_RECONNECT_ATTEMPTS:
            backoff = _RECONNECT_CHECK_DELAY * (2 ** attempt)
            logger.info(f"[Watchdog] {nome}: aguardando {backoff}s antes da tentativa {attempt + 1}...")
            await asyncio.sleep(backoff)

    logger.error(
        f"[Watchdog] {nome}: falhou após {_MAX_RECONNECT_ATTEMPTS} tentativas. "
        f"Verifique a Evolution API e o estado da sessão manualmente."
    )
    return False


async def _watchdog():
    """
    Monitora o estado de conexão WhatsApp de cada instância a cada 10 minutos.
    Se a instância não estiver "open", tenta reconectar com retry inteligente.
    Não faz restarts preventivos — isso causava falsos positivos e tempestades de QR.
    """
    from app.infrastructure.external.evolution_client import EvolutionClient
    from app.interfaces.api.v1.routers.webhook_router import _reconnecting

    # Aguarda inicialização completa antes da primeira verificação
    await asyncio.sleep(60)

    while True:
        try:
            instancias = [settings.evolution_instance_name]
            if settings.evolution_instance_two_name:
                instancias.append(settings.evolution_instance_two_name)

            for nome in instancias:
                client = EvolutionClient(nome)
                try:
                    data = await client.connection_state()
                    state = data.get("instance", {}).get("state", "unknown")

                    if state == "open":
                        logger.info(f"[Watchdog] {nome}: conectado (open) ✓")
                    else:
                        # Evita tentar reconectar se o webhook já está tratando isso
                        if nome in _reconnecting:
                            logger.info(
                                f"[Watchdog] {nome}: reconexão já em andamento via webhook, aguardando..."
                            )
                        else:
                            logger.warning(f"[Watchdog] {nome}: estado '{state}' detectado.")
                            await _tentar_reconectar(client, nome)

                except Exception as e:
                    logger.error(f"[Watchdog] Erro ao verificar {nome}: {e}")

        except Exception as e:
            logger.error(f"[Watchdog] Erro inesperado no loop: {e}")

        await asyncio.sleep(_WATCHDOG_INTERVAL_SECONDS)


async def _cleanup_old_messages():
    """
    Remove mensagens com mais de _CLEANUP_DAYS dias do banco, uma vez por dia.
    Libera espaço em disco e mantém queries do painel rápidas.
    """
    from app.infrastructure.database.session import async_session
    from app.domain.entities.models import Mensagem
    from sqlalchemy import delete as sa_delete

    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        try:
            cutoff = datetime.utcnow() - timedelta(days=_CLEANUP_DAYS)
            async with async_session() as session:
                result = await session.execute(
                    sa_delete(Mensagem).where(Mensagem.data_hora < cutoff)
                )
                await session.commit()
                deleted = result.rowcount
                if deleted > 0:
                    logger.info(f"[Cleanup] {deleted} mensagens com mais de {_CLEANUP_DAYS} dias removidas.")
                else:
                    logger.info(f"[Cleanup] Nenhuma mensagem antiga para remover.")
        except Exception as e:
            logger.error(f"[Cleanup] Erro na limpeza automática: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia ciclo de vida da aplicação: startup e shutdown."""
    from app.infrastructure.database.session import init_db

    await init_db()

    watchdog_task = asyncio.create_task(_watchdog())
    cleanup_task = asyncio.create_task(_cleanup_old_messages())
    logger.info("[Lifespan] Banco inicializado. Watchdog e limpeza automática ativos.")

    yield

    watchdog_task.cancel()
    cleanup_task.cancel()
    for task in (watchdog_task, cleanup_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("[Lifespan] Watchdog e cleanup encerrados.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory="src/app/static"), name="static")

    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "ok", "app": settings.project_name}

    from app.interfaces.api.v1.routers import whatsapp_router, webhook_router
    from app.interfaces.api.v1.routers.panel_router import router as panel_router

    app.include_router(whatsapp_router.router)
    app.include_router(webhook_router.router)
    app.include_router(panel_router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
