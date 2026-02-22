from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    project_name: str = "Bot de WhatsApp (Evolution API)"
    version: str = "0.1.0"
    
    # Evolution API Settings
    evolution_api_url: str = "http://bot_evolution_api:8080" # URL interna no docker
    evolution_api_key: str = ""
    evolution_instance_name: str = "wesley_bot_session"
    
    # Gemini AI Settings
    gemini_api_key: str = "your_google_api_key_here"
    gemini_model: str = "gemini-2.0-flash"
    
    # Database Settings
    database_url: str = "sqlite+aiosqlite:///./bot_data.db"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
