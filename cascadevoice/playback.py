"""Playout clock — what the customer is currently hearing.

A WebSocket hands a synthesized sentence to the client in milliseconds; the
client then plays it for several seconds. The server is therefore done *sending*
long before the user is done *listening*, and anything that keys off "am I
still sending?" — barge-in, above all — is asking the wrong question.

This tracks the far end of the audio already committed to the wire, so the
session can answer the right ones: is the agent audible right now, and on a
barge-in, which sentences had the user actually started hearing? Only those
go into the conversation history — otherwise the model believes it said
things the user never heard, and answers questions it never asked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List


@dataclass(frozen=True)
class SpokenUnit:
    """One synthesized sentence and the window it occupies in the playout."""

    text: str
    starts_at: float
    ends_at: float

    def had_started_by(self, moment: float) -> bool:
        return moment >= self.starts_at


@dataclass
class PlaybackClock:
    """Tracks how far ahead of real time the sent audio reaches.

    ``tail_padding`` covers the gap between the server writing bytes and the
    client actually rendering them — network hop, decode, scheduling — so the
    barge-in window does not close a moment early.
    """

    tail_padding: float = 0.25
    now: Callable[[], float] = time.monotonic
    _audible_until: float = 0.0
    _units: List[SpokenUnit] = field(default_factory=list)

    def enqueue(self, text: str, duration: float) -> SpokenUnit:
        """Record audio just handed to the transport, and return its window."""
        now = self.now()
        if self._units and now >= self._audible_until + self.tail_padding:
            # The previous run has finished playing: this is a new run of speech. Without this,
            # speaking_for counted from the call's first sentence (so the barge-in grace window
            # had always passed) and a barge-in's "heard" text was everything since the call
            # began (or the last interruption), all written into the history as one turn.
            self._units.clear()
        starts_at = max(now, self._audible_until)
        ends_at = starts_at + duration
        self._audible_until = ends_at
        unit = SpokenUnit(text=text, starts_at=starts_at, ends_at=ends_at)
        self._units.append(unit)
        return unit

    @property
    def is_speaking(self) -> bool:
        return self.now() < self._audible_until + self.tail_padding

    @property
    def remaining(self) -> float:
        """Seconds of audio still to play, ignoring the padding."""
        return max(0.0, self._audible_until - self.now())

    @property
    def speaking_for(self) -> float:
        """How long the current run of speech has been audible."""
        if not self._units:
            return 0.0
        return max(0.0, self.now() - self._units[0].starts_at)

    def spoken_text(self, until: float | None = None) -> str:
        """What the user actually heard, up to `until` (default: now).

        Units whose playback had begun are counted as heard — a half-finished
        sentence still reached the customer. Units still queued behind the
        interruption did not, and must not enter the conversation history.
        """
        moment = self.now() if until is None else until
        return " ".join(u.text for u in self._units if u.text and u.had_started_by(moment)).strip()

    def stop(self) -> str:
        """Playback was cut off. Returns what had been heard by that point."""
        heard = self.spoken_text()
        self._audible_until = 0.0
        self._units.clear()
        return heard

    def reset(self) -> None:
        self._audible_until = 0.0
        self._units.clear()
