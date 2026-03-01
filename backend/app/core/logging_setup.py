from __future__ import annotations

import logging
from pathlib import Path

from loguru import logger


def _intercept_stdlib_logging() -> None:
    """将标准库 logging 的日志转发到 loguru，便于 uvicorn 等输出统一格式。"""

    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)


def setup_logging(logs_dir: Path) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "backend.log"

    logger.remove()
    logger.add(
        lambda msg: print(msg, end=""),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
        level="INFO",
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
    )

    _intercept_stdlib_logging()

    logger.info("Backend logging initialized at {}", log_file)
    return log_file


def tail_file(path: Path, lines: int = 200) -> list[str]:
    if lines <= 0:
        return []
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        data = fh.readlines()
    return [line.rstrip("\n") for line in data[-lines:]]
