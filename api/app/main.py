import logging
import secrets

from starlette.exceptions import HTTPException as StarletteHTTPException

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import assets, auth, cas_import, cron, holdings, master, portfolio
from app.routers.assets import ASSET_LABELS

app = FastAPI(title="Wealth Tracker API")

# Pydantic default messages rewritten to match the web forms.
_MESSAGES = {
    "missing": "Required",
    "int_parsing": "Enter a valid number",
    "int_type": "Enter a valid number",
    "int_from_float": "Enter a valid number",
    "float_parsing": "Enter a valid number",
    "float_type": "Enter a valid number",
    "decimal_parsing": "Enter a valid number",
    "decimal_type": "Enter a valid number",
}


_FIELD_LABELS = {
    "avg_nav": "Average NAV",
    "ytm": "YTM",
    "tenure_years": "Tenure",
    "tenure_months": "Tenure",
    "tenure_days": "Tenure",
}

logger = logging.getLogger("app")


def _field_label(loc) -> str | None:
    fields = [part for part in loc if isinstance(part, str) and part != "body"]
    if not fields:
        return None
    field = fields[-1]
    return _FIELD_LABELS.get(field) or field.replace("_", " ").capitalize()


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        message = _MESSAGES.get(error["type"])
        errors.append({**error, "msg": message} if message else error)
    description = "Some values are invalid."
    if errors:
        first = errors[0]
        label = _field_label(first.get("loc", ()))
        description = f"{label}: {first['msg']}" if label else str(first["msg"])
    is_filter_query = request.method == "GET" and request.url.path.startswith("/api/holdings/")
    is_nav_lookup = request.method == "GET" and request.url.path.endswith("/nav")
    if request.url.path.startswith("/api/auth/"):
        message = "Check the highlighted fields"
    elif is_nav_lookup:
        message = "Invalid date"
    elif is_filter_query:
        message = "Invalid filters"
    else:
        message = "Couldn't save — check the highlighted fields"
    return JSONResponse(
        status_code=422,
        content={
            "message": message,
            "description": description,
            "detail": jsonable_encoder(errors),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and {"message", "description"} <= exc.detail.keys():
        message = exc.detail["message"]
        description = exc.detail["description"]
    elif exc.status_code == 401:
        message = "Not authorised"
        description = "Your session may have expired. Log in again."
    elif exc.status_code == 404:
        parts = request.url.path.strip("/").split("/")
        slug = parts[2] if len(parts) == 4 and parts[:2] == ["api", "assets"] else None
        if slug in ASSET_LABELS:
            message = f"{ASSET_LABELS[slug]} not found"
            description = "It may have been deleted already."
        elif parts[:3] == ["api", "master", "mf"] and len(parts) in (4, 5):
            message = "Scheme not found"
            description = "It isn't in the AMFI scheme list."
        else:
            message = "Not found"
            description = "The requested resource doesn't exist."
    else:
        message = "Request failed"
        description = str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": message, "description": description, "detail": jsonable_encoder(exc.detail)},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "message": "Something went wrong on the server",
            "description": type(exc).__name__,
            "detail": "Internal Server Error",
        },
    )


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


api_router.include_router(auth.router)
api_router.include_router(assets.router)
api_router.include_router(portfolio.router)
api_router.include_router(holdings.router)
api_router.include_router(master.router)
api_router.include_router(cas_import.router)

app.include_router(api_router)
# Not behind X-API-Key: authenticated by CRON_SECRET instead.
app.include_router(cron.router, prefix="/api")
