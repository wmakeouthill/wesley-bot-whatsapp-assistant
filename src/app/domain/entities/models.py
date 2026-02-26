from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.infrastructure.database.base import Base

class Cliente(Base):
    __tablename__ = "bot_clientes"
    
    id = Column(String(36), primary_key=True)
    whatsapp_id = Column(String(50), unique=True, nullable=False, index=True) # Ex: 5511999999999@s.whatsapp.net
    nome = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Historico do cliente
    mensagens = relationship("Mensagem", back_populates="cliente", cascade="all, delete-orphan")

class Mensagem(Base):
    __tablename__ = "bot_mensagens"
    
    id = Column(String(36), primary_key=True)
    id_cliente = Column(String(36), ForeignKey("bot_clientes.id"), index=True)
    texto = Column(Text, nullable=True)
    mensagem_id_whatsapp = Column(String(200), unique=True, index=True) # Para evitar recriar a mesma mensagem que ja foi respondida
    direcao = Column(String(10)) # RECEBIDA (do cliente pro bot) ou ENVIADA (do bot pro cliente)
    data_hora = Column(DateTime, default=datetime.utcnow)

    # Relacionamento de volta pro cliente
    cliente = relationship("Cliente", back_populates="mensagens")


class BotConfig(Base):
    """Armazena o estado de ativação da IA por instância e (opcionalmente) por chat.

    Prioridade:
      1. Config por chat_jid específico (sobrescreve o global)
      2. Config global (chat_jid IS NULL) — default da instância inteira
      3. Se não existir nenhuma config, considera IA ativa por padrão.
    """
    __tablename__ = "bot_config"
    __table_args__ = (UniqueConstraint("instancia", "chat_jid", name="uq_bot_config_instancia_chat"),)

    id         = Column(String(36), primary_key=True)
    instancia  = Column(String(100), nullable=False, index=True)  # ex: "wesley_bot_session"
    chat_jid   = Column(String(100), nullable=True, index=True)   # NULL = config global da instância
    ia_ativa   = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AllowBlockEntry(Base):
    """Entrada de allowlist/blocklist por número e (opcionalmente) por instância.

    - tipo: 'allow' ou 'block'
    - numero: telefone sem sufixo JID (ex: 5521999999999)
    - instancia: opcional, se quiser restringir a uma instância específica
    """

    __tablename__ = "bot_allow_block"

    id = Column(String(36), primary_key=True)
    instancia = Column(String(100), nullable=True, index=True)
    numero = Column(String(50), nullable=False, index=True)
    tipo = Column(String(10), nullable=False, index=True)  # "allow" ou "block"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("instancia", "numero", "tipo", name="uq_bot_allow_block_instancia_numero_tipo"),
    )


class AdminUser(Base):
    """Usuário administrador do painel web.
    Senha gerenciada via SSH com o script scripts/set_admin_password.py.
    """
    __tablename__ = "admin_user"

    id            = Column(String(36), primary_key=True)
    username      = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)  # bcrypt hash
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
