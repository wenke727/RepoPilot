from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api import auth, audio, board, health, logs, notifications, repos, settings, tasks
from app.middleware.auth_middleware import AuthMiddleware
from app.config import load_settings
from app.core.logging_setup import setup_logging
from app.core.runner import TaskRunner
from app.core.scheduler import Scheduler
from app.store.json_store import JsonStore

app_settings = load_settings()
setup_logging(app_settings.state_dir / "logs")
logger.info(
    "Config loaded",
    auth_enabled=app_settings.auth_enabled,
    state_dir=str(app_settings.state_dir),
)
store = JsonStore(app_settings.state_dir, app_settings.repos_dir)
runner = TaskRunner(store, app_settings)
scheduler = Scheduler(store, runner, app_settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = app_settings
    app.state.store = store
    app.state.runner = runner
    app.state.scheduler = scheduler

    store.rescan_repos()
    logger.info("Repos rescanned, starting scheduler")
    scheduler.start()
    try:
        yield
    finally:
        logger.info("Shutting down scheduler")
        scheduler.stop()


app = FastAPI(title="Claude Code Web Manager", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware, settings=app_settings)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(settings.router)
app.include_router(repos.router)
app.include_router(tasks.router)
app.include_router(audio.router)
app.include_router(board.router)
app.include_router(notifications.router)
app.include_router(logs.router)
