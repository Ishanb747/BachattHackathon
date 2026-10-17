"""Where the agent's output goes: one browser WebSocket.

:class:`Transport` is the seam — the session calls only these methods — so a
host project can put the same pipeline on another sink (a phone carrier, a
test double) without touching the session.
"""

from __future__ import annotations

import logging
from typing import Any

from cascadevoice import defaults as d
from cascadevoice.events import AudioBeginEvent, AudioEndEvent, ControlEvent, Event

logger = logging.getLogger(__name__)


class Transport:
    """Sink for one call's audio and events."""

    #: Whether this peer plays audio at all (False: synthesis is skipped).
    wants_audio: bool = True
    #: Whether hanging up needs the server to close the connection. A browser
    #: disconnects itself once playback drains.
    hangup_requires_close: bool = False

    async def send_event(self, event: Event) -> None:
        raise NotImplementedError

    async def begin_audio_stream(self, sample_rate: int) -> None:
        raise NotImplementedError

    async def send_audio_chunk(self, pcm16: bytes) -> None:
        raise NotImplementedError

    async def end_audio_stream(self) -> None:
        raise NotImplementedError

    async def stop_playback(self) -> None:
        """Cut off audio already handed to the peer (barge-in)."""
        raise NotImplementedError

    @property
    def is_connected(self) -> bool:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class BrowserTransport(Transport):
    """JSON text frames for events; binary frames are raw PCM-16 chunks,
    bracketed by audio_begin (carrying the rate) and audio_end, which the
    client schedules gaplessly as they arrive. Takes any websocket-like
    object with ``send_text`` / ``send_bytes`` (Starlette's, or a fake)."""

    def __init__(self, websocket: Any) -> None:
        self._ws = websocket

    @property
    def is_connected(self) -> bool:
        state = getattr(self._ws, "client_state", None)
        return state is None or getattr(state, "name", "") == "CONNECTED"

    async def send_event(self, event: Event) -> None:
        if not self.is_connected:
            return
        try:
            await self._ws.send_text(event.to_json())
        except Exception as exc:
            logger.debug(f"[Transport] Dropped event, socket closing: {exc!r}")

    async def begin_audio_stream(self, sample_rate: int) -> None:
        await self.send_event(AudioBeginEvent(sample_rate=sample_rate))

    async def send_audio_chunk(self, pcm16: bytes) -> None:
        if not pcm16 or not self.is_connected:
            return
        try:
            await self._ws.send_bytes(pcm16)
        except Exception as exc:
            logger.debug(f"[Transport] Dropped audio chunk, socket closing: {exc!r}")

    async def end_audio_stream(self) -> None:
        # Always sent, even after a barge-in mid-stream, so the client never
        # misreads what follows.
        await self.send_event(AudioEndEvent())

    async def stop_playback(self) -> None:
        await self.send_event(ControlEvent(action="stop_playback", fade_ms=d.BARGE_IN_FADE_MS))
