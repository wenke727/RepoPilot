from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.audio import DEFAULT_TRANSCRIBE_MODEL, WhisperClient, safe_audio_filename

router = APIRouter(prefix="/api/audio", tags=["audio"])


@router.post("/transcribe")
async def transcribe_audio(
    request: Request,
    language: str = Query(default="zh"),
    model: str = Query(default=DEFAULT_TRANSCRIBE_MODEL),
):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="audio file is required")
    filename = request.headers.get("x-audio-filename", "voice-input.webm")

    try:
        client = WhisperClient()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        text = client.transcribe(
            BytesIO(body),
            filename=safe_audio_filename(filename),
            language=language,
            model=model,
        )
        return {"text": text}
    except Exception as exc:  # pragma: no cover - defensive error mapping
        raise HTTPException(status_code=502, detail=f"transcription failed: {exc}") from exc
