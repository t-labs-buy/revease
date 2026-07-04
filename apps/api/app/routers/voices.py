"""AI voice library + on-demand preview samples."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.queue import enqueue_voice_preview
from app.storage import store
from app.voices import PREVIEW_TEXT, VOICE_IDS, VOICES

router = APIRouter(tags=["voices"])


class VoicePreview(BaseModel):
    voice_id: str


@router.get("/voices")
def list_voices() -> dict:
    return {"voices": VOICES, "preview_text": PREVIEW_TEXT}


@router.post("/voices/preview")
def preview_voice(payload: VoicePreview) -> dict:
    if payload.voice_id not in VOICE_IDS:
        raise HTTPException(status_code=404, detail="unknown voice")
    key = f"previews/{payload.voice_id}.wav"
    ready = store.exists(key)
    if not ready:
        enqueue_voice_preview(payload.voice_id)  # synthesize in the background (cached)
    return {"url": store.download_url(key), "ready": ready}
