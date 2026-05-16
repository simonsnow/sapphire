"""Silero VAD wrapper — drop-in replacement for amplitude-based VAD.

Lazy-downloads the ONNX model to user/models/silero_vad.onnx on first use,
then runs inference via onnxruntime (no torch/torchaudio dep). Designed to
replace _is_silent() in core/stt/recorder.py.

Silero VAD wants 16kHz mono float32 audio in fixed chunk sizes:
  - 512 samples (32ms) for 16kHz
  - 256 samples (16ms) for 8kHz
The model is stateful — each call updates a hidden state from the previous
call. Reset state at the start of each recording session.

Why not the silero-vad pip package: it pulls torchaudio 2.11 which conflicts
with our pinned torch 2.10. Using the ONNX directly is also lighter — single
~2.3MB file, runs on the onnxruntime we already ship.
"""
import logging
import os
import threading
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Stable upstream — snakers4/silero-vad master branch
SILERO_VAD_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
SILERO_VAD_SHA256 = None  # Not pinned for now; could add later if abuse becomes a concern

PROJECT_ROOT = Path(__file__).parent.parent.parent
MODEL_CACHE_PATH = PROJECT_ROOT / "user" / "models" / "silero_vad.onnx"

# Silero v5 ONNX takes (audio_chunk + leading context, state, sr) and returns
# (speech_prob, new_state). Critical detail learned the hard way 2026-05-16:
# the model expects the LAST 64 samples (at 16kHz) of the previous chunk
# prepended to the new chunk, for waveform continuity. Without that context
# every chunk is scored as a cold-start fragment and real speech reads as ~0.
_SILERO_STATE_SHAPE = (2, 1, 128)
_SILERO_CONTEXT_SAMPLES = {16000: 64, 8000: 32}


class SileroVAD:
    """Per-recording-session VAD instance. Holds the model state across chunks."""

    _shared_session: Optional["onnxruntime.InferenceSession"] = None
    _shared_lock = threading.Lock()

    def __init__(self, sample_rate: int = 16000):
        if sample_rate not in (8000, 16000):
            raise ValueError(f"silero-vad supports 8kHz or 16kHz, got {sample_rate}")
        self.sample_rate = sample_rate
        self.chunk_samples = 512 if sample_rate == 16000 else 256
        self.context_samples = _SILERO_CONTEXT_SAMPLES[sample_rate]
        self.state = np.zeros(_SILERO_STATE_SHAPE, dtype=np.float32)
        # Leading-context buffer prepended to each new chunk. Starts as zeros;
        # after each score_chunk we save the last context_samples of the chunk.
        self.context = np.zeros(self.context_samples, dtype=np.int16)
        self.sr_tensor = np.array(sample_rate, dtype=np.int64)
        self.session = self._get_shared_session()

    @classmethod
    def _get_shared_session(cls):
        """One ONNX session per process. Model is small (~2.3MB) but inference
        objects aren't free — share across all recording sessions."""
        if cls._shared_session is not None:
            return cls._shared_session
        with cls._shared_lock:
            if cls._shared_session is not None:
                return cls._shared_session
            model_path = _ensure_model_downloaded()
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            cls._shared_session = ort.InferenceSession(
                str(model_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            logger.info(f"[SILERO] Loaded model from {model_path}")
            return cls._shared_session

    def reset(self):
        """Clear hidden state and context — call at the start of each recording."""
        self.state.fill(0.0)
        self.context = np.zeros(self.context_samples, dtype=np.int16)

    def score_chunk(self, audio_int16: np.ndarray) -> float:
        """Score one chunk of audio for speech probability (0.0..1.0).

        audio_int16: 1-D np.int16 array of exactly self.chunk_samples samples.
        Internally prepends the previous chunk's trailing context (64 samples
        at 16kHz) for waveform continuity, then advances state and context.
        """
        if audio_int16.dtype != np.int16:
            audio_int16 = audio_int16.astype(np.int16)
        if len(audio_int16) != self.chunk_samples:
            if len(audio_int16) < self.chunk_samples:
                audio_int16 = np.pad(audio_int16, (0, self.chunk_samples - len(audio_int16)))
            else:
                audio_int16 = audio_int16[:self.chunk_samples]

        # Concatenate stored context with new chunk
        with_context = np.concatenate([self.context, audio_int16])  # 576 samples @ 16k

        audio_f32 = (with_context.astype(np.float32) / 32768.0).reshape(1, -1)
        outputs = self.session.run(
            None,
            {
                "input": audio_f32,
                "state": self.state,
                "sr": self.sr_tensor,
            },
        )
        speech_prob = float(outputs[0].squeeze())
        self.state = outputs[1]
        # Save the last context_samples of THIS chunk for the next call
        self.context = audio_int16[-self.context_samples:].copy()
        return speech_prob


def _ensure_model_downloaded() -> Path:
    """Download silero_vad.onnx to user/models/ on first use. Returns path."""
    if MODEL_CACHE_PATH.exists() and MODEL_CACHE_PATH.stat().st_size > 1_000_000:
        return MODEL_CACHE_PATH

    MODEL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"[SILERO] Downloading {SILERO_VAD_URL} → {MODEL_CACHE_PATH}")
    # Atomic download — write to .tmp then rename so a Ctrl-C mid-download
    # doesn't leave a half-file that the next run silently uses.
    tmp_path = MODEL_CACHE_PATH.with_suffix(".onnx.tmp")
    try:
        urllib.request.urlretrieve(SILERO_VAD_URL, str(tmp_path))
        if tmp_path.stat().st_size < 1_000_000:
            raise RuntimeError(f"Downloaded file too small ({tmp_path.stat().st_size} bytes) — likely a redirect/error page")
        os.replace(tmp_path, MODEL_CACHE_PATH)
        logger.info(f"[SILERO] Model cached at {MODEL_CACHE_PATH} ({MODEL_CACHE_PATH.stat().st_size:,} bytes)")
        return MODEL_CACHE_PATH
    except Exception as e:
        # Clean up partial download
        if tmp_path.exists():
            try: tmp_path.unlink()
            except Exception: pass
        raise RuntimeError(f"silero-vad model download failed: {e}") from e
