# Dockerfile
### Stage 1: Builder (Poetry + toolchain) ###############################
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=1.8.2 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=false

ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /app

# Dependências de build (faiss, psycopg2, etc.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Apenas arquivos de dependência para maximizar cache
COPY pyproject.toml poetry.lock ./

# Gera requirements.txt reproduzível a partir do lock do Poetry
RUN poetry lock --no-update \
    && poetry export -f requirements.txt --output requirements.txt --without-hashes


### Stage 2: Runtime enxuto #############################################
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app/src"

WORKDIR /app

# Copia apenas o requirements já resolvido do builder
COPY --from=builder /app/requirements.txt /app/requirements.txt

# Instala dependências em camada única e sem cache de pip
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copia o restante da aplicação
COPY . .

EXPOSE 8000

# Mantém o mesmo entrypoint atual (alembic + uvicorn)
ENTRYPOINT ["/bin/sh", "/app/docker-entrypoint.sh"]
