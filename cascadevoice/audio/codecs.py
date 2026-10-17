"""PCM helpers. The browser sends 16 kHz mono PCM-16; that is the VAD's and
the ear's contract too, so no resampling happens on the way in. TTS audio
leaves at the rate it was requested at."""

from __future__ import annotations

import struct

try:  # audioop was removed from the stdlib in Python 3.13.
    import audioop
except ImportError:  # pragma: no cover - depends on interpreter version
    import audioop_lts as audioop

SAMPLE_RATE = 16000


def pcm16_to_wav(pcm16_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Prepend a 44-byte RIFF header to raw mono PCM-16 samples."""
    data_len = len(pcm16_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_len, b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", data_len,
    )
    return header + pcm16_bytes


def pcm_duration_s(pcm16: bytes, sample_rate: int) -> float:
    return len(pcm16) / 2 / max(1, sample_rate)


def rms_energy(pcm16_bytes: bytes) -> float:
    """Root-mean-square amplitude of a PCM-16 buffer, on a 0..32767 scale.

    Runs on every 20 ms frame, so it uses audioop's C implementation: the
    Python loop costs ~17 µs per frame against 0.5 µs here, and event-loop
    time spent here is latency added to every call in flight.
    """
    usable = len(pcm16_bytes) - (len(pcm16_bytes) % 2)
    if usable == 0:
        return 0.0
    return float(audioop.rms(pcm16_bytes[:usable], 2))
