"""
Utilitários de autenticação para o painel admin.
- Geração e validação de JWT
- Hash e verificação de senha (bcrypt via passlib)
"""
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Cookie
from fastapi.security import OAuth2PasswordBearer

from app.infrastructure.config.settings import settings

# ---------------------------------------------------------------------------
# Contexto de hash de senha (bcrypt)
# ---------------------------------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# OAuth2 — lê o token do header Authorization: Bearer <token>
# ---------------------------------------------------------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/panel/login", auto_error=False)

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Retorna o hash bcrypt da senha."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha plain bate com o hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Gera um JWT com os dados fornecidos."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.panel_jwt_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.panel_secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decodifica e valida o JWT. Retorna o payload ou None se inválido."""
    try:
        payload = jwt.decode(token, settings.panel_secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user_from_token(token: Optional[str]) -> str:
    """Extrai o username do token. Lança 401 se inválido."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exc
    payload = decode_token(token)
    if not payload:
        raise credentials_exc
    username: str = payload.get("sub", "")
    if not username:
        raise credentials_exc
    return username


async def get_current_user(
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    panel_token: Optional[str] = Cookie(default=None),
) -> str:
    """
    Dependency do FastAPI: autentica via JWT.
    Aceita token no header Authorization Bearer OU no cookie `panel_token`
    (para as chamadas AJAX do frontend que usam cookie de sessão).
    """
    token = bearer_token or panel_token
    return get_current_user_from_token(token)
