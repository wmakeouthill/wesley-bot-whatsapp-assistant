# Dockerfile
FROM python:3.11-slim

# Variáveis de ambiente
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=1.8.2 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONPATH="/app/src"

# Adicionar o Poetry no PATH
ENV PATH="$POETRY_HOME/bin:$PATH"

# Dependências de sistema (necessárias para compilar alguns pacotes C++ como Faiss e dependências SQLite)
RUN apt-get update \
    && apt-get install -y curl build-essential \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia dependências primeiro (aproveita cache do Docker)
# poetry.lock é necessário para instalação reproduzível (inclui asyncpg para PostgreSQL assíncrono)
COPY pyproject.toml poetry.lock ./

# Sincroniza lock com pyproject.toml (evita falha quando lock está desatualizado)
RUN poetry lock --no-update

# Instala todas as dependências do projeto (inclui asyncpg para SQLAlchemy async)
RUN poetry install --no-root --no-interaction --no-ansi

# Falha no build se asyncpg não estiver instalado (evita erro em runtime)
RUN python -c "import asyncpg"

# Copia o resto da aplicação
COPY . .

# Expõe a porta do FastAPI
EXPOSE 8000

# EntryPoint que aplica migrations Alembic antes de subir o uvicorn
# Usa /bin/sh para não depender da permissão de execução do script (evita "permission denied" no Linux)
ENTRYPOINT ["/bin/sh", "/app/docker-entrypoint.sh"]
