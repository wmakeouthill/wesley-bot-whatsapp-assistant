from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    project_name: str = "Bot de WhatsApp (Evolution API)"
    version: str = "0.1.0"
    
    # Painel Admin
    panel_secret_key: str = "troque-por-uma-chave-aleatoria-e-longa-aqui"  # usado para assinar JWT
    panel_jwt_expire_minutes: int = 480  # 8 horas de sessão

    
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
    
    # Owner / Controle de IA
    # JID do seu número NESTA instância (ex: "5521983866676@s.whatsapp.net")
    # Mensagens fromMe enviadas pra este JID são interpretadas como comandos /ia
    owner_jid: str = ""
    
    # Instância 2 — Número Pessoal do Wesley
    evolution_instance_two_name: str = ""  # Ex: "wesley_bot_pessoal"
    instance_two_owner_jid: str = ""       # JID do owner nesta instância
    
    # Allowlist/Blocklist de números (separados por vírgula, sem @s.whatsapp.net)
    # Se allowlist não estiver vazia, apenas esses números recebem resposta na instância 1
    ia_allowlist: str = ""  # Ex: "5521999999999,5511888888888" (vazio = todos)
    ia_blocklist: str = ""  # Ex: "5521000000000" (números sempre bloqueados)
    
    @property
    def ia_allowlist_set(self) -> set[str]:
        """Retorna o allowlist como um set de strings para lookup O(1)."""
        return {n.strip() for n in self.ia_allowlist.split(",") if n.strip()}
    
    @property
    def ia_blocklist_set(self) -> set[str]:
        """Retorna o blocklist como um set de strings para lookup O(1)."""
        return {n.strip() for n in self.ia_blocklist.split(",") if n.strip()}
    
    # Database Settings
    # Banco da Evolution API (reaproveitado para o histórico do bot)
    evolution_db_url: str = "postgresql://bot_user:@bot_postgres:5432/evolution_db"
    
    @property
    def async_database_url(self) -> str:
        """Converte a URL do async SQLAlchemy."""
        return self.evolution_db_url.replace("postgresql://", "postgresql+asyncpg://")
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
