"""ElevenLabs Scribe v2 Realtime — the pipeline's ear.

A batch STT can only start once the user has stopped, so its whole round trip
lands in the gap before the agent speaks (~0.5-0.9 s). This stream is opened
at speech onset, fed every 20 ms frame while the user talks, and *committed*
at end of utterance; by then the vendor has heard everything, so the commit
returns in ~125 ms (measured against 512 ms batch on the same audio).

One stream per utterance. Anything that goes wrong (connect failure, vendor
error, commit timeout) surfaces as ``commit()`` returning None, and the
session falls back to batch Scribe on the buffered utterance — the stream is
an accelerator, never a new single point of failure.

Protocol (/v1/speech-to-text/realtime): the client sends
``{"message_type": "input_audio_chunk", "audio_base_64", "commit", "sample_rate"}``;
the server sends ``session_started``, ``partial_transcript``,
``committed_transcript`` (``text``, optionally ``language_code``) and a family
of ``*_error`` types carrying ``error``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from cascadevoice import defaults as d
from cascadevoice import elevenlabs

logger = logging.getLogger(__name__)

REALTIME_MODEL_ID = "scribe_v2_realtime"
_COMMIT = object()   # sentinel on the send queue: flush what's there, then commit
_SILENCE_20MS = b"\x00" * 640   # what the commit rides on when no frame is pending
MAX_PARTIALS = 40

@dataclass(frozen=True)
class Transcription:
    """One recognised utterance."""

    text: str
    language: str
    latency_ms: float
    model: str
    detected: str = ""   # the vendor's own code ("hin"), never replaced by the fallback
    partials: list = field(default_factory=list)   # [{"ms", "text"}] interim hypotheses


def _ssl_context(url: str):
    """TLS roots for the socket. httpx verifies against certifi's bundle;
    `websockets` uses the interpreter's default context, which on python.org
    macOS builds has no CA file at all and fails every wss:// handshake with
    CERTIFICATE_VERIFY_FAILED. So hand it certifi's bundle explicitly."""
    if not url.startswith("wss://"):
        return None
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


# Socket closes handed off the commit path. asyncio holds tasks weakly, so a
# close with no other reference could be collected mid-handshake.
_closing: set = set()


def _close_done(task: asyncio.Task) -> None:
    _closing.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning(f"[Scribe] background close failed: {task.exception()!r}")


class ScribeRealtimeStream:
    """One utterance's worth of streaming transcription.

    Surface the session relies on (any replacement ear needs the same):
    ``partial_text``, ``feed(pcm)``, ``await open()``, ``await commit()``,
    ``await close()``.
    """

    name = "elevenlabs-scribe-realtime"

    def __init__(self, api_key: str, *, language: str = d.LANGUAGE, sample_rate: int = 16000) -> None:
        self._api_key = api_key
        self._fallback_language = language
        self._sample_rate = sample_rate
        self._queue: asyncio.Queue = asyncio.Queue()
        self._ws = None
        self._sender: Optional[asyncio.Task] = None
        self._receiver: Optional[asyncio.Task] = None
        self._opened: asyncio.Future = asyncio.get_running_loop().create_future()
        self._committed: Optional[asyncio.Future] = None
        self._partial = ""
        self._partials: list = []
        self._t_open = time.perf_counter()
        self._failed: Optional[str] = None
        self._closed = False

    @property
    def partial_text(self) -> str:
        """The vendor's latest interim transcript — what the pause-time
        "is the sentence finished?" judgement reads, for free."""
        return self._partial

    @property
    def failed(self) -> Optional[str]:
        return self._failed

    async def open(self) -> bool:
        """Connect and wait for ``session_started``. False on any failure —
        the caller keeps feeding regardless; frames queue until connected."""
        if not self._api_key:
            self._fail("no ELEVENLABS_API_KEY")
            return False
        try:
            from websockets.asyncio.client import connect

            await elevenlabs.ensure_region(self._api_key)
            url = (
                f"{elevenlabs.ws_base(self._api_key)}/v1/speech-to-text/realtime"
                f"?model_id={REALTIME_MODEL_ID}&audio_format=pcm_{self._sample_rate}"
                "&commit_strategy=manual&include_language_detection=true"
            )
            self._ws = await asyncio.wait_for(
                connect(url, additional_headers={"xi-api-key": self._api_key}, max_size=None, ssl=_ssl_context(url)),
                timeout=d.SCRIBE_CONNECT_TIMEOUT_S,
            )
            self._receiver = asyncio.create_task(self._receive(), name="scribe_recv")
            await asyncio.wait_for(self._opened, timeout=d.SCRIBE_CONNECT_TIMEOUT_S)
            self._sender = asyncio.create_task(self._send_loop(), name="scribe_send")
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(f"connect failed: {exc!r}")
            await self.close()
            return False

    def feed(self, pcm16: bytes) -> None:
        """Queue raw PCM-16 mono frames. Safe before ``open()`` completes."""
        if self._closed or self._failed or not pcm16:
            return
        self._queue.put_nowait(pcm16)

    async def commit(self) -> Transcription | None:
        """Finalize the utterance and return its transcript, or None when the
        stream cannot deliver one."""
        if self._failed or self._closed:
            self.close_soon()
            return None
        if not self._opened.done():
            # Still connecting at end of utterance: the round trip would now
            # cost as much as any fallback.
            self._fail("commit before the session started")
            self.close_soon()
            return None
        self._committed = asyncio.get_running_loop().create_future()
        started = time.perf_counter()
        self._queue.put_nowait(_COMMIT)
        try:
            text, language_code = await asyncio.wait_for(self._committed, timeout=d.SCRIBE_COMMIT_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._fail("commit timed out")
            self.close_soon()
            return None
        except asyncio.CancelledError:
            self.close_soon()
            raise
        # The transcript is in hand: the close handshake is one more round
        # trip nobody is waiting for.
        self.close_soon()
        if text is None:
            return None
        latency_ms = (time.perf_counter() - started) * 1000
        language = elevenlabs.to_bcp47(language_code, self._fallback_language)
        logger.info(f"[Scribe] commit {latency_ms:.0f} ms ({language}): {text!r}")
        return Transcription(text=text.strip(), language=language, latency_ms=latency_ms, model=self.name,
                             detected=(language_code or "").strip().lower(), partials=list(self._partials))

    async def close(self) -> None:
        if self._shutdown():
            await self._close_socket()

    def close_soon(self) -> Optional[asyncio.Task]:
        """Close without waiting for the socket's close handshake."""
        if not self._shutdown():
            return None
        task = asyncio.get_running_loop().create_task(self._close_socket(), name="scribe_close")
        _closing.add(task)
        task.add_done_callback(_close_done)
        return task

    def _shutdown(self) -> bool:
        """Everything about closing except the socket handshake. False when
        already closed."""
        if self._closed:
            return False
        self._closed = True
        for task in (self._sender, self._receiver):
            if task is not None and not task.done() and task is not asyncio.current_task():
                task.cancel()
        self._resolve()
        return True

    def _resolve(self) -> None:
        """Unblock anyone waiting on open or commit — with nothing."""
        if self._committed is not None and not self._committed.done():
            self._committed.set_result((None, None))
        if not self._opened.done():
            self._opened.set_result(False)

    async def _close_socket(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass

    def _fail(self, reason: str) -> None:
        if self._failed is None:
            self._failed = reason
            logger.warning(f"[Scribe] {reason} — batch Scribe will take this utterance")

    async def _send_loop(self) -> None:
        """Drain queued frames into chunks; a commit rides on the last one."""
        try:
            while True:
                item = await self._queue.get()
                commit = item is _COMMIT
                pcm = b"" if commit else item
                if not commit:
                    # Coalesce whatever else is already waiting so a burst of
                    # frames becomes one message, not twenty.
                    while not self._queue.empty():
                        nxt = self._queue.get_nowait()
                        if nxt is _COMMIT:
                            commit = True
                            break
                        pcm += nxt
                if commit and not pcm:
                    pcm = _SILENCE_20MS
                await self._ws.send(json.dumps({
                    "message_type": "input_audio_chunk",
                    "audio_base_64": base64.b64encode(pcm).decode("ascii"),
                    "commit": commit,
                    "sample_rate": self._sample_rate,
                }))
                if commit:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(f"send failed: {exc!r}")
            self._resolve()

    async def _receive(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                kind = str(message.get("message_type") or "")
                if kind == "session_started":
                    if not self._opened.done():
                        self._opened.set_result(True)
                elif kind == "partial_transcript":
                    self._partial = str(message.get("text") or "")
                    if self._partial and len(self._partials) < MAX_PARTIALS and \
                            (not self._partials or self._partials[-1]["text"] != self._partial):
                        self._partials.append({"ms": round((time.perf_counter() - self._t_open) * 1000),
                                               "text": self._partial[:300]})
                elif kind in ("committed_transcript", "committed_transcript_with_timestamps"):
                    text = str(message.get("text") or "")
                    if self._committed is not None and not self._committed.done():
                        self._committed.set_result((text, message.get("language_code")))
                    else:
                        # A commit we did not ask for (should not happen with
                        # commit_strategy=manual) — keep it as the best partial.
                        self._partial = text
                elif kind == "warning":
                    logger.debug(f"[Scribe] warning: {message.get('warning')!r}")
                elif kind.endswith("error") or kind in (
                    "quota_exceeded", "commit_throttled", "unaccepted_terms", "rate_limited",
                    "queue_overflow", "resource_exhausted", "session_time_limit_exceeded",
                    "chunk_size_exceeded", "insufficient_audio_activity",
                ):
                    self._fail(f"{kind}: {message.get('error')!r}")
                    self._resolve()
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(f"socket closed: {exc!r}")
            self._resolve()


class NoStreamEar:
    """The ear when STT is batch-only: takes the audio, transcribes nothing.
    ``failed`` is set so the session skips the pause judgment and its commit
    is empty, which sends the utterance to the batch transcriber."""

    partial_text = ""
    failed = "batch-only"

    def feed(self, pcm16: bytes) -> None:
        pass

    async def open(self) -> bool:
        return False

    async def commit(self):
        return None

    async def close(self) -> None:
        pass
