"""The voice session — one live call.

One turn:

    PCM frames → VAD → end of utterance
        → Scribe realtime commit (batch Scribe if the stream failed)
        → the host's hook (pass-through by default)
        → gpt-4o stream → sentence chunking
        → ElevenLabs stream per sentence → transport, in order

Sentences are synthesized and sent as soon as the model completes them, so the
user hears the first sentence while the rest is still being generated.

Full duplex: the mic is processed the whole time the agent speaks. An onset
over the agent is not an interruption until it earns one — sustained speech
(``BARGE_IN_HARD_MS``), or an utterance whose transcript reads as a real
answer or interruption rather than a backchannel. On a real one the reply is
cancelled (model stream, synthesis, queued audio, the client's buffer) and the
history records only what the user actually heard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence
from uuid import uuid4

from cascadevoice import defaults as d
from cascadevoice import turns
from cascadevoice.audio.vad import FRAME_DURATION_MS, FRAME_SIZE_BYTES, VADEvent, VADProcessor, VADResult
from cascadevoice.audio.vad_engines import describe_engine
from cascadevoice.cache import AudioCache, audio_cache
from cascadevoice.ear.scribe import Transcription
from cascadevoice.events import (
    ConnectedEvent,
    ControlEvent,
    ErrorEvent,
    Event,
    StatusEvent,
    TranscriptEvent,
    TurnCompleteEvent,
)
from cascadevoice.hooks import PassThrough, TurnHook, TurnPlan
from cascadevoice.language import detect_local
from cascadevoice.llm import END_CALL, VOICE_GUIDANCE, Conversation, TextDelta, Tool, ToolCall
from cascadevoice.metrics import TurnMetrics
from cascadevoice.playback import PlaybackClock
from cascadevoice.text import SentenceBuffer, is_backchannel, is_noise_transcript
from cascadevoice.transport import Transport

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = "You are Asha, a warm and concise voice assistant. Help the user with whatever they need."
DEFAULT_GREETING = "Hi, this is Asha. How can I help you today?"


@dataclass
class SpeechUnit:
    """One sentence's audio for ordered playout: a chunk queue that fills
    (terminated by None) while earlier sentences are still playing."""

    chunks: Optional[asyncio.Queue] = None
    sample_rate: int = d.TTS_SAMPLE_RATE
    cache_hit: bool = False
    text_only: bool = False
    first_chunk_at: float = 0.0
    pump: Optional[asyncio.Task] = None


@dataclass
class _Turn:
    """What one turn has done so far — enough to record it correctly however
    it ends (finished, cut by a barge-in, or superseded before it spoke)."""

    transcript: Optional[str] = None
    tool_messages: List[dict] = field(default_factory=list)


class VoiceSession:
    """One conversation. Vendors are injectable (tests, other projects);
    by default they are built from the two keys in ``.env``."""

    def __init__(
        self,
        transport: Transport,
        *,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        greeting: Optional[str] = DEFAULT_GREETING,
        hook: Optional[TurnHook] = None,
        tools: Sequence[Tool] = (),
        llm: Any = None,
        tts: Any = None,
        ear_factory: Optional[Callable[[str], Any]] = None,
        batch_stt: Any = None,
        vad: Optional[VADProcessor] = None,
        cache: Optional[AudioCache] = None,
        on_event: Optional[Callable[[Event], Any]] = None,
    ) -> None:
        if llm is None or tts is None or ear_factory is None or batch_stt is None:
            from cascadevoice.defaults import load_keys
            from cascadevoice.ear.scribe import NoStreamEar, ScribeRealtimeStream
            from cascadevoice.elevenlabs import ElevenLabsTTS, OpenAIBatch, ScribeBatch
            from cascadevoice.llm import OpenAILLM

            keys = load_keys()
            llm = llm or OpenAILLM(keys.openai)
            tts = tts or ElevenLabsTTS(keys.elevenlabs)
            if d.STT_PROVIDER == "openai":
                ear_factory = ear_factory or (lambda language: NoStreamEar())
                batch_stt = batch_stt or OpenAIBatch(keys.openai)
            else:
                ear_factory = ear_factory or (lambda language: ScribeRealtimeStream(keys.elevenlabs, language=language))
                batch_stt = batch_stt or ScribeBatch(keys.elevenlabs)
        self.transport = transport
        self.llm, self.tts, self.batch_stt = llm, tts, batch_stt
        self._ear_factory = ear_factory
        self.hook: TurnHook = hook or PassThrough()
        self.system_prompt = system_prompt
        self.greeting = greeting
        self.tools = {tool.name: tool for tool in tools}
        self.tools.setdefault(END_CALL.name, END_CALL)
        self.cache = cache or audio_cache
        self._on_event = on_event
        self.session_id = uuid4().hex
        self.language = d.LANGUAGE
        self.conversation = Conversation()

        self._vad = vad or VADProcessor.from_defaults()
        self._pcm_remainder = b""
        # What the user is hearing right now — distinct from what the server
        # is sending, which finishes seconds earlier.
        self._playback = PlaybackClock(tail_padding=d.PLAYBACK_TAIL_PADDING_S)
        self._ear: Any = None
        self._partial_watch: Optional[asyncio.Task] = None
        self._turn_task: Optional[asyncio.Task] = None
        self._generating = False
        self._turn_spoke = False
        self._hanging_up = False
        self._closed = False
        # An onset was heard over the agent but has not yet sustained long
        # enough to justify cutting the agent off.
        self._pending_barge_in = False
        self._barge_gate_task: Optional[asyncio.Task] = None
        # A backchannel heard over the agent's line, parked to be answered
        # once the line has actually finished (see _drain_replay).
        self._parked_backchannel: Optional[tuple] = None
        self._drain_replay_task: Optional[asyncio.Task] = None
        # A transcript whose reply was cancelled before any of it played. The
        # user said something, heard nothing back, and spoke again — the two
        # utterances are one answer and must reach the model together.
        self._pending_user_text: Optional[str] = None
        # Set by interrupt() for the turn being cancelled: what was heard.
        self._cut_heard: Optional[str] = None
        # Where the last finished reply sits in the history — truncated to
        # what was heard if the user cuts it off while it is still playing.
        self._last_reply_at: Optional[int] = None
        # Strong references for fire-and-forget tasks — see _spawn.
        self._background: set = set()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        await self._emit(ConnectedEvent(
            call_id=self.session_id, llm=getattr(self.llm, "name", "llm"),
            voice=str(getattr(self.tts, "voice_id", "")), vad=describe_engine(), language=self.language,
            frame_size_bytes=FRAME_SIZE_BYTES,
        ))
        if self.greeting:
            # Interruptible like any other line — a user who answers over the
            # greeting is exactly who barge-in is for.
            self._turn_task = asyncio.create_task(self._speak_lines([self.greeting]), name="greeting")
        else:
            await self._emit(StatusEvent(status="listening"))

    async def close(self, reason: str = "disconnected") -> None:
        if self._closed:
            return
        self._closed = True
        logger.info(f"[Session] Closing ({reason})")
        for task in (self._turn_task, self._barge_gate_task, self._drain_replay_task, self._partial_watch):
            if task is not None and not task.done():
                task.cancel()
        self._discard_ear()

    async def say(self, text: str, *, end_call: bool = False) -> None:
        """Speak a fixed line now (cached), as its own turn — e.g. from the
        host when something happens outside the conversation."""
        await self._cut_or_cancel()
        self._turn_task = asyncio.create_task(self._speak_lines([text], end_call=end_call), name="say")

    async def hang_up(self, reason: str = "completed") -> None:
        """Tell the client to hang up once playback drains (and close the
        transport, for one that needs it)."""
        if self._hanging_up:
            return
        self._hanging_up = True
        logger.info(f"[Session] Ending the call — {reason}")
        await self._emit(ControlEvent(action="hangup", reason=reason))
        if self.transport.hangup_requires_close:
            await asyncio.sleep(self._playback.remaining + 0.5)
            await self.transport.close()

    # ── Audio in ──────────────────────────────────────────────────────────────

    async def feed_pcm(self, pcm16: bytes) -> None:
        """16 kHz mono PCM-16 in any chunk size; frames are realigned here."""
        if self._hanging_up or self._closed:
            # A closing line is draining: a turn now would answer a call that
            # believes it has already ended.
            return
        buffer = self._pcm_remainder + pcm16
        self._pcm_remainder = b""
        while len(buffer) >= FRAME_SIZE_BYTES:
            frame, buffer = buffer[:FRAME_SIZE_BYTES], buffer[FRAME_SIZE_BYTES:]
            # A stream open before this frame gets the frame after the VAD has
            # seen it. One opened *by* this frame (speech onset) seeded itself
            # from the VAD's buffer, which already holds it — feeding it again
            # would double the first syllable.
            ear = self._ear
            await self._handle_vad(self._vad.process_frame(frame))
            if ear is not None and ear is self._ear and self._vad.in_speech:
                ear.feed(frame)
        self._pcm_remainder = buffer

    def _agent_audible(self) -> bool:
        return self._playback.is_speaking

    def _should_barge_in(self) -> bool:
        """Whether speech now could be cutting the agent off."""
        if not self._agent_audible():
            return False
        # The first moments of a run of speech are exempt: an answer over the
        # agent's opening syllable is usually noise, not an interruption.
        return self._playback.speaking_for >= d.BARGE_IN_GRACE_S

    async def _handle_vad(self, result: VADResult) -> None:
        # Keep the onset threshold in step with whether the agent's own voice
        # could be leaking into the microphone.
        self._vad.set_agent_speaking(self._agent_audible())

        if result.event is VADEvent.SPEECH:
            # Acoustic sustain alone hard-cuts the agent only for speech long
            # enough that it cannot be a backchannel grunt; shorter runs wait
            # for end of utterance, where the transcript decides.
            if self._pending_barge_in and result.speech_frames * FRAME_DURATION_MS >= d.BARGE_IN_HARD_MS:
                self._pending_barge_in = False
                if self._should_barge_in():
                    logger.info(f"[Barge-in] Sustained speech over the agent — {self._playback.remaining:.1f}s dropped")
                    await self.interrupt(reason="barge_in")
                    await self._emit(StatusEvent(status="listening"))

        elif result.event is VADEvent.PAUSE_HINT:
            self._judge_pause()

        elif result.event is VADEvent.SPEECH_START:
            self._cancel_partial_watch()
            self._open_ear()
            if self._should_barge_in():
                # Not an interruption yet: sub-second noise bursts reach here
                # too, and cutting the agent off for one leaves dead air.
                self._pending_barge_in = True
            else:
                await self._emit(StatusEvent(status="listening"))

        elif result.event is VADEvent.SPEECH_ABORTED:
            # Noise. The agent was never interrupted; a pending barge-in
            # simply evaporates.
            self._pending_barge_in = False
            self._discard_ear()

        elif result.event is VADEvent.END_OF_UTTERANCE and result.speech_pcm:
            self._pending_barge_in = False
            metrics = TurnMetrics(t_eou=time.perf_counter(),
                                  endpoint_wait_ms=result.silence_frames * FRAME_DURATION_MS)
            await self._end_utterance(result.speech_pcm, metrics)

    async def _end_utterance(self, pcm: bytes, metrics: TurnMetrics) -> None:
        self._cancel_partial_watch()
        pending = self._commit_ear()
        if self._should_barge_in():
            # Decision deferred: classify the transcript before touching
            # playback at all. A backchannel leaves the agent talking.
            self._barge_gate_task = asyncio.create_task(self._gate_barge_in(pcm, metrics, pending), name="barge_gate")
        else:
            self._vad.set_agent_speaking(False)
            await self._begin_turn(pcm, metrics, pending)

    # ── The ear ───────────────────────────────────────────────────────────────

    def _open_ear(self) -> None:
        """At speech onset: open this utterance's stream, seeded with the onset
        frames the VAD already buffered. Connecting runs while the user talks."""
        self._discard_ear()
        stream = self._ear_factory(self.language)
        stream.feed(self._vad.speech_so_far)
        self._ear = stream
        self._spawn(stream.open(), name="ear_open")

    def _commit_ear(self) -> Optional[asyncio.Task]:
        stream, self._ear = self._ear, None
        if stream is None:
            return None
        return asyncio.create_task(stream.commit(), name="ear_commit")

    def _discard_ear(self) -> None:
        stream, self._ear = self._ear, None
        if stream is not None:
            self._spawn(stream.close(), name="ear_close")

    def _judge_pause(self) -> None:
        """Halfway through the silence window: is the sentence finished?

        The realtime stream has been transcribing all along, so its latest
        partial IS the pause-time transcript, for free. Complete → commit the
        endpoint now instead of waiting out the window. Mid-thought → give the
        user more room before the timer cuts them off.
        """
        stream = self._ear
        if stream is None or getattr(stream, "failed", None):
            return
        partial = (stream.partial_text or "").strip()
        if not partial:
            # Nothing recognised *yet* is not nothing to say. One look at the
            # halfway mark made the judgment a race against the vendor; keep
            # looking until the endpoint actually fires.
            self._watch_for_partial(stream)
            return
        verdict = turns.assess(partial)
        if verdict is turns.Verdict.COMPLETE and d.EARLY_COMMIT:
            silence_ms = self._vad.silence_ms_so_far
            pcm = self._vad.commit()
            if pcm is None:
                return
            logger.info(f"[Endpoint] Complete at the pause — committing early: {partial!r}")
            self._pending_barge_in = False
            metrics = TurnMetrics(t_eou=time.perf_counter(), endpoint_wait_ms=silence_ms)
            self._spawn(self._end_utterance(pcm, metrics), name="early_commit")
        elif verdict is turns.Verdict.INCOMPLETE:
            logger.info(f"[Endpoint] Mid-thought at the pause — extending the window: {partial!r}")
            self._vad.extend_current_eou(max(1, int(d.ENDPOINT_EXTENSION_MS / FRAME_DURATION_MS)))

    def _watch_for_partial(self, stream: Any) -> None:
        if self._partial_watch is not None and not self._partial_watch.done():
            return

        async def watch() -> None:
            while self._vad.in_speech and stream is self._ear:
                await asyncio.sleep(0.04)
                if getattr(stream, "failed", None):
                    return
                if (stream.partial_text or "").strip():
                    self._judge_pause()
                    return

        self._partial_watch = asyncio.create_task(watch(), name="partial_watch")

    def _cancel_partial_watch(self) -> None:
        watch, self._partial_watch = self._partial_watch, None
        if watch is not None and not watch.done():
            watch.cancel()

    async def _transcript(self, pcm: bytes, pending: Optional[asyncio.Future], metrics: TurnMetrics):
        """The realtime commit, else batch Scribe on the buffered utterance.
        None for silence or noise."""
        result = None
        if pending is not None:
            try:
                result = await pending
                metrics.stt_source = metrics.stt_source or "realtime"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"[STT] Realtime commit failed ({exc!r}) — batch")
        if result is None or not result.text.strip():
            try:
                result = await self.batch_stt.transcribe(pcm, language=self.language)
                metrics.stt_source = "batch"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"[STT] Batch Scribe failed: {exc!r}")
                result = None
        if not metrics.t_stt_done:
            metrics.t_stt_done = time.perf_counter()
        if result is None or is_noise_transcript(turns.strip_events(result.text)):
            logger.info(f"[STT] Discarded noise transcript {getattr(result, 'text', '')!r}")
            return None
        return result

    # ── False-interruption gate ──────────────────────────────────────────────
    #
    # The interrupt decision moves to end of utterance: transcribe first (the
    # realtime commit, ~125 ms), then classify. A real interruption cuts the
    # agent off; a backchannel ("haan", "hmm") leaves the reply and its audio
    # alone and is parked, to be answered once the line actually finishes.

    def _classify_barge_in(self, text: str) -> str:
        """"real" or "park" for a transcript heard while the agent was audible."""
        words = text.strip().split()
        verdict = turns.assess(text)
        at_tail = self._playback.remaining <= d.BARGE_IN_TAIL_WINDOW_S
        if verdict is turns.Verdict.COMPLETE and at_tail:
            # On the question's tail a complete answer — "haan" included — IS
            # the answer, not a backchannel. Checked before the backchannel
            # test or the answer would park forever.
            return "real"
        if is_backchannel(text) or (len(words) <= d.BARGE_IN_MAX_BACKCHANNEL_WORDS
                                    and verdict is not turns.Verdict.COMPLETE):
            return "park"
        return "real"

    async def _gate_barge_in(self, pcm: bytes, metrics: TurnMetrics, pending: Optional[asyncio.Task]) -> None:
        try:
            result = await self._transcript(pcm, pending, metrics)
            done = self._done(result)
            if result is None:
                return   # noise over the agent: nothing to do, it keeps talking
            if not self._should_barge_in():
                # Playback drained while this was transcribing: just a turn.
                await self._begin_turn(pcm, metrics, done)
                return
            if self._classify_barge_in(result.text) == "real":
                logger.info(f"[Barge-in] Real interruption: {result.text!r}")
                await self.interrupt(reason="barge_in")
                self._vad.set_agent_speaking(False)
                await self._begin_turn(pcm, metrics, done)
            else:
                logger.info(f"[Barge-in] Backchannel over the agent — keeping it talking: {result.text!r}")
                self._parked_backchannel = (result, pcm)
                self._start_drain_replay()
        finally:
            self._barge_gate_task = None

    def _start_drain_replay(self) -> None:
        if self._drain_replay_task and not self._drain_replay_task.done():
            self._drain_replay_task.cancel()
        self._drain_replay_task = asyncio.create_task(self._drain_replay(), name="drain_replay")

    async def _drain_replay(self) -> None:
        """Answer a parked backchannel once the agent's line finishes and the
        user has said nothing else — an eager "haan" over the question's tail
        becomes the answer once the question has been heard in full."""
        while True:
            remaining = self._playback.remaining
            if remaining <= 0 and not self._generating:
                break
            # Short steps, not one long sleep: the line can be cut or extended.
            await asyncio.sleep(min(max(0.05, remaining), 0.25))
        await asyncio.sleep(self._playback.tail_padding)
        if self._vad.in_speech or self._generating or self._parked_backchannel is None:
            return
        result, pcm = self._parked_backchannel
        self._parked_backchannel = None
        logger.info(f"[Barge-in] Answering the parked backchannel: {result.text!r}")
        metrics = TurnMetrics(t_eou=time.perf_counter(), stt_source="parked")
        metrics.t_stt_done = metrics.t_eou
        await self._begin_turn(pcm, metrics, self._done(result))

    def _claim_parked_backchannel(self) -> None:
        """Fold a parked backchannel into the next turn, so it is answered
        once, in order, and never twice by a replay that fires after all."""
        if self._parked_backchannel is None:
            return
        result, _ = self._parked_backchannel
        self._parked_backchannel = None
        self._pending_user_text = f"{result.text} {self._pending_user_text or ''}".strip()
        if self._drain_replay_task and not self._drain_replay_task.done():
            self._drain_replay_task.cancel()

    # ── Interrupting ──────────────────────────────────────────────────────────

    async def interrupt(self, reason: str = "client_request") -> None:
        """Stop speaking now and record only what the user actually heard.

        Recording the full generated reply would leave the model believing it
        said things the user never heard — and it would answer accordingly.
        """
        audible = self._agent_audible()
        heard = self._playback.stop()
        self._vad.set_agent_speaking(False)
        await self.transport.stop_playback()
        running = self._turn_task is not None and not self._turn_task.done()
        self._cut_heard = heard
        await self._cancel_turn()
        if not running and audible and self._last_reply_at is not None:
            # The reply had been fully sent (and recorded) but was still
            # playing: truncate it to what was heard.
            message = self.conversation.messages[self._last_reply_at]
            if heard:
                message["content"] = heard
            else:
                self.conversation.messages.pop(self._last_reply_at)
            logger.info(f"[Session] Interrupted ({reason}) after: {heard[:60]!r}")
        self._last_reply_at = None
        self._cut_heard = None

    async def _cut_or_cancel(self) -> None:
        """Before a new turn: an audible agent is interrupted (recording what
        was heard); a silent in-flight turn is just cancelled."""
        if self._agent_audible():
            await self.interrupt(reason="superseded")
        else:
            await self._cancel_turn()

    async def _cancel_turn(self) -> None:
        task, self._turn_task = self._turn_task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def _record_cancelled(self, turn: _Turn) -> None:
        """A turn ended early. Put in the history exactly what happened."""
        heard = self._cut_heard
        self._cut_heard = None
        if heard:
            if turn.transcript:
                self.conversation.add_user(turn.transcript)
            self.conversation.extend(turn.tool_messages)
            self.conversation.add_agent(heard)
            logger.info(f"[Session] Reply cut after: {heard[:60]!r}")
        elif turn.transcript and not self._turn_spoke:
            # Nothing of the reply was heard: the user spoke again into
            # silence. Losing this transcript is how an agent forgets a "yes"
            # and asks again — carry it into the next turn.
            self._pending_user_text = f"{self._pending_user_text or ''} {turn.transcript}".strip()
            logger.info(f"[Session] Follow-up before the reply played — carrying {turn.transcript!r} forward")

    # ── Turns ─────────────────────────────────────────────────────────────────

    async def _begin_turn(self, pcm: bytes, metrics: TurnMetrics, pending: Optional[asyncio.Future]) -> None:
        self._claim_parked_backchannel()
        await self._cut_or_cancel()
        self._turn_task = asyncio.create_task(self._run_turn(pcm, metrics, pending), name="turn")

    async def submit_text(self, text: str) -> None:
        """A typed turn: the text stands in for a transcript. A second one
        while the first is in flight cancels it, and the first's text is
        carried into the second."""
        text = (text or "").strip()
        if not text or self._closed:
            return
        await self._cut_or_cancel()
        metrics = TurnMetrics(t_eou=time.perf_counter(), stt_source="typed")
        metrics.t_stt_done = metrics.t_eou
        self._turn_task = asyncio.create_task(
            self._run_turn(b"", metrics, self._done(Transcription(text=text, language=self.language, latency_ms=0,
                                                                  model="typed"))),
            name="typed_turn")

    async def _run_turn(self, pcm: bytes, metrics: TurnMetrics, pending: Optional[asyncio.Future]) -> None:
        turn = _Turn()
        self._generating = True
        self._turn_spoke = False
        try:
            await self._emit(StatusEvent(status="transcribing"))
            result = await self._transcript(pcm, pending, metrics)
            if result is None:
                await self._emit(StatusEvent(status="listening"))
                return
            text = result.text.strip()
            self._follow_language(text)
            await self._emit(TranscriptEvent(role="user", text=text, language=self.language))
            if self._pending_user_text:
                text = f"{self._pending_user_text} {text}".strip()
                self._pending_user_text = None
                logger.info(f"[Session] Merged the follow-up into one turn: {text!r}")
            turn.transcript = text
            await self._respond(turn, metrics)
        except asyncio.CancelledError:
            self._record_cancelled(turn)
            raise
        except Exception as exc:
            logger.error(f"[Session] Turn failed: {exc!r}", exc_info=True)
            await self._emit(ErrorEvent(message=str(exc)[:200]))
            await self._emit(StatusEvent(status="listening"))
        finally:
            self._generating = False

    def _follow_language(self, text: str) -> None:
        """The call's language is whatever the user last spoke — decided by the
        words, never by the STT's label (a one-word English answer labelled
        Hindi once flipped a whole call)."""
        detected = detect_local(text, english=d.LANGUAGE if d.LANGUAGE.startswith("en") else "en-IN")
        if detected != self.language:
            logger.info(f"[Session] Language {self.language} → {detected}")
            self.language = detected

    async def _respond(self, turn: _Turn, metrics: TurnMetrics) -> None:
        plan: Optional[TurnPlan] = None
        try:
            plan = await self.hook.before_reply(turn.transcript, language=self.language,
                                                history=list(self.conversation.messages))
        except Exception as exc:  # noqa: BLE001 — a broken hook must not cost the turn
            logger.error(f"[Hook] before_reply failed: {exc!r}")
        await self._emit(StatusEvent(status="thinking"))
        end_call = bool(plan and plan.end_call)
        speaker = _Speaker(self, metrics, cacheable=bool(plan and plan.reply))
        try:
            if plan is not None and plan.reply:
                metrics.hooked = True
                metrics.t_llm_first_sentence = time.perf_counter()
                await speaker.say(plan.reply)
            else:
                end_call = await self._stream_reply(turn, speaker, metrics, plan) or end_call
            await speaker.finish()
        except BaseException:
            # Barge-in or a vendor failure: drop queued audio rather than speak
            # over the user.
            speaker.abort()
            raise
        reply = " ".join(speaker.sentences).strip()
        self.conversation.add_user(turn.transcript)
        self.conversation.extend(turn.tool_messages)
        self.conversation.add_agent(reply)
        self._last_reply_at = len(self.conversation.messages) - 1 if reply else None
        await self._emit(TurnCompleteEvent(full_text=reply))
        if end_call:
            await self.hang_up(reason="end_call")
        else:
            await self._emit(StatusEvent(status="listening"))

    async def _stream_reply(self, turn: _Turn, speaker: "_Speaker", metrics: TurnMetrics,
                            plan: Optional[TurnPlan]) -> bool:
        """Stream the model, speaking each sentence the moment it completes;
        run tools between rounds. Returns True when the model ended the call."""
        system = self.system_prompt + (f"\n\n{VOICE_GUIDANCE}" if VOICE_GUIDANCE else "")
        messages: List[dict] = [{"role": "system", "content": system}, *self.conversation.window()]
        if plan is not None and plan.instructions:
            messages.append({"role": "system", "content": plan.instructions})
        messages.append({"role": "user", "content": turn.transcript})
        schemas = [tool.schema() for tool in self.tools.values()]
        end_call = False
        for _ in range(d.LLM_MAX_TOOL_ROUNDS + 1):
            calls: List[ToolCall] = []
            said = ""
            async for event in self.llm.stream(messages, tools=schemas):
                if not metrics.t_llm_first_token:
                    metrics.t_llm_first_token = time.perf_counter()
                if isinstance(event, ToolCall):
                    calls.append(event)
                elif isinstance(event, TextDelta):
                    said += event.text
                    await speaker.push(event.text)
            if not calls:
                break
            # Whatever was said before the tool runs is spoken while it runs.
            await speaker.flush()
            assistant = {"role": "assistant", "content": said or None, "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                for c in calls]}
            results = []
            for call in calls:
                if call.name == END_CALL.name:
                    end_call = True
                result = await self._run_tool(call)
                results.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})
            messages += [assistant, *results]
            turn.tool_messages += [assistant, *results]
            if end_call:
                break   # the goodbye was said with the call; nothing more to add
        await speaker.flush()
        return end_call

    async def _run_tool(self, call: ToolCall) -> Any:
        tool = self.tools.get(call.name)
        if tool is None:
            logger.warning(f"[Tool] The model called {call.name!r}, which it was never given")
            return {"error": f"unknown tool {call.name}"}
        try:
            result = await tool.run(call.args)
            logger.info(f"[Tool] {call.name}({call.args}) → {str(result)[:80]}")
            return result
        except Exception as exc:  # noqa: BLE001 — a failing tool costs the tool, not the call
            logger.error(f"[Tool] {call.name} failed: {exc!r}")
            return {"error": str(exc)[:200]}

    async def _speak_lines(self, lines: List[str], *, end_call: bool = False) -> None:
        """Fixed lines (the greeting, say()): cached, interruptible."""
        turn = _Turn()
        speaker = _Speaker(self, None, cacheable=True)
        self._turn_spoke = False
        try:
            for line in lines:
                await speaker.say(line)
            await speaker.finish()
        except asyncio.CancelledError:
            speaker.abort()
            self._record_cancelled(turn)
            raise
        reply = " ".join(speaker.sentences)
        self.conversation.add_agent(reply)
        self._last_reply_at = len(self.conversation.messages) - 1
        await self._emit(TurnCompleteEvent(full_text=reply))
        if end_call:
            await self.hang_up(reason="say")
        else:
            await self._emit(StatusEvent(status="listening"))

    # ── Synthesis and ordered playout ────────────────────────────────────────

    async def _synthesize(self, text: str, gate: asyncio.Semaphore, cacheable: bool) -> SpeechUnit:
        """This sentence's audio, streamed. Returns as soon as the stream is
        open; a pump keeps filling the unit while earlier sentences play, so
        synthesis overlaps playout instead of extending it."""
        if not self.transport.wants_audio:
            return SpeechUnit(text_only=True)
        voice = str(getattr(self.tts, "voice_id", ""))
        rate = getattr(self.tts, "sample_rate", d.TTS_SAMPLE_RATE)
        chunks: asyncio.Queue = asyncio.Queue()
        cached = self.cache.get(text, voice, rate)
        if cached is not None:
            chunks.put_nowait(cached)
            chunks.put_nowait(None)
            return SpeechUnit(chunks=chunks, sample_rate=rate, cache_hit=True, first_chunk_at=time.perf_counter())

        unit = SpeechUnit(chunks=chunks, sample_rate=rate)

        async def pump() -> None:
            kept = bytearray()
            try:
                async with gate:
                    try:
                        unit.sample_rate, upstream = await self.tts.open(text, language=self.language)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(f"[TTS] Could not open a stream ({exc!r}) — one-shot")
                        pcm = await self.tts.synthesize(text, language=self.language)
                        upstream = _once(pcm)
                    async for chunk in upstream:
                        if not unit.first_chunk_at:
                            unit.first_chunk_at = time.perf_counter()
                        if cacheable:
                            kept += chunk
                        await chunks.put(chunk)
                if cacheable and kept:
                    self.cache.put(text, voice, unit.sample_rate, bytes(kept))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # One unspeakable sentence costs that sentence, not the turn.
                logger.error(f"[TTS] Failed mid-sentence: {exc!r}")
            finally:
                chunks.put_nowait(None)

        unit.pump = self._spawn(pump(), name="tts_pump")
        return unit

    async def _deliver(self, text: str, index: int, unit: SpeechUnit, metrics: Optional[TurnMetrics]) -> bool:
        """Send one sentence's audio in playout order."""
        if unit.text_only:
            return True
        await self.transport.begin_audio_stream(unit.sample_rate)
        sent = 0
        first = True
        try:
            while True:
                chunk = await unit.chunks.get()
                if chunk is None:
                    break
                # The clock carries the sentence text on its first chunk only,
                # so an interruption records the sentence as heard exactly once.
                self._playback.enqueue(text if first else "", len(chunk) / 2 / unit.sample_rate)
                self._vad.set_agent_speaking(True)
                await self.transport.send_audio_chunk(chunk)
                sent += len(chunk)
                if first:
                    first = False
                    # After the chunk: bookkeeping never delays audio.
                    if metrics is not None and index == 1:
                        metrics.t_tts_first = unit.first_chunk_at
                        metrics.t_audio_out = time.perf_counter()
                        metrics.cache_hit = unit.cache_hit
                        await self._emit(metrics.log())
                    await self._emit(StatusEvent(status="speaking"))
        finally:
            # Always close the bracket — a barge-in mid-stream must not leave
            # the client reading later frames at the wrong rate.
            await self.transport.end_audio_stream()
        return sent > 0

    async def _playout(self, queue: asyncio.Queue, metrics: Optional[TurnMetrics]) -> None:
        while True:
            item = await queue.get()
            if item is None:
                return
            index, text, job = item
            unit = await job
            # The user started talking while this was synthesizing: hold.
            # Either their speech ends short of an utterance (resume), or an
            # end of utterance cancels this turn. The gate holds it too: the
            # VAD has already reset when the gate starts, and without this a
            # held unit would resume mid-decision and be cut a moment later.
            while self._vad.in_speech or (self._barge_gate_task is not None and not self._barge_gate_task.done()):
                await asyncio.sleep(0.05)
            if await self._deliver(text, index, unit, metrics):
                self._turn_spoke = True

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _done(result) -> asyncio.Future:
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        future.set_result(result)
        return future

    def _spawn(self, coro, *, name: str) -> asyncio.Task:
        """create_task with a strong reference until it finishes. asyncio holds
        tasks weakly; one referenced only by its own await chain (a stream's
        send loop parked on its queue) can be collected mid-flight — it showed
        up as "Task was destroyed but it is pending!" and an utterance that
        silently fell back to batch STT."""
        task = asyncio.create_task(coro, name=name)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def _emit(self, event: Event) -> None:
        if self._on_event is not None:
            try:
                result = self._on_event(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[Session] on_event hook failed: {exc!r}")
        await self.transport.send_event(event)


async def _once(pcm: Optional[bytes]):
    if pcm:
        yield pcm


class _Speaker:
    """One reply's sentences → concurrent synthesis → ordered playout.

    Synthesis runs concurrently with generation *and* with the sending of
    earlier audio, while the playout task preserves order. Waiting for
    sentence N to be sent before synthesizing N+1 put the full synthesis
    latency into the gap between every pair of sentences.
    """

    def __init__(self, session: VoiceSession, metrics: Optional[TurnMetrics], *, cacheable: bool) -> None:
        self.session = session
        self.metrics = metrics
        self.cacheable = cacheable
        self.sentences: List[str] = []
        self._buffer = SentenceBuffer(
            eager_first=True, min_eager_chars=d.EAGER_FIRST_CHUNK_MIN_CHARS, min_unit_chars=d.TTS_MIN_UNIT_CHARS,
            is_cached_prefix=lambda partial: session.cache.has_prefix(
                partial, str(getattr(session.tts, "voice_id", "")), getattr(session.tts, "sample_rate", d.TTS_SAMPLE_RATE)),
        )
        self._gate = asyncio.Semaphore(d.TTS_PIPELINE_DEPTH)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._jobs: List[asyncio.Task] = []
        self._playout = asyncio.create_task(session._playout(self._queue, metrics), name="playout")

    async def push(self, text: str) -> None:
        for unit in self._buffer.push(text):
            await self.say(unit)

    async def flush(self) -> None:
        leftover = self._buffer.flush()
        if leftover:
            await self.say(leftover)

    async def say(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not self.sentences and self.metrics is not None and not self.metrics.t_llm_first_sentence:
            self.metrics.t_llm_first_sentence = time.perf_counter()
        self.sentences.append(text)
        index = len(self.sentences)
        await self.session._emit(TranscriptEvent(role="agent", text=text, index=index))
        job = asyncio.create_task(self.session._synthesize(text, self._gate, self.cacheable), name=f"tts:{index}")
        self._jobs.append(job)
        await self._queue.put((index, text, job))

    async def finish(self) -> None:
        await self._queue.put(None)
        await self._playout

    def abort(self) -> None:
        self._playout.cancel()
        for job in self._jobs:
            job.cancel()
            if job.done() and not job.cancelled() and job.exception() is None:
                pump = job.result().pump
                if pump is not None:
                    pump.cancel()
