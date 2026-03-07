from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import set_agent_driver, set_exec_mode


@pytest.fixture(autouse=True)
def _reset_runtime_mode_overrides():
    set_exec_mode("")
    set_agent_driver("")
    yield
    set_exec_mode("")
    set_agent_driver("")
