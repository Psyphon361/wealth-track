import secrets

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import assets, portfolio

app = FastAPI(title="Wealth Tracker API")


def require_api_key(request: Request) -> None:
    """Enforce X-API-Key when API_KEY is configured; health and preflight are exempt."""
    expected = settings.api_key
    if not expected:
        return
    if request.method == "OPTIONS" or request.url.path == "/api/health":
        return
    provided = request.headers.get("x-api-key", "")
    if not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


@api_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


api_router.include_router(assets.router)
api_router.include_router(portfolio.router)

app.include_router(api_router)
