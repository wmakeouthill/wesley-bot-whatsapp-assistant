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

# Instala todas as dependências do projeto (inclui asyncpg para SQLAlchemy async)
RUN poetry install --no-root --no-interaction --no-ansi

# Falha no build se asyncpg não estiver instalado (evita erro em runtime)
RUN python -c "import asyncpg"

# Copia o resto da aplicação
COPY . .

# Expõe a porta do FastAPI
EXPOSE 8000

# Roda o servidor usando o uvicorn através do poetry
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
