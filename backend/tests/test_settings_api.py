from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import settings as settings_api
from app.config import load_settings, set_agent_driver


def _build_client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.state.settings = load_settings(tmp_path)
    app.include_router(settings_api.router)
    return TestClient(app)


def test_get_agent_driver_returns_supported_and_reserved(tmp_path: Path):
    set_agent_driver("")
    client = _build_client(tmp_path)

    resp = client.get("/api/settings/agent-driver")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["agent_driver"] == "CLAUDE_KIMI"
    assert payload["supported"] == ["CLAUDE", "CLAUDE_KIMI", "CLAUDE_GLM"]
    assert payload["reserved"] == ["CURSOR_CLI"]


def test_put_agent_driver_glm_success(tmp_path: Path):
    set_agent_driver("")
    client = _build_client(tmp_path)

    resp = client.put("/api/settings/agent-driver", json={"agent_driver": "CLAUDE_GLM"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["agent_driver"] == "CLAUDE_GLM"
    assert payload["supported"] == ["CLAUDE", "CLAUDE_KIMI", "CLAUDE_GLM"]
    assert payload["reserved"] == ["CURSOR_CLI"]

    check = client.get("/api/settings/agent-driver")
    assert check.status_code == 200
    assert check.json()["agent_driver"] == "CLAUDE_GLM"


def test_put_agent_driver_claude_success(tmp_path: Path):
    set_agent_driver("")
    client = _build_client(tmp_path)

    resp = client.put("/api/settings/agent-driver", json={"agent_driver": "CLAUDE"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["agent_driver"] == "CLAUDE"
    assert payload["supported"] == ["CLAUDE", "CLAUDE_KIMI", "CLAUDE_GLM"]


def test_put_agent_driver_cursor_cli_rejected(tmp_path: Path):
    set_agent_driver("")
    client = _build_client(tmp_path)

    resp = client.put("/api/settings/agent-driver", json={"agent_driver": "CURSOR_CLI"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "DRIVER_RESERVED_NOT_IMPLEMENTED"

    check = client.get("/api/settings/agent-driver")
    assert check.status_code == 200
    assert check.json()["agent_driver"] == "CLAUDE_KIMI"
