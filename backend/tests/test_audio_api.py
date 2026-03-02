from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import audio


class _FakeWhisperClient:
    def transcribe(self, file_obj, *, filename: str, language: str, model: str) -> str:
        assert filename == "voice.webm"
        assert language == "zh"
        assert model == "gpt-4o-transcribe"
        assert file_obj.read() == b"audio-bytes"
        file_obj.seek(0)
        return "识别结果"


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(audio.router)
    return TestClient(app)


def test_audio_transcribe_success(monkeypatch):
    monkeypatch.setattr("app.api.audio.WhisperClient", _FakeWhisperClient)
    client = _build_client()

    resp = client.post(
        "/api/audio/transcribe?language=zh",
        headers={"x-audio-filename": "voice.webm", "content-type": "audio/webm"},
        content=b"audio-bytes",
    )

    assert resp.status_code == 200
    assert resp.json() == {"text": "识别结果"}


def test_audio_transcribe_missing_key_returns_503(monkeypatch):
    class _RaiseClient:
        def __init__(self):
            raise ValueError("OPENAI_API_KEY is required for transcription")

    monkeypatch.setattr("app.api.audio.WhisperClient", _RaiseClient)
    client = _build_client()

    resp = client.post(
        "/api/audio/transcribe",
        headers={"x-audio-filename": "voice.webm", "content-type": "audio/webm"},
        content=b"audio-bytes",
    )

    assert resp.status_code == 503
    assert "OPENAI_API_KEY" in resp.text
