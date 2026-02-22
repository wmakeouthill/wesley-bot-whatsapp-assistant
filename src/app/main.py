from fastapi import FastAPI
from app.infrastructure.config.settings import settings

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
    )

    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "ok", "app": settings.project_name}

    from app.interfaces.api.v1.routers import whatsapp_router, webhook_router
    app.include_router(whatsapp_router.router)
    app.include_router(webhook_router.router)

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
