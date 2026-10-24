# Wealth Tracker API

FastAPI + SQLAlchemy 2 + PostgreSQL (psycopg 3). Requires Python 3.11+ (uses uv).

## Setup

```sh
cd api
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env   # then fill in DATABASE_URL
```

## Run

```sh
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Health check: `curl localhost:8000/api/health`

## Configuration (`.env`)

- `DATABASE_URL`: Postgres URL (Neon `postgresql://...?sslmode=require` works; it is rewritten to `postgresql+psycopg://`).
- `CORS_ORIGINS`: JSON list of allowed origins, default `["http://localhost:3000"]`.
