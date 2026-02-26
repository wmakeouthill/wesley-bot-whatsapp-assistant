"""
Script CLI para criar ou alterar a senha do admin do painel via SSH.

Uso (na VPS via SSH):
    docker exec -it bot_api python /app/scripts/set_admin_password.py
    docker exec -it bot_api python /app/scripts/set_admin_password.py --username admin --password NOVA_SENHA
"""
import sys
import asyncio
import argparse
import uuid
from pathlib import Path

# Garante que o pacote 'app' está no PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select
from app.infrastructure.database.session import async_session, init_db
from app.domain.entities.models import AdminUser
from app.infrastructure.auth.panel_auth import hash_password


async def set_password(username: str, password: str):
    await init_db()  # garante que a tabela existe

    async with async_session() as session:
        stmt = select(AdminUser).where(AdminUser.username == username)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            user.password_hash = hash_password(password)
            print(f"✅ Senha do usuário '{username}' atualizada com sucesso.")
        else:
            user = AdminUser(
                id=str(uuid.uuid4()),
                username=username,
                password_hash=hash_password(password),
            )
            session.add(user)
            print(f"✅ Usuário '{username}' criado com sucesso.")

        await session.commit()


def main():
    parser = argparse.ArgumentParser(description="Gerencia senha do painel admin do Bot WhatsApp")
    parser.add_argument("--username", default="admin", help="Nome do usuário admin (padrão: admin)")
    parser.add_argument("--password", help="Nova senha (se não informado, será pedida interativamente)")
    args = parser.parse_args()

    password = args.password
    if not password:
        import getpass
        password = getpass.getpass(f"Nova senha para '{args.username}': ")
        confirm = getpass.getpass("Confirme a senha: ")
        if password != confirm:
            print("❌ As senhas não conferem. Operação cancelada.")
            sys.exit(1)

    if len(password) < 8:
        print("❌ A senha deve ter pelo menos 8 caracteres.")
        sys.exit(1)

    asyncio.run(set_password(args.username, password))


if __name__ == "__main__":
    main()
