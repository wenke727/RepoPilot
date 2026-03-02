from __future__ import annotations

import os
from pathlib import Path
from typing import Any, BinaryIO


def _build_openai_client(**kwargs: Any):
    from openai import OpenAI

    return OpenAI(**kwargs)

DEFAULT_TRANSCRIBE_MODEL = "gpt-4o-transcribe"


class WhisperClient:
    """OpenAI transcription helper for uploading local audio files."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 60,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not key.strip():
            raise ValueError("OPENAI_API_KEY is required for transcription")
        kwargs: dict[str, str | int] = {
            "api_key": key.strip(),
            "timeout": timeout,
        }
        if base_url is not None:
            kwargs["base_url"] = base_url
        self._client = _build_openai_client(**kwargs)

    def transcribe(
        self,
        file_obj: BinaryIO,
        *,
        filename: str,
        language: str = "zh",
        model: str = DEFAULT_TRANSCRIBE_MODEL,
    ) -> str:
        response = self._client.audio.transcriptions.create(
            model=model,
            file=(filename, file_obj.read()),
            language=language,
            response_format="text",
        )
        return getattr(response, "text", str(response)).strip()


def safe_audio_filename(raw_name: str | None) -> str:
    if not raw_name:
        return "audio.webm"
    return Path(raw_name).name
