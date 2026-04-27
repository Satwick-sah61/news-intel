"""
News Intelligence — FastAPI entry point.

Start with:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.session import init_db, AsyncSessionLocal
from scheduler.jobs import start_scheduler, stop_scheduler

# ── API routers ──────────────────────────────────────────────────────────────
from api.topics import router as topics_router
from api.articles import router as articles_router
from api.timeline import router as timeline_router
from api.chat import router as chat_router
from api.perception import router as perception_router
from api.pipeline import router as pipeline_router
from api.stream import router as stream_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up…")
    await init_db()
    async with AsyncSessionLocal() as session:
        await start_scheduler(session)
    yield
    logger.info("Shutting down…")
    stop_scheduler()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="News Intelligence API",
    description="AI-powered news gathering, analysis, and Q&A platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(topics_router)
app.include_router(articles_router)
app.include_router(timeline_router)
app.include_router(chat_router)
app.include_router(perception_router)
app.include_router(pipeline_router)
app.include_router(stream_router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}


@app.get("/", tags=["meta"])
async def root():
    return {
        "name": "News Intelligence API",
        "docs": "/docs",
        "health": "/health",
    }
