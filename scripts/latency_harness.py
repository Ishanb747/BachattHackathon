"""Offline latency harness: what the pipeline itself adds, with stub vendors.

Every vendor is a stub with a fixed, realistic delay (Scribe commit, LLM first
token and per-token, TTS first chunk), so whatever latency is left above those
delays is ours. Each simulated call is a real VoiceSession fed 16 kHz PCM in
20 ms frames at real time, so the VAD, endpointing and the turn pipeline all
run as on a live call. Silero runs on every frame (its CPU cost is real) but
the energy gate decides, so every synthetic utterance is a turn — Silero is
rightly unsure about a synthetic voice. No network, no keys.

    .venv/bin/python scripts/latency_harness.py --calls 1 10 50 --turns 3

Reports per level: EOU → first audio out, the same minus the stub delays (our
overhead) p50/p99, and event-loop lag p50/p99/max.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cascadevoice.audio.vad import VADProcessor           # noqa: E402
from cascadevoice.audio.vad_engines import create_classifier  # noqa: E402
from cascadevoice.cache import AudioCache                # noqa: E402
from cascadevoice.ear.scribe import Transcription        # noqa: E402
from cascadevoice.llm import TextDelta                   # noqa: E402
from cascadevoice.session import VoiceSession            # noqa: E402
from cascadevoice.transport import Transport             # noqa: E402

STT_COMMIT_S = 0.125     # Scribe realtime commit
LLM_TTFT_S = 0.35        # first token
LLM_TOKEN_S = 0.01       # per token after it
TTS_FIRST_S = 0.12       # first audio chunk of a sentence
STUB_FLOOR_MS = (STT_COMMIT_S + LLM_TTFT_S + TTS_FIRST_S) * 1000
REPLY = "Thank you, I have noted that down. Could you tell me which day suits you best?"
SR = 16000


def speechlike(seconds: float) -> bytes:
    t = np.arange(int(SR * seconds)) / SR
    f0 = 140 + 20 * np.sin(2 * np.pi * 1.5 * t)
    phase = 2 * np.pi * np.cumsum(f0) / SR
    voiced = sum(np.sin(k * phase) / k for k in range(1, 15))
    return (voiced * (0.7 + 0.3 * np.sin(2 * np.pi * 4 * t)) * 3000).astype(np.int16).tobytes()


class SileroCostEnergyVerdict:
    """Pays Silero's per-frame inference, answers like the energy gate."""

    def __init__(self) -> None:
        self.silero = create_classifier("silero")

    def is_speech(self, frame, rate):
        self.silero.is_speech(frame, rate)
        return True

    def reset(self):
        self.silero.reset()


class StubLLM:
    name = "stub-llm"

    async def stream(self, messages, *, tools=None):
        await asyncio.sleep(LLM_TTFT_S)
        for word in REPLY.split(" "):
            yield TextDelta(word + " ")
            await asyncio.sleep(LLM_TOKEN_S)


class StubTTS:
    voice_id = "stub"
    sample_rate = 22050

    async def open(self, text, *, language):
        async def gen():
            await asyncio.sleep(TTS_FIRST_S)
            for _ in range(3):
                yield b"\x00\x00" * int(self.sample_rate * 0.2)
                await asyncio.sleep(0.05)
        return self.sample_rate, gen()

    async def synthesize(self, text, *, language):
        return None


class StubEar:
    partial_text = ""
    failed = None

    def feed(self, pcm):
        pass

    async def open(self):
        return True

    async def commit(self):
        await asyncio.sleep(STT_COMMIT_S)
        return Transcription(text="I would like to book a table for Friday", language="en-IN",
                             latency_ms=STT_COMMIT_S * 1000, model="stub")

    async def close(self):
        pass


class StubBatch:
    async def transcribe(self, pcm, *, language):
        return None


class Sink(Transport):
    def __init__(self, results: list) -> None:
        self.results = results

    @property
    def is_connected(self):
        return True

    async def send_event(self, event):
        if event.type == "metrics":
            self.results.append(event.total_ms)

    async def begin_audio_stream(self, rate):
        pass

    async def send_audio_chunk(self, pcm):
        pass

    async def end_audio_stream(self):
        pass

    async def stop_playback(self):
        pass


async def one_call(turns: int, results: list) -> None:
    session = VoiceSession(Sink(results), llm=StubLLM(), tts=StubTTS(), ear_factory=lambda lang: StubEar(),
                           batch_stt=StubBatch(), vad=VADProcessor.from_defaults(classifier=SileroCostEnergyVerdict()), greeting=None, cache=AudioCache())
    await session.start()
    utterance = speechlike(1.2)
    silence = b"\x00\x00" * int(SR * 4.0)   # long enough for the reply to finish playing
    started = time.perf_counter()
    sent = 0
    for _ in range(turns):
        for audio in (utterance, silence):
            for i in range(0, len(audio), 640):
                await session.feed_pcm(audio[i:i + 640])
                sent += 1
                # Real time: frame n is due at n × 20 ms after the start.
                delay = started + sent * 0.02 - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
    await session.close()


async def level(calls: int, turns: int) -> dict:
    results: list = []
    lags: list = []
    stop = asyncio.Event()

    async def lag_probe():
        while not stop.is_set():
            t0 = time.perf_counter()
            await asyncio.sleep(0.01)
            lags.append((time.perf_counter() - t0 - 0.01) * 1000)

    probe = asyncio.create_task(lag_probe())
    await asyncio.gather(*(one_call(turns, results) for _ in range(calls)))
    stop.set()
    await probe

    def pct(values, p):
        values = sorted(values)
        return values[min(len(values) - 1, int(len(values) * p))] if values else float("nan")

    overhead = [r - STUB_FLOOR_MS for r in results]
    return {"calls": calls, "turns": len(results), "e2e_p50": pct(results, 0.5), "overhead_p50": pct(overhead, 0.5),
            "overhead_p99": pct(overhead, 0.99), "lag_p50": statistics.median(lags) if lags else 0,
            "lag_p99": pct(lags, 0.99), "lag_max": max(lags) if lags else 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls", type=int, nargs="+", default=[1, 10])
    parser.add_argument("--turns", type=int, default=3)
    args = parser.parse_args()
    print(f"stub floor (STT commit + LLM first token + TTS first chunk) = {STUB_FLOOR_MS:.0f} ms")
    print(f"{'calls':>5} {'turns':>5} {'EOU→audio p50':>14} {'ours p50':>9} {'ours p99':>9} "
          f"{'loop lag p50':>12} {'p99':>6} {'max':>6}")
    for calls in args.calls:
        r = asyncio.run(level(calls, args.turns))
        print(f"{r['calls']:>5} {r['turns']:>5} {r['e2e_p50']:>12.0f}ms {r['overhead_p50']:>7.0f}ms "
              f"{r['overhead_p99']:>7.0f}ms {r['lag_p50']:>10.1f}ms {r['lag_p99']:>5.1f} {r['lag_max']:>5.1f}")


if __name__ == "__main__":
    main()
