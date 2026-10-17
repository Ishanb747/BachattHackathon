"""Server → client events. The browser client renders these directly, so the
wire format is a contract: add fields, never rename or drop them. Optional
fields are omitted from the JSON rather than sent as null.

Binary frames are raw PCM-16 mono agent audio, each run bracketed by
``audio_begin`` (carrying the sample rate) and ``audio_end``.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

Status = Literal["idle", "listening", "transcribing", "thinking", "speaking"]


class Event(BaseModel):
    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True)


class ConnectedEvent(Event):
    type: Literal["connected"] = "connected"
    call_id: str
    llm: str
    voice: str
    vad: str
    language: str
    protocol: str = "raw-pcm-16k-20ms"
    frame_size_bytes: int = 640


class StatusEvent(Event):
    type: Literal["status"] = "status"
    status: Status


class TranscriptEvent(Event):
    type: Literal["transcript"] = "transcript"
    role: Literal["user", "agent"]
    text: str
    index: Optional[int] = None      # agent: sentence number within the reply
    language: Optional[str] = None


class MetricsEvent(Event):
    """One turn's stage timings, all in ms from the end of the user's utterance
    unless named otherwise. Sent when the first audio of the reply goes out."""

    type: Literal["metrics"] = "metrics"
    endpoint_wait_ms: float = 0.0      # silence the user had already sat through at EOU
    stt_ms: float = 0.0                # EOU → transcript
    llm_first_token_ms: float = 0.0    # transcript → first model token
    llm_first_sentence_ms: float = 0.0  # transcript → first complete sentence
    tts_first_audio_ms: float = 0.0    # first sentence → first TTS bytes
    total_ms: float = 0.0              # EOU → first audio out
    true_e2e_ms: float = 0.0           # last words → first audio out (endpoint_wait + total)
    stt_source: str = ""               # realtime | partial | batch | typed
    cache_hit: bool = False
    hooked: bool = False               # the reply came from the hook, not the model


class TurnCompleteEvent(Event):
    type: Literal["turn_complete"] = "turn_complete"
    full_text: str


class ControlEvent(Event):
    type: Literal["control"] = "control"
    action: Literal["stop_playback", "hangup"]
    reason: Optional[str] = None
    # stop_playback only: ramp the client's gain to zero over this many ms.
    fade_ms: Optional[int] = None


class AudioBeginEvent(Event):
    type: Literal["audio_begin"] = "audio_begin"
    sample_rate: int


class AudioEndEvent(Event):
    type: Literal["audio_end"] = "audio_end"


class ErrorEvent(Event):
    type: Literal["error"] = "error"
    message: str
