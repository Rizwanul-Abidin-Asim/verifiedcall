"""FastAPI entrypoint for VerifiedCall.

Routers are registered here as each phase lands. Right now this is skeleton only:
a /health endpoint so we can prove the app boots.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

app = FastAPI(
    title="VerifiedCall",
    description="APP fraud detection via CAMARA network signals + AI voice intervention",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Liveness probe. Reports which switches are active but never leaks secrets."""
    return {
        "status": "ok",
        "service": "verified-call",
        "version": "0.1.0",
        "env": settings.app_env,
        "demo_mode": settings.demo_mode,
        "voice_mock": settings.voice_mock,
    }
