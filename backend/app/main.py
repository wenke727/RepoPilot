from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import board, health, logs, notifications, repos, settings, tasks
from app.config import load_settings
from app.core.logging_setup import setup_logging
from app.core.runner import TaskRunner
from app.core.scheduler import Scheduler
from app.store.json_store import JsonStore

settings = load_settings()
setup_logging(settings.state_dir / "logs")
store = JsonStore(settings.state_dir, settings.repos_dir)
runner = TaskRunner(store, settings)
scheduler = Scheduler(store, runner, settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    app.state.store = store
    app.state.runner = runner
    app.state.scheduler = scheduler

    store.rescan_repos()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(title="Claude Code Web Manager", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(settings.router)
app.include_router(repos.router)
app.include_router(tasks.router)
app.include_router(board.router)
app.include_router(notifications.router)
app.include_router(logs.router)
