# Wealth Tracker API

FastAPI + SQLAlchemy 2 + PostgreSQL (psycopg 3). Requires Python 3.11+ (uses uv).

## Setup

```sh
cd api
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env   # then fill in DATABASE_URL
```

## Database migrations

Run from `api/` once `.env` exists with `DATABASE_URL`:

```sh
.venv/bin/alembic upgrade head
```

Without a database, `.venv/bin/alembic upgrade head --sql` prints the DDL.

## Run

```sh
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Health check: `curl localhost:8000/api/health`

## Deploy (Vercel)

Create a separate Vercel project with Root Directory set to `api/`. Vercel's zero-config FastAPI
detection finds `app` in `app/main.py`; Python 3.12 comes from `.python-version`, dependencies from
`requirements.txt`, and `vercel.json` pins the function region to `iad1` (next to Neon in AWS us-east).
Set these environment variables in the project:

- `DATABASE_URL`: Neon pooled URL (the PgBouncer endpoint is fine; prepared statements are disabled).
- `API_KEY`: shared secret. Every `/api` request except `GET /api/health` and CORS preflight must send `X-API-Key: <API_KEY>`.
- `CORS_ORIGINS`: JSON list including the deployed web origin.

Production migrations, run from `api/` with the production URL supplied inline (prefer the direct,
non-pooled Neon URL for migrations):

```sh
DATABASE_URL='<production url>' .venv/bin/alembic upgrade head
```

## Configuration (`.env`)

- `API_KEY`: optional shared secret; when set, requests under `/api` need an `X-API-Key` header (except health). Leave empty locally.
- `DATABASE_URL`: Postgres URL (Neon `postgresql://...?sslmode=require` works; it is rewritten to `postgresql+psycopg://`).
- `CORS_ORIGINS`: JSON list of allowed origins, default `["http://localhost:3000"]`.
