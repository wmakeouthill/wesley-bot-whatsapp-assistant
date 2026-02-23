import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.infrastructure.config.settings import settings
from app.infrastructure.database.base import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.async_database_url,
    echo=False
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
