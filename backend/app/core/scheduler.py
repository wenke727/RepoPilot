from __future__ import annotations

import threading
import time

from loguru import logger

from app.config import Settings
from app.core.runner import TaskRunner
from app.models import Task
from app.store.json_store import JsonStore


class Scheduler:
    def __init__(self, store: JsonStore, runner: TaskRunner, settings: Settings) -> None:
        self.log = logger.bind(component="scheduler")
        self.store = store
        self.runner = runner
        self.settings = settings
        self._threads: list[threading.Thread] = []
        self._janitor_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._threads:
            return
        self.log.info("Starting scheduler with {} workers", self.settings.workers)

        for idx in range(self.settings.workers):
            worker_id = f"worker-{idx}"
            thread = threading.Thread(target=self._worker_loop, args=(worker_id,), daemon=True)
            thread.start()
            self._threads.append(thread)

        self._janitor_thread = threading.Thread(target=self._janitor_loop, daemon=True)
        self._janitor_thread.start()

    def stop(self) -> None:
        self.log.info("Stopping scheduler")
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads = []
        if self._janitor_thread:
            self._janitor_thread.join(timeout=2)
            self._janitor_thread = None

    def request_cancel(self, task_id: str) -> None:
        self.log.info("Cancel requested for task {}", task_id)
        self.runner.cancel(task_id)

    def _worker_loop(self, worker_id: str) -> None:
        self.log.info("Worker loop started: {}", worker_id)
        while not self._stop_event.is_set():
            task = self.store.claim_next_task(worker_id)
            if task is None:
                time.sleep(1)
                continue

            self.log.info("Worker {} claimed task={} mode={}", worker_id, task.id, task.mode.value)
            self._safe_run(worker_id, task)

    def _safe_run(self, worker_id: str, task: Task) -> None:
        try:
            self.runner.run_task(task, worker_id)
        except Exception as exc:  # pragma: no cover
            self.log.exception("Worker {} crashed while running task={}", worker_id, task.id)
            self.store.update_task(
                task.id,
                {
                    "status": "FAILED",
                    "error_code": "SCHEDULER_CRASH",
                    "error_message": str(exc),
                },
            )

    def _janitor_loop(self) -> None:
        while not self._stop_event.is_set():
            deleted = self.store.cleanup_old_logs(self.settings.logs_retention_days)
            if deleted > 0:
                self.log.info("Log cleanup deleted {} files", deleted)
            for _ in range(3600):
                if self._stop_event.is_set():
                    break
                time.sleep(1)
