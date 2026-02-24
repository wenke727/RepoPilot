from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.core.runner import TaskRunner
from app.core.scheduler import Scheduler
from app.store.json_store import JsonStore


def get_store(request: Request) -> JsonStore:
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_runner(request: Request) -> TaskRunner:
    return request.app.state.runner


def get_scheduler(request: Request) -> Scheduler:
    return request.app.state.scheduler
