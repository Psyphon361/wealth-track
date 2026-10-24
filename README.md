# Wealth Tracker (prototype v1)

Personal wealth tracking for FD, RD, stocks, bonds, and mutual funds.

## Layout

- `api/` - FastAPI backend
- `web/` - Next.js frontend
- `docs/PLAN.md` - project plan

## Stack

- Next.js + shadcn (web)
- FastAPI (api)
- Neon Postgres (database)
- npm (web package manager)

## Setup

Prerequisites: Node.js (with npm) and [uv](https://docs.astral.sh/uv/).

1. Create the API env file: `cp api/.env.example api/.env` and fill in the values.
2. One-time install of the root tooling: `npm install`.
3. Start both services: `npm run dev`.
   - Web: http://localhost:3000
   - API: http://localhost:8000/api (docs at http://localhost:8000/docs)

Code changes in `api/` and `web/` reload automatically.
