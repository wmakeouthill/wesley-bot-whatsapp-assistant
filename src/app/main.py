import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.infrastructure.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(name)s - %(message)s"
)

logger = logging.getLogger(__name__)

# Intervalo do watchdog: verifica conexão WhatsApp a cada 5 minutos
_WATCHDOG_INTERVAL_SECONDS = 5 * 60

# Segundos para aguardar o Baileys estabelecer conexão após connect_instance()
_RECONNECT_CHECK_DELAY = 20

# Máximo de tentativas de reconexão antes de desistir e logar alerta crítico
_MAX_RECONNECT_ATTEMPTS = 3

# Ciclos consecutivos com state="open" antes de forçar restart para detectar ghost connections.
# 12 ciclos × 5 min = 60 min → reinicia Baileys a cada hora como heartbeat.
_GHOST_RESTART_CYCLES = 12

# Contador de ciclos "open" por instância (chave: nome da instância)
_open_cycles: dict[str, int] = {}


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
    Monitora o estado de conexão WhatsApp de cada instância a cada 5 minutos.

    Dois modos de atuação:
    1. State != "open": delega para _tentar_reconectar() com retry inteligente.
    2. State == "open" por N ciclos consecutivos (_GHOST_RESTART_CYCLES): reinicia
       o Baileys via restart_instance() para eliminar ghost connections (conexões
       que parecem vivas mas o WebSocket subjacente está morto).
    """
    from app.infrastructure.external.evolution_client import EvolutionClient

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
                        _open_cycles[nome] = _open_cycles.get(nome, 0) + 1
                        cycles = _open_cycles[nome]

                        if cycles >= _GHOST_RESTART_CYCLES:
                            # Heartbeat: reinicia Baileys para garantir que o WebSocket
                            # está realmente vivo e não é uma ghost connection.
                            logger.info(
                                f"[Watchdog] {nome}: heartbeat — {cycles} ciclos 'open'. "
                                f"Reiniciando Baileys para verificar conexão real..."
                            )
                            try:
                                await client.restart_instance()
                                _open_cycles[nome] = 0
                                logger.info(f"[Watchdog] {nome}: restart preventivo concluído ✓")
                            except Exception as e:
                                logger.warning(f"[Watchdog] {nome}: falha no restart preventivo: {e}")
                                _open_cycles[nome] = 0  # Reset para evitar loop de falhas
                        else:
                            logger.info(
                                f"[Watchdog] {nome}: conectado (open) ✓ "
                                f"[ciclo {cycles}/{_GHOST_RESTART_CYCLES}]"
                            )
                    else:
                        _open_cycles[nome] = 0  # Reset contador ao detectar desconexão
                        logger.warning(f"[Watchdog] {nome}: estado '{state}' detectado.")
                        await _tentar_reconectar(client, nome)

                except Exception as e:
                    logger.error(f"[Watchdog] Erro ao verificar {nome}: {e}")

        except Exception as e:
            logger.error(f"[Watchdog] Erro inesperado no loop: {e}")

        await asyncio.sleep(_WATCHDOG_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia ciclo de vida da aplicação: startup e shutdown."""
    from app.infrastructure.database.session import init_db

    await init_db()

    watchdog_task = asyncio.create_task(_watchdog())
    logger.info("[Lifespan] Banco inicializado. Watchdog de conexão ativo.")

    yield

    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass
    logger.info("[Lifespan] Watchdog encerrado.")


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
