# core/routes/body.py — endpoints the Pi-based body service POSTs to.
#
# LAN-only by design. The body posts audio captured after a wakeword fire;
# brain transcribes, routes through process_llm_query (same path as the
# brain's own wakeword detector), and sends the response back through the
# body_speak tool so TTS plays on the Pi's BT speaker.
#
# Auth: bearer token if SAPPH_BODY_BRAIN_TOKEN is set (Pi-side env var
# SAPPH_BRAIN_TOKEN must match). If unset, LAN-trust mode — no auth.
# Suitable for closed LAN; harden when this leaves the house.

import asyncio
import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile

from core.api_fastapi import get_system

logger = logging.getLogger(__name__)
router = APIRouter()

# Optional shared bearer for Pi → brain auth. Set in environment if you
# want the endpoint locked down; leave unset for open-LAN.
_BRAIN_AUTH_TOKEN = os.environ.get("SAPPH_BODY_BRAIN_TOKEN", "").strip()


def _verify_brain_auth(authorization: Optional[str]):
    """Token check if SAPPH_BODY_BRAIN_TOKEN is set. No-op otherwise."""
    if not _BRAIN_AUTH_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    if authorization.split(" ", 1)[1].strip() != _BRAIN_AUTH_TOKEN:
        raise HTTPException(401, "invalid bearer token")


@router.post("/api/body/wake")
async def handle_body_wake(
    audio: UploadFile = File(...),
    x_body_name: Optional[str] = Header(default="sapphire-pi", alias="X-Body-Name"),
    authorization: Optional[str] = Header(default=None),
    system=Depends(get_system),
):
    """Pi posts audio captured immediately after a wakeword fire. Brain:
      1. transcribes via whisper
      2. routes through process_llm_query (LLM + plugins)
      3. sends the response back via body_speak tool → TTS on Pi BT speaker
    Returns JSON status. The Pi logs the response but doesn't act on it
    further — the body_speak side-effect is the actual user-facing reply."""
    _verify_brain_auth(authorization)
    logger.info(f"[body/wake] from {x_body_name!r}, content-type={audio.content_type}")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "empty audio upload")

    # Spool to disk — whisper transcribe_file expects a path
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        if not getattr(system, "whisper_client", None):
            raise HTTPException(503, "STT not available on brain")

        # Transcribe — runs in a thread to keep the event loop free
        text = await asyncio.to_thread(system.whisper_client.transcribe_file, tmp_path)
        if not text or not text.strip():
            logger.info("[body/wake] no speech transcribed (silence/hallucination)")
            return {"ok": True, "transcribed": "", "response": None}
        logger.info(f"[body/wake] transcribed {len(text)} chars")

        # LLM dispatch — skip local TTS, we'll route to body. Same processing
        # path the on-brain wakeword detector uses; just different output sink.
        response = await asyncio.to_thread(
            system.process_llm_query, text.strip(), True  # skip_tts=True
        )
        if not response:
            logger.info("[body/wake] no LLM response")
            return {"ok": True, "transcribed": text, "response": None}

        # Route response back to body via the body_speak tool. We invoke it
        # explicitly through function_manager so the call works even when
        # body tools aren't in the active toolset (e.g. a non-body chat).
        try:
            fm = system.llm_chat.function_manager
            speak_result = await asyncio.to_thread(
                fm.execute_function,
                "body_speak",
                {"text": response, "body_name": x_body_name},
                None,            # scopes
                {"body_speak"},  # allowed_tools — force-allow regardless of toolset
            )
            logger.info(f"[body/wake] body_speak: {str(speak_result)[:120]}")
        except Exception as e:
            # Don't fail the request — text was processed; the TTS routing
            # just didn't make it back. Logged for debug.
            logger.error(f"[body/wake] body_speak dispatch failed: {e!r}")

        return {"ok": True, "transcribed": text, "response": response[:400]}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.get("/api/body/health")
async def body_health(_system=Depends(get_system)):
    """Lightweight liveness probe for body → brain reachability."""
    return {"ok": True}
