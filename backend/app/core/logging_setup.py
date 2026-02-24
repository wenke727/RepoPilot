from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(logs_dir: Path) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "backend.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    # Route uvicorn and app logs through root handlers.
    for name in ["uvicorn", "uvicorn.error", "uvicorn.access", "app"]:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(logging.INFO)

    logging.getLogger("app").info("Backend logging initialized at %s", log_file)
    return log_file


def tail_file(path: Path, lines: int = 200) -> list[str]:
    if lines <= 0:
        return []
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        data = fh.readlines()
    return [line.rstrip("\n") for line in data[-lines:]]
