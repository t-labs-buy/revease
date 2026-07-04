"""AI voice library. `id`s are Kokoro voices (high-quality, keyless, local — runs
via onnxruntime). Piper ids (en_US-*) and OpenAI ids also work through the adapter."""

from __future__ import annotations

PREVIEW_TEXT = "Hi, this is a sample of my voice for your Refract video."

VOICES = [
    {"id": "af_heart", "name": "Heart", "gender": "Female", "accent": "American", "style": "Warm"},
    {"id": "af_bella", "name": "Bella", "gender": "Female", "accent": "American", "style": "Conversational"},
    {"id": "af_sarah", "name": "Sarah", "gender": "Female", "accent": "American", "style": "Clear"},
    {"id": "am_adam", "name": "Adam", "gender": "Male", "accent": "American", "style": "Confident"},
    {"id": "am_michael", "name": "Michael", "gender": "Male", "accent": "American", "style": "Calm"},
    {"id": "bf_emma", "name": "Emma", "gender": "Female", "accent": "British", "style": "Friendly"},
    {"id": "bm_george", "name": "George", "gender": "Male", "accent": "British", "style": "Informative"},
]

VOICE_IDS = {v["id"] for v in VOICES}
DEFAULT_VOICE = "af_sarah"
