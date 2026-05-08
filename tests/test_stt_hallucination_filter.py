"""Verify the Whisper hallucination filter is applied at the STT provider
boundary, not at any single call site.

Pre-fix, `_is_whisper_hallucination` only ran in `wake_detector.py:335`.
Browser STT (route /api/transcribe → `whisper_client.transcribe_file`) and
any future continuous-listen path skipped it — Sapphire replied to phantom
"thank you" / "[music]" inputs after silence/noise wakeword false-positives.

The fix moved the filter into `BaseSTTProvider.transcribe_file`. Every
consumer that calls `transcribe_file` on a real STT provider now gets
filtered output for free. This test pins that contract so future loops
modifying STT can't silently regress it. Chaos scout 2026-05-07 #1.
"""
from typing import Optional

import pytest

from core.stt.hallucination import is_whisper_hallucination
from core.stt.providers.base import BaseSTTProvider


class _StubProvider(BaseSTTProvider):
    """Test double — echoes whatever was queued via `set_next`."""

    def __init__(self):
        self._next = None

    def set_next(self, text):
        self._next = text

    def _transcribe_impl(self, audio_path: str) -> Optional[str]:
        return self._next

    def is_available(self) -> bool:
        return True


def test_hallucination_function_smoke():
    assert is_whisper_hallucination("Thank you") is True
    assert is_whisper_hallucination("thanks for watching!") is True
    assert is_whisper_hallucination("[music]") is True
    assert is_whisper_hallucination("") is True
    assert is_whisper_hallucination(None) is True
    assert is_whisper_hallucination("   ") is True
    # Real speech should pass
    assert is_whisper_hallucination("what time is it") is False
    assert is_whisper_hallucination("set a timer for five minutes") is False


def test_filter_applied_at_provider_boundary():
    """transcribe_file must return None when impl returns a hallucination,
    even though impl returned the raw string. This is the contract every
    STT consumer relies on."""
    p = _StubProvider()

    p.set_next("Thank you.")
    assert p.transcribe_file("/tmp/anything.wav") is None

    p.set_next("[music]")
    assert p.transcribe_file("/tmp/anything.wav") is None

    p.set_next("")
    assert p.transcribe_file("/tmp/anything.wav") is None

    p.set_next(None)
    assert p.transcribe_file("/tmp/anything.wav") is None


def test_real_speech_passes_through():
    """Real speech must NOT be dropped — guards against an over-eager
    filter that would block normal use."""
    p = _StubProvider()

    p.set_next("turn the lights off")
    assert p.transcribe_file("/tmp/anything.wav") == "turn the lights off"

    p.set_next("what's the weather today")
    assert p.transcribe_file("/tmp/anything.wav") == "what's the weather today"


def test_punctuation_and_case_insensitive():
    """Variants of the same hallucination should all be filtered."""
    p = _StubProvider()
    for variant in [
        "Thank you", "THANK YOU", "thank you.", "  thank you  ",
        "Thanks for watching!", "thanks for watching",
    ]:
        p.set_next(variant)
        assert p.transcribe_file("/tmp/x.wav") is None, (
            f"variant {variant!r} should have been filtered"
        )
