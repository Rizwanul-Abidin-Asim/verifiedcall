"""FastAPI entrypoint for VerifiedCall."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import decisions, metrics, stream, transactions
from app.camara.base import close_client, get_client
from app.config import settings
from app.db.session import dispose_engine
from app.voice import webhooks as voice_webhooks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-18s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the shared HTTP client up front. A cold connection to Nokia costs about a
    # second; a warm one costs about 250ms, and the first request of a demo should not
    # be the slow one.
    get_client()
    log.info("startup provider=%s demo_mode=%s voice_mock=%s",
             settings.llm_provider, settings.demo_mode, settings.voice_mock)
    yield
    await close_client()
    await dispose_engine()
    log.info("shutdown complete")


app = FastAPI(
    title="VerifiedCall",
    description="APP fraud detection via CAMARA network signals and AI voice intervention",
    version="0.2.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def catch_everything(request: Request, call_next):
    """Turn any unhandled failure into a clear JSON error.

    This is a middleware rather than only an exception handler, and it is registered
    BEFORE the CORS middleware on purpose. Starlette builds the stack so the last
    middleware added sits outermost, and a response produced by an exception handler is
    generated outside the CORS layer, so it carries no Access-Control-Allow-Origin
    header. The browser then reports a CORS failure and the real cause is invisible.

    Found exactly that way: the database was down, and the checkout showed a CORS error
    instead of "we could not reach the payment service". Catching in here means the
    error response passes back out through CORS and the frontend can read it.
    """
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001 - the demo surface never sees a traceback
        log.exception("api.unhandled path=%s %r", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error",
                     "detail": "The service could not complete this request."},
        )


# Added last, so it wraps everything above and labels error responses too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Backstop for anything the middleware cannot catch."""
    log.exception("api.unhandled_outer path=%s %r", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error",
                 "detail": "The service could not complete this request."},
    )


app.include_router(transactions.router)
app.include_router(decisions.router)
app.include_router(stream.router)
app.include_router(voice_webhooks.router)
app.include_router(metrics.router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    """Liveness probe. Reports which switches are active but never leaks secrets."""
    return {
        "status": "ok",
        "service": "verified-call",
        "version": "0.2.0",
        "env": settings.app_env,
        "demo_mode": settings.demo_mode,
        "voice_mock": settings.voice_mock,
        "llm_provider": settings.llm_provider,
    }
