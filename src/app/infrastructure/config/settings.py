from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    project_name: str = "Bot de WhatsApp (Evolution API)"
    version: str = "0.1.0"
    
    # Evolution API Settings
    evolution_api_url: str = "http://bot_evolution_api:8080" # URL interna no docker
    evolution_api_key: str = ""
    evolution_instance_name: str = "wesley_bot_session"
    # URL interna do bot_api para o Evolution API enviar webhooks (via rede Docker)
    # Em produção, usar URL pública: http://<VPS_IP>:8000/webhooks/evolution
    webhook_url: str = "http://bot_api:8000/webhooks/evolution"
    
    # Gemini AI Settings
    gemini_api_key: str = "your_google_api_key_here"
    gemini_model: str = "gemini-2.0-flash"
    
    # Database Settings
    database_url: str = "sqlite+aiosqlite:///./bot_data.db"
    # Banco da Evolution API para resolver LID → telefone real
    evolution_db_url: str = "postgresql://bot_user:@bot_postgres:5432/evolution_db"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
