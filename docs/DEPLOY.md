# Deploying Wealth Tracker

Two Vercel projects from this one repo (`api/` and `web/`) plus the Neon `production` branch. All on free tiers.

```
Browser ──> web (Next.js, Vercel) ──/api/* proxy + Bearer token + X-API-Key──> api (FastAPI, Vercel, iad1) ──> Neon production (AWS us-east)
```

The browser only ever talks to the web project. The web project keeps the sign-in cookies, then forwards API calls to FastAPI with the access token and a secret key. FastAPI rejects any request without that key.

## 1. Prerequisites

- Vercel account connected to GitHub (repo `Psyphon361/wealth-track`).
- Neon project with a `production` branch.
- Local API venv set up (`api/.venv`), see `api/README.md`.

## 2. Generate secrets

```bash
openssl rand -hex 32   # use as API_KEY
openssl rand -hex 32   # use as JWT_SECRET
```

Keep both in a password manager. Your login password is chosen per account in the `app.jobs.users` CLI (see Auth rollout below), not stored as a deploy variable.

## 3. Create the tables on the production branch

1. Neon console → **Connect** → branch **production** → copy the **direct** (non-pooled) connection string.
2. From `api/`:

```bash
DATABASE_URL='<production direct connection string>' .venv/bin/alembic upgrade head
DATABASE_URL='<production direct connection string>' .venv/bin/alembic current
```

`alembic current` should print `0010 (head)`. Repeat this step whenever a new migration is added.

## 4. API project (FastAPI)

1. Vercel → **Add New… → Project** → import `Psyphon361/wealth-track`.
2. **Root Directory:** `api`. Framework preset: FastAPI (auto-detected; no build command needed).
3. **Environment variables** (Production):
   - `DATABASE_URL` = Neon production **pooled** connection string (host contains `-pooler`, keep `?sslmode=require`).
   - `API_KEY` = the first secret from step 2.
   - `JWT_SECRET` = the second secret from step 2 (signs access tokens; sign-in fails without it).
   - `ALLOWED_EMAILS` = comma-separated emails allowed to sign up (invite list), e.g. `you@example.com`.
   - `CRON_SECRET` = a new value from `openssl rand -hex 32` (bearer token for the daily AMFI cron).
4. Deploy. The function region is pinned to `iad1` by `api/vercel.json` (next to Neon us-east).
5. Check (replace with your API URL):

```bash
curl https://<api-project>.vercel.app/api/health      # {"status":"ok"}
curl -i https://<api-project>.vercel.app/api/dashboard # 401 Unauthorized
```

## 5. Web project (Next.js)

1. Vercel → **Add New… → Project** → import the same repo again.
2. **Root Directory:** `web`. Framework preset: Next.js.
3. **Environment variables** (Production):
   - `API_KEY` = same value as the API project.
   - `API_URL` = `https://<api-project>.vercel.app` (no trailing slash, no `/api`).
   - The old password-gate variables `APP_PASSWORD` and `SESSION_SECRET` are no longer read. Remove them as the last step of the Auth rollout.
4. Deploy. Then **Settings → Functions → Function Region** → `Washington, D.C. (iad1)` and redeploy, so the proxy sits next to the API.

## 6. Load MF master data

The MF scheme picker needs `mf_schemes` and `mf_nav_latest` filled. Run the import once; after that the daily cron keeps them current.

Either locally, from `api/` (use the production **direct** connection string):

```bash
DATABASE_URL='<production direct connection string>' .venv/bin/python -m app.jobs.amfi_import
```

Or trigger the cron endpoint once against the deployed API:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" https://<api-project>.vercel.app/api/cron/amfi
```

The import takes about 15–20 s.

## 7. Smoke test

1. Open the web URL → you are redirected to `/login`.
2. Wrong password → "Incorrect email or password". Right email and password → Dashboard.
3. Add a holding → it appears on Portfolio and Dashboard.
4. Log out (sidebar footer) → back to `/login`.

The production database starts empty; your `dev` branch data stays in dev.

## Automatic migrations (GitHub Actions)

`.github/workflows/api-deploy.yml` runs `alembic upgrade head` against the Neon production branch, then triggers the API project's Vercel deploy hook. It runs on pushes to `main` that touch `api/**` (or the workflow file), and manually via **Actions → API migrate and deploy → Run workflow**. `api/vercel.json` sets `git.deploymentEnabled.main = false`, so Vercel no longer auto-deploys the API on push; the hook is the only production deploy path (preview deploys on other branches are unaffected). The web project still auto-deploys.

One-time setup (you):

1. Vercel → API project → **Settings → Git → Deploy Hooks** → create a hook for branch `main`; copy the URL.
2. GitHub repo → **Settings → Secrets and variables → Actions** → add:
   - `PROD_DATABASE_URL` = Neon production **direct** (non-pooled) connection string.
   - `VERCEL_API_DEPLOY_HOOK` = the hook URL from step 1.
   - `OWNER_EMAIL` (environment secret of `production`, see below) = your login email.
   (If you use an environment, add them as environment secrets of `production` instead.)
3. Optional: **Settings → Environments → New environment** named `production`, with required reviewers, so each migration waits for your approval.
4. Only if `deploymentEnabled` in `vercel.json` does not stop auto-deploys: Vercel API project → **Settings → Git → Ignored Build Step** → "Don't build anything" (or disconnect auto-deploy). Check afterwards that the deploy hook still produces a production deployment.

Write migrations backward compatible (expand, then contract): the web project deploys independently and the old API code keeps running until the new deploy lands.

Fallback: the manual `alembic upgrade head` in step 3 still works.

## Auth rollout (one-time)

Sign-in replaces the shared password. Migration `0010` adds users, refresh tokens and login attempts, and `user_id` on every holdings table. Do these steps in order:

1. **Set the secrets.** API project: `JWT_SECRET` and `ALLOWED_EMAILS` (your email). GitHub `production` environment: `OWNER_EMAIL` (your email).
2. **Push to `main`.** The Action runs `alembic upgrade head` on prod, so the database reaches `0010`. Existing holdings are assigned to the `OWNER_EMAIL` user, which is created without a password. The migration fails with a clear error if holdings exist and `OWNER_EMAIL` is unset.
   - On a database with no holdings the migration does not create the owner. Use `create` in step 3 instead of `set-password`.
3. **Set your password locally.** Use the production **pooled** connection string from `api/` (prod credentials stay with you). The command prompts for the password:

```bash
cd api && DATABASE_URL='<production pooled connection string>' .venv/bin/python -m app.jobs.users set-password --email <owner email>
```

4. **Log in** on the web project with that email and password. Your existing holdings should appear.
5. **Remove the old variables.** Web project: delete `APP_PASSWORD` and `SESSION_SECRET`, then redeploy.

## Day-to-day

- Every push to `main` redeploys the web project automatically. Pushes touching `api/` first run migrations, then deploy the API via the GitHub Actions workflow (see above).
- Change a user's password: `cd api && DATABASE_URL='<production pooled connection string>' .venv/bin/python -m app.jobs.users set-password --email <email>`.
- Lock an account: the same command with `deactivate --email <email>`. Sign-in and token refresh stop at once. `list` shows all users.
- Rotate the API key: update `API_KEY` in **both** projects, then redeploy both.
- Local development: `npm run dev` from the repo root. Sign-in is always required; create a local account with `cd api && .venv/bin/python -m app.jobs.users create --email <email>` (sets the password at the prompt; the allowlist is not checked here).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Sign-in or refresh returns 500 | `JWT_SECRET` missing in the API project |
| Sign-up says "Sign-ups are invite-only" | Email not in `ALLOWED_EMAILS` (API project) |
| Owner gets "Incorrect email or password" after the rollout | No password set yet: run `set-password` (Auth rollout step 3) |
| Pages load but data shows "Upstream API unreachable" (502) | `API_URL` wrong or API project not deployed |
| Data requests return 401 after logging in | `API_KEY` differs between the two projects |
| API errors mentioning the database | `DATABASE_URL` wrong, not the pooled string, or migrations not run on production (step 3) |
| First request after a while is slow | Cold start of the serverless function; subsequent requests are fast |
| Local AMFI import fails with an SSL certificate error | uv's Python has no CA bundle on macOS; set `SSL_CERT_FILE` to a system CA bundle and rerun the import |
