"""Frame classifiers for VADProcessor: "is this frame speech?"

VADProcessor owns the state machine (energy gate, adaptive noise floor,
speaker focus, onset debounce, pre-roll, pause-hint/EOU). This module owns
only the per-frame verdict it consults, behind one seam:

    class FrameClassifier(Protocol):
        def is_speech(self, frame_bytes: bytes, sample_rate: int) -> bool: ...

Two implementations: webrtcvad's formant classifier, and Silero VAD (ONNX) —
a small RNN trained on real speech across many languages and noise
conditions, which tells a fan or a TV from a human voice far better than
webrtcvad's level-3 heuristic. A call must never die because a model file is
missing, so Silero falls back to webrtcvad whenever it cannot load.

Where the Silero model comes from, in order: an explicit ``model_path``, then
``<project>/models/silero_vad.onnx``, then a one-time download of
onnx-community/silero-vad (a community export of snakers4/silero-vad v5)
into that same path.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional, Protocol

import numpy as np

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
DEFAULT_MODEL_PATH = MODELS_DIR / "silero_vad.onnx"
MODEL_URL = "https://huggingface.co/onnx-community/silero-vad/resolve/main/onnx/model.onnx"

# Silero works on fixed hops regardless of the caller's frame size: 512
# samples at 16 kHz is the window this export expects per call. It takes plain
# [1, 512] float32 audio plus a [2, 1, 128] recurrent state threaded call to
# call — no manual context-window concatenation (some older releases needed
# one; this graph does not, checked by feeding it directly).
_SILERO_HOP_SAMPLES = 512
_SILERO_STATE_SHAPE = (2, 1, 128)


class FrameClassifier(Protocol):
    def is_speech(self, frame_bytes: bytes, sample_rate: int) -> bool: ...

    def reset(self) -> None: ...


class WebRTCClassifier:
    """webrtcvad's formant classifier, behind FrameClassifier."""

    def __init__(self, aggressiveness: int = 3) -> None:
        import webrtcvad  # webrtcvad or webrtcvad-wheels

        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame_bytes: bytes, sample_rate: int) -> bool:
        return self._vad.is_speech(frame_bytes, sample_rate)

    def reset(self) -> None:
        pass  # stateless


class EnergyClassifier:
    """Last resort when neither Silero nor webrtcvad is available: every
    frame is "speech" and VADProcessor's energy gate alone decides."""

    def is_speech(self, frame_bytes: bytes, sample_rate: int) -> bool:
        return True

    def reset(self) -> None:
        pass


class SileroClassifier:
    """Buffers 20 ms / 320-sample frames into Silero's 512-sample hops.

    LCM(320, 512) = 2560 samples = 8 frames = 5 inferences per cycle, so most
    frames land between inferences and hold the last verdict — worst-case
    staleness under 2 frames (~40 ms), well inside the 350 ms pre-roll that
    already protects onsets from clipping.
    """

    def __init__(self, session, threshold: float = 0.5, release: float = 0.35) -> None:
        self._session = session
        self._threshold = threshold
        self._release = release
        self._pending = np.empty(0, dtype=np.float32)
        self._state = np.zeros(_SILERO_STATE_SHAPE, dtype=np.float32)
        self._voiced = False

    def is_speech(self, frame_bytes: bytes, sample_rate: int) -> bool:
        chunk = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        self._pending = np.concatenate([self._pending, chunk])
        while len(self._pending) >= _SILERO_HOP_SAMPLES:
            window, self._pending = self._pending[:_SILERO_HOP_SAMPLES], self._pending[_SILERO_HOP_SAMPLES:]
            try:
                outputs = self._session.run(["output", "stateN"], {
                    "input": window.reshape(1, -1),
                    "state": self._state,
                    "sr": np.array(sample_rate, dtype=np.int64),
                })
            except Exception:
                logger.exception("[VAD] Silero inference failed — treating frame as non-speech")
                return False
            prob, self._state = float(outputs[0][0, 0]), outputs[1]
            # Hysteresis: easier to stay voiced than to become voiced.
            self._voiced = prob >= (self._release if self._voiced else self._threshold)
        return self._voiced

    def reset(self) -> None:
        """Full stream restart. Not called by VADProcessor.reset(): the
        recurrent state deliberately persists across utterances in one call,
        same as the adaptive noise floor."""
        self._pending = np.empty(0, dtype=np.float32)
        self._state = np.zeros(_SILERO_STATE_SHAPE, dtype=np.float32)
        self._voiced = False


_sessions: dict = {}
_failed: set = set()
_lock = threading.Lock()


def _download(path: Path) -> None:
    import httpx

    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"[VAD] Downloading the Silero VAD model to {path}…")
    tmp = path.with_suffix(".download")
    with httpx.stream("GET", MODEL_URL, follow_redirects=True, timeout=60.0) as response:
        response.raise_for_status()
        with open(tmp, "wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    os.replace(tmp, path)


def get_silero_session(model_path: str = ""):
    """Load and cache one ONNX session per model file. onnxruntime sessions
    are safe for concurrent run() calls with per-call state passed in, so
    every classifier shares it. None when it cannot be loaded."""
    path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
    key = str(path)
    if key in _sessions or key in _failed:
        return _sessions.get(key)
    with _lock:
        if key in _sessions or key in _failed:
            return _sessions.get(key)
        try:
            import onnxruntime as ort

            if not path.exists():
                if model_path:
                    raise FileNotFoundError(model_path)
                _download(path)
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            _sessions[key] = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
            logger.info(f"[VAD] Silero VAD loaded from {path}")
        except Exception as exc:
            _failed.add(key)
            logger.error(f"[VAD] Could not load Silero VAD — falling back to webrtcvad: {exc!r}")
    return _sessions.get(key)


def create_classifier(
    engine: str = "silero",
    *,
    aggressiveness: int = 3,
    threshold: float = 0.5,
    release: float = 0.35,
    model_path: str = "",
) -> FrameClassifier:
    """Build the frame classifier, falling back silero → webrtc → energy."""
    if engine == "silero":
        session = get_silero_session(model_path)
        if session is not None:
            return SileroClassifier(session, threshold=threshold, release=release)
        logger.warning("[VAD] Silero unavailable — using webrtcvad")
    try:
        return WebRTCClassifier(aggressiveness)
    except ImportError:
        logger.warning("[VAD] webrtcvad not installed — energy gate only")
        return EnergyClassifier()


def describe_engine(engine: str = "silero", model_path: str = "") -> str:
    """Label for the active classifier. Never triggers a load itself."""
    if engine == "silero":
        key = str(Path(model_path) if model_path else DEFAULT_MODEL_PATH)
        if key in _sessions:
            return "silero-onnx"
        if key in _failed:
            return "webrtcvad [silero load failed]"
        return "silero-onnx (not loaded yet)"
    return "webrtcvad"
