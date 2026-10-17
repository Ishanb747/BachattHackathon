"""Offline stand-ins for every vendor and the browser."""

from __future__ import annotations

import asyncio
import time
from typing import List, Optional

from cascadevoice.audio.vad import VADEvent, VADResult
from cascadevoice.ear.scribe import Transcription
from cascadevoice.llm import TextDelta, ToolCall
from cascadevoice.transport import Transport

RATE = 16000


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class FakeLLM:
    """Plays scripted rounds. Each round is a list of str (text deltas),
    ToolCall, or float (sleep that long)."""

    name = "fake-llm"

    def __init__(self, *rounds) -> None:
        self.rounds = list(rounds)
        self.calls: List[List[dict]] = []
        self.finished_at = 0.0

    async def stream(self, messages, *, tools=None):
        self.calls.append([dict(m) for m in messages])
        script = self.rounds.pop(0) if self.rounds else ["Okay."]
        for item in script:
            if isinstance(item, (int, float)):
                await asyncio.sleep(item)
            elif isinstance(item, ToolCall):
                yield item
            else:
                yield TextDelta(item)
        self.finished_at = time.perf_counter()


class FakeTTS:
    """Each sentence streams `chunks` chunks of `chunk_s` seconds of audio,
    the first after `first_delay` seconds."""

    voice_id = "fake-voice"
    sample_rate = RATE

    def __init__(self, *, first_delay: float = 0.0, chunks: int = 2, chunk_s: float = 0.05,
                 delays: Optional[dict] = None, fail_open: bool = False) -> None:
        self.first_delay = first_delay
        self.chunks = chunks
        self.chunk_s = chunk_s
        self.delays = delays or {}
        self.fail_open = fail_open
        self.opened: List[str] = []
        self.synthesized: List[str] = []

    async def open(self, text, *, language):
        if self.fail_open:
            raise RuntimeError("stream refused")
        self.opened.append(text)
        delay = self.delays.get(text, self.first_delay)

        async def gen():
            await asyncio.sleep(delay)
            for _ in range(self.chunks):
                yield b"\x01\x00" * int(RATE * self.chunk_s)
        return RATE, gen()

    async def synthesize(self, text, *, language):
        self.synthesized.append(text)
        return b"\x01\x00" * int(RATE * self.chunk_s)


class FakeEar:
    def __init__(self, text: str = "", *, partial: str = "", delay: float = 0.0, fail: bool = False) -> None:
        self.text, self.partial_text, self.delay = text, partial, delay
        self.failed = None
        self.fail = fail
        self.fed = 0
        self.closed = False

    def feed(self, pcm: bytes) -> None:
        self.fed += len(pcm)

    async def open(self) -> bool:
        return True

    async def commit(self):
        await asyncio.sleep(self.delay)
        if self.fail:
            return None
        return Transcription(text=self.text, language="en-IN", latency_ms=self.delay * 1000, model="fake-ear")

    async def close(self) -> None:
        self.closed = True


class FakeBatch:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.calls = 0

    async def transcribe(self, pcm, *, language):
        self.calls += 1
        if not self.text:
            return None
        return Transcription(text=self.text, language=language, latency_ms=500, model="fake-batch")


class RecordingTransport(Transport):
    def __init__(self) -> None:
        self.events: List[dict] = []
        self.chunks: List[bytes] = []
        self.first_chunk_at = 0.0
        self.stops = 0

    @property
    def is_connected(self) -> bool:
        return True

    async def send_event(self, event) -> None:
        self.events.append(event.model_dump(exclude_none=True))

    async def begin_audio_stream(self, sample_rate: int) -> None:
        self.events.append({"type": "audio_begin", "sample_rate": sample_rate})

    async def send_audio_chunk(self, pcm16: bytes) -> None:
        if not self.first_chunk_at:
            self.first_chunk_at = time.perf_counter()
        self.chunks.append(pcm16)

    async def end_audio_stream(self) -> None:
        self.events.append({"type": "audio_end"})

    async def stop_playback(self) -> None:
        self.stops += 1

    def of_type(self, kind: str) -> List[dict]:
        return [e for e in self.events if e["type"] == kind]

    def agent_lines(self) -> List[str]:
        return [e["text"] for e in self.of_type("transcript") if e["role"] == "agent"]


class StubVAD:
    """What the session touches when a test drives _handle_vad directly."""

    def __init__(self) -> None:
        self.in_speech = False
        self.speech_so_far = b""
        self.silence_ms_so_far = 110.0
        self.agent_speaking = False
        self.extended: Optional[int] = None
        self.committed = False

    def set_agent_speaking(self, speaking: bool) -> None:
        self.agent_speaking = speaking

    def extend_current_eou(self, frames: int) -> None:
        self.extended = frames

    def commit(self):
        self.committed = True
        self.in_speech = False
        return b"\x00\x10" * 3200

    def process_frame(self, frame: bytes) -> VADResult:
        return vad(VADEvent.SILENCE)


def vad(event: VADEvent, speech_frames: int = 10, pcm: bytes = b"\x00\x10" * 3200) -> VADResult:
    return VADResult(event=event, is_voiced=event is VADEvent.SPEECH, rms_energy=0.0, silence_frames=11,
                     speech_frames=speech_frames,
                     speech_pcm=pcm if event in (VADEvent.END_OF_UTTERANCE, VADEvent.PAUSE_HINT) else None)


async def until(predicate, timeout: float = 2.0) -> None:
    deadline = time.perf_counter() + timeout
    while not predicate():
        if time.perf_counter() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)
