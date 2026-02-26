#!/bin/sh
set -e

echo "▶ Rodando migrations Alembic (upgrade head)..."
if alembic upgrade head; then
  echo "✅ Migrations aplicadas com sucesso."
else
  echo "⚠️ Falha ao rodar alembic upgrade head. O app ainda tentará criar as tabelas via init_db()."
fi

echo "▶ Iniciando servidor FastAPI (uvicorn)..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000

