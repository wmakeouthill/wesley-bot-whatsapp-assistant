import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.infrastructure.config.settings import settings
from app.infrastructure.database.base import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.async_database_url,
    echo=False,
    # Pool de conexões: evita criação excessiva/leak sob carga alta
    pool_size=10,        # conexões persistentes no pool
    max_overflow=20,     # conexões extras permitidas acima do pool_size
    pool_pre_ping=True,  # valida a conexão antes de usar (evita "connection closed" após idle)
    pool_recycle=1800,   # recicla conexões a cada 30min (evita timeout do PostgreSQL)
    pool_timeout=30,     # aguarda até 30s por uma conexão livre antes de lançar erro
)

async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_db():
    async with engine.begin() as conn:
        # Import models here so that they are registered with Base.metadata
        from app.domain.entities import models
        await conn.run_sync(Base.metadata.create_all)
        
async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
