"""Whisper hallucination filter — shared by all STT consumers.

Whisper frequently confabulates canned phrases on silence, ambient noise, or
off-language input (the training set was heavily YouTube captions). Without
filtering, a wakeword false-positive at 3am makes Sapphire reply to phantom
"Thank you for watching" / "[music]" inputs.

The filter lives at the STT provider boundary so wakeword, browser STT, and
any future continuous-listen / voice-mode path inherit it automatically.
Previously this filter only ran in the wakeword call site, leaving every
other consumer unprotected.

Chaos scout 2026-05-07 #1.
"""

# Case-insensitive exact-match (after strip + trailing-punct removal).
_WHISPER_HALLUCINATIONS = {
    'thank you',
    'thanks for watching',
    'thanks for watching!',
    'thanks for watching.',
    'you',
    '.',
    'bye',
    'bye.',
    'bye!',
    'goodbye',
    'goodbye.',
    "i'm sorry",
    "i'm sorry.",
    'subtitles by',
    '[music]',
    '[laughter]',
    '[applause]',
    'thanks.',
    'thank you.',
    'okay.',
    'ok.',
}


def is_whisper_hallucination(text) -> bool:
    """Return True if `text` matches a known Whisper hallucination phrase
    (or is empty/whitespace — same downstream treatment).

    Accepts None / empty / non-string defensively — providers diverge on
    return type (None vs '' vs raise) and we don't want to amplify that
    inconsistency by raising AttributeError on a defensive caller.
    """
    if not text or not isinstance(text, str):
        return True
    normalized = text.strip().lower()
    if not normalized:
        return True
    if normalized in _WHISPER_HALLUCINATIONS:
        return True
    stripped = normalized.rstrip('.!?').strip()
    return stripped in _WHISPER_HALLUCINATIONS
