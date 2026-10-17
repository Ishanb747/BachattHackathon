"""Noise-robust dual-stage voice-activity detection.

Combines:
  1. RMS Energy Floor: Filters out low-level background hiss, fan noise, AC hum (< 350 RMS).
  2. A frame classifier (Silero VAD by default, webrtcvad as a fallback/rollback
     — see vad_engines): classifies human speech vs non-speech noise.
  3. Speech Onset Debounce: Requires 3 consecutive voiced frames (60ms) to trigger SPEECH_START,
     preventing clicks, desk taps, coughs, or breaths from interrupting the assistant.
  4. Adaptive EOU Window: sustained silence after speech triggers EOU. The
     length is defaults.EOU_SILENCE_MS (from_defaults passes it in); the
     constant below is only the library default.
  5. Pre-Roll Ring Buffer: 350ms (17 frames) prepended to never clip opening consonants.
  6. Pause Hint: halfway through the end-of-utterance wait, the speech so far is
     offered to the caller so transcription can start speculatively. If speech
     resumes the caller throws it away; if it does not, the end-of-utterance
     arrives with the transcript already in flight. The duplex session uses
     it to ask "is the sentence finished?" and extend the window if not.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from cascadevoice.audio.codecs import SAMPLE_RATE, rms_energy as compute_rms
from cascadevoice.audio.vad_engines import FrameClassifier, create_classifier

logger = logging.getLogger(__name__)


# ─── Configuration ─────────────────────────────────────────────────────────────

FRAME_DURATION_MS      = 20      # ms — browser sends 20ms chunks
FRAME_SIZE_SAMPLES     = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 320 samples
FRAME_SIZE_BYTES       = FRAME_SIZE_SAMPLES * 2                        # 640 bytes (int16)

# Energy floor: RMS under this threshold is treated as silence (filters background noise)
MIN_RMS_ENERGY         = 450.0   # Scale: 0 to 32767 (normal speech is 800 - 6000+)

# Adaptive noise floor. A fixed energy gate is right for a quiet room and wrong
# for a fan, a TV, or a street: steady background can sit well above it and
# stream false onsets at the debouncer — spurious barge-ins and junk turns. The
# processor tracks ambient loudness as an EMA over frames it did NOT classify
# as speech and gates onsets at a multiple of that ambient level. Speech frames
# never feed the average, so the customer's voice cannot raise the bar against
# itself; the absolute floor above still applies in quiet rooms.
NOISE_EMA_ALPHA        = 0.05    # per-frame weight → ~400ms adaptation time constant
NOISE_GATE_FACTOR      = 2.0     # speech must be at least this multiple of ambient — library
                                  # default; from_defaults uses VAD_NOISE_GATE_FACTOR
                                  # (1.5, after a quiet-digit-in-noise report).
NOISE_GATE_CAP         = 6000.0  # never demand more than this, or loud rooms go deaf

# Speaker focus. WebRTC VAD cannot tell the customer from a TV or a person
# across the room — both are speech, and neither feeds the ambient floor above
# (voiced frames are excluded from it by design). What does separate them is
# level: the customer is near-field and reliably much louder than a far-field
# background voice. The processor tracks the customer's own speech level across
# confirmed utterances and demands that a new onset come within earshot of it.
# A stricter multiple applies while the agent is audible, because a false
# positive there cuts the agent off mid-sentence.
SPEAKER_FOCUS_FACTOR    = 0.35   # onset must reach this fraction of the customer's level
BARGE_IN_FOCUS_FACTOR   = 0.5    # stricter while the agent is audible
SPEAKER_EMA_ALPHA       = 0.5    # per-utterance blend into the running estimate
SPEAKER_DECAY_PER_FRAME = 0.9997 # ~60s time constant: a customer who moved away
                                 # from the mic is never locked out for good

# Onset Debounce: consecutive voiced frames needed to confirm speech start
ONSET_DEBOUNCE_FRAMES  = 3       # 3 frames = 60ms of continuous speech

# Stricter onset while the agent is audible. Echo cancellation removes most of
# the agent's own voice from the mic, but not all of it on speakerphones, and a
# false trigger here cuts the agent off mid-sentence. Demanding more sustained
# speech before believing a barge-in costs the customer ~40ms and removes most
# spurious interruptions.
BARGE_IN_ONSET_FRAMES  = 5       # 5 frames = 100ms of continuous speech

# End-of-utterance: this much sustained silence after speech ends the turn.
# from_defaults overrides it with EOU_SILENCE_MS; this is only the
# default for direct construction and the tests. It is deliberately short, and
# short is wrong for prose: a speaker hunting for a word pauses 300-600ms, so
# a window under that cuts them off mid-sentence. See the setting's comment.
EOU_SILENCE_MS         = 220
EOU_SILENCE_FRAMES     = int(EOU_SILENCE_MS / FRAME_DURATION_MS)  # 11

# Minimum speech to consider a valid utterance (discards clicks/coughs).
# Tuned against real synthesized speech: a spoken "Yes." is ~150-250ms of voiced
# audio, so the old 260ms floor silently discarded the most important answers a
# survey call receives. 140ms passes every word tested ("Yes.", "No.", "Four.",
# "Haan ji.") while still rejecting clicks up to 120ms.
MIN_SPEECH_MS          = 140
MIN_SPEECH_FRAMES      = int(MIN_SPEECH_MS / FRAME_DURATION_MS)   # 7

# Pre-roll: 350ms = 17 frames of audio prepended before speech start
PRE_ROLL_MS            = 350
PRE_ROLL_FRAMES        = int(PRE_ROLL_MS / FRAME_DURATION_MS)     # 17

# Pause hint: fires halfway into the end-of-utterance silence window. Derived
# from the window actually in force, not from the default above, so raising
# `eou_silence_ms` moves the hint with it instead of leaving it at 110ms.
SPECULATIVE_SILENCE_FRAMES = None   # None = half of eou_silence_frames

# WebRTC VAD aggressiveness: 3 is the most aggressive at filtering non-speech noise
VAD_AGGRESSIVENESS     = 3


# ─── Events ────────────────────────────────────────────────────────────────────

class VADEvent(Enum):
    SPEECH            = auto()   # Sustained speech frame
    SILENCE           = auto()   # Silent frame
    SPEECH_START      = auto()   # Confirmed onset of user speech (barge-in trigger)
    PAUSE_HINT        = auto()   # Probably finished — speculative STT trigger
    END_OF_UTTERANCE  = auto()   # User finished speaking (STT trigger)
    SPEECH_ABORTED    = auto()   # Onset was too short to be a real utterance (noise spike)


@dataclass
class VADResult:
    event: VADEvent
    is_voiced: bool
    rms_energy: float
    silence_frames: int
    speech_frames: int
    speech_pcm: Optional[bytes] = None
    vad_latency_ms: float = 0.0


# ─── VADProcessor ──────────────────────────────────────────────────────────────

class VADProcessor:
    """
    Noise-robust stateful frame-level VAD processor with onset debouncing.
    """

    def __init__(
        self,
        aggressiveness: int = VAD_AGGRESSIVENESS,
        min_rms: float = MIN_RMS_ENERGY,
        onset_frames: int = ONSET_DEBOUNCE_FRAMES,
        eou_silence_frames: int = EOU_SILENCE_FRAMES,
        min_speech_frames: int = MIN_SPEECH_FRAMES,
        pre_roll_frames: int = PRE_ROLL_FRAMES,
        speculative_silence_frames: Optional[int] = SPECULATIVE_SILENCE_FRAMES,
        barge_in_onset_frames: int = BARGE_IN_ONSET_FRAMES,
        noise_alpha: float = NOISE_EMA_ALPHA,
        noise_factor: float = NOISE_GATE_FACTOR,
        noise_cap: float = NOISE_GATE_CAP,
        speaker_focus_factor: float = SPEAKER_FOCUS_FACTOR,
        barge_in_focus_factor: float = BARGE_IN_FOCUS_FACTOR,
        speaker_blend: float = SPEAKER_EMA_ALPHA,
        speaker_decay_per_frame: float = SPEAKER_DECAY_PER_FRAME,
        classifier: Optional[FrameClassifier] = None,
    ) -> None:
        self._vad = classifier if classifier is not None else create_classifier("webrtc", aggressiveness=aggressiveness)
        self._min_rms             = min_rms
        self._noise_alpha         = noise_alpha
        self._noise_factor        = noise_factor
        self._noise_cap           = noise_cap
        self._noise_ema           = 0.0
        self._speaker_focus_factor  = speaker_focus_factor
        self._barge_in_focus_factor = barge_in_focus_factor
        self._speaker_blend         = speaker_blend
        self._speaker_decay         = speaker_decay_per_frame
        self._speaker_ema           = 0.0
        self.last_utterance_rms     = 0.0
        self.last_speaker_rms_before = 0.0
        self._utt_rms_sum           = 0.0
        self._utt_rms_count         = 0
        self._onset_frames        = onset_frames
        self._barge_in_onset_frames = barge_in_onset_frames
        self._agent_speaking      = False
        self._eou_silence_frames  = eou_silence_frames
        self._min_speech_frames   = min_speech_frames
        self._pre_roll_frames     = pre_roll_frames
        if speculative_silence_frames is None:
            speculative_silence_frames = max(1, eou_silence_frames // 2)
        self._speculative_frames  = min(speculative_silence_frames, max(1, eou_silence_frames - 1))

        # State
        self._in_speech          = False
        self._consecutive_voiced = 0
        self._speech_frames      = 0
        self._silence_frames     = 0
        self._pause_hinted       = False
        self._eou_extension      = 0    # extra silence frames for this utterance only

        # Circular pre-roll ring buffer
        self._pre_roll: list[bytes] = []
        # Candidate onset buffer (holds frames during the 3-frame debounce check)
        self._onset_buffer: list[bytes] = []
        # Accumulated speech PCM16 (raw bytes)
        self._speech_pcm: bytearray = bytearray()

    def process_frame(self, pcm16_bytes: bytes) -> VADResult:
        t0 = time.perf_counter()

        # Ensure exact frame length
        if len(pcm16_bytes) < FRAME_SIZE_BYTES:
            pcm16_bytes = pcm16_bytes + b'\x00' * (FRAME_SIZE_BYTES - len(pcm16_bytes))
        elif len(pcm16_bytes) > FRAME_SIZE_BYTES:
            pcm16_bytes = pcm16_bytes[:FRAME_SIZE_BYTES]

        # 1. Compute RMS energy
        rms = compute_rms(pcm16_bytes)

        # 2. Dual-stage classification, gated at the current ambient-aware floor.
        # The classifier runs on every frame, not only energy-active ones: a
        # neural classifier (Silero) is stateful across the audio stream, and
        # feeding it only the frames that clear the energy gate would stitch
        # discontinuous audio through its recurrent state and corrupt every
        # verdict after a silence gap. The energy gate is instead an AND-term
        # on the final verdict — same effect on `is_voiced`, but the
        # classifier always sees continuous audio.
        is_energy_active = rms >= self.energy_threshold
        try:
            is_classifier_speech = self._vad.is_speech(pcm16_bytes, SAMPLE_RATE)
        except Exception:
            is_classifier_speech = False

        is_voiced = is_energy_active and is_classifier_speech

        # 3. Speaker focus: a voiced frame quieter than the known customer
        # level cannot START an utterance — it is somebody else's voice. It
        # does not teach the ambient floor either (it is still speech), and
        # frames of an utterance already underway are never gated, so natural
        # level variation cannot chop up real speech.
        speaker_gated = False
        if is_voiced and not self._in_speech:
            gate = self.speaker_gate
            if gate and rms < gate:
                speaker_gated = True
                logger.debug(f"[VAD] Onset gated by speaker focus (RMS {rms:.0f} < {gate:.0f})")

        # 4. Non-speech frames teach the ambient floor — including loud frames
        # WebRTC rejected as non-speech, which is exactly what a fan or traffic
        # looks like. Voiced frames are excluded so speech never raises the bar.
        if not is_voiced:
            self._noise_ema += self._noise_alpha * (rms - self._noise_ema)

        latency_ms = (time.perf_counter() - t0) * 1000

        if is_voiced and not speaker_gated:
            return self._handle_voiced(pcm16_bytes, rms, latency_ms)
        else:
            return self._handle_silent(pcm16_bytes, rms, latency_ms)

    def reset(self) -> None:
        self._in_speech          = False
        self._consecutive_voiced = 0
        self._speech_frames      = 0
        self._silence_frames     = 0
        self._pause_hinted       = False
        self._eou_extension      = 0
        self._speech_pcm         = bytearray()
        self._utt_rms_sum        = 0.0
        self._utt_rms_count      = 0
        self._onset_buffer.clear()

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def energy_threshold(self) -> float:
        """The RMS a frame must clear right now to count as possible speech.

        Rides the ambient EMA between the absolute floor and the cap. Survives
        `reset()` deliberately: the room is still the same room between
        utterances.
        """
        return min(self._noise_cap, max(self._min_rms, self._noise_ema * self._noise_factor))

    @property
    def ambient_rms(self) -> float:
        """Current ambient-noise estimate, for diagnostics."""
        return self._noise_ema

    @property
    def speaker_rms(self) -> float:
        """Tracked level of the customer's own speech, for diagnostics."""
        return self._speaker_ema

    @property
    def speaker_gate(self) -> float:
        """Extra RMS an onset must reach once the customer's level is known.

        Zero (inactive) until the first confirmed utterance and whenever the
        focus factor is 0. Survives `reset()` deliberately: the customer is
        still the same customer between utterances.
        """
        factor = self._barge_in_focus_factor if self._agent_speaking else self._speaker_focus_factor
        if factor <= 0.0 or self._speaker_ema <= 0.0:
            return 0.0
        return min(self._noise_cap, self._speaker_ema * factor)

    def _update_speaker_level(self) -> None:
        """Fold the finished utterance's mean voiced RMS into the estimate.

        Called only for confirmed utterances (EOU) — aborted
        onsets never teach the tracker, so background noise cannot become the
        speaker the processor focuses on.
        """
        if not self._utt_rms_count:
            return
        mean = self._utt_rms_sum / self._utt_rms_count
        # Kept for the turn's cue signals: this utterance against the level
        # the tracker held *before* it — loudness relative to the caller's
        # own norm, not to a fixed threshold.
        self.last_utterance_rms = mean
        self.last_speaker_rms_before = self._speaker_ema
        if self._speaker_ema <= 0.0:
            self._speaker_ema = mean
        else:
            self._speaker_ema += self._speaker_blend * (mean - self._speaker_ema)

    @property
    def speech_so_far(self) -> bytes:
        """The current utterance's PCM up to now (pre-roll included), or b""
        outside speech. A streaming STT opened at onset seeds itself with this
        so the first syllable is not lost to the onset-confirmation frames."""
        return bytes(self._speech_pcm) if self._in_speech else b""

    def commit(self) -> Optional[bytes]:
        """End the utterance now, without waiting out the silence window.

        Called when the transcript taken at the pause already reads as a
        complete answer. Returns the utterance PCM exactly as an
        END_OF_UTTERANCE would have, or None when there is nothing committable
        (not in speech, or too short to be a real utterance).
        """
        if not self._in_speech or self._speech_frames < self._min_speech_frames:
            return None
        utterance = bytes(self._speech_pcm)
        logger.info(f"[VAD] Early commit: {self._speech_frames} speech frames, {self._silence_frames} silence frames")
        self._update_speaker_level()
        self.reset()
        return utterance

    @property
    def silence_ms_so_far(self) -> float:
        """How long the speaker has been silent in the utterance in progress —
        latency the user is already feeling when a turn commits early."""
        return self._silence_frames * FRAME_DURATION_MS

    @classmethod
    def from_defaults(cls, *, classifier: Optional[FrameClassifier] = None) -> "VADProcessor":
        """The pipeline's VAD, from cascadevoice.defaults.

        Every millisecond-to-frame conversion lives here, so nothing else can
        drift from it.
        """
        from cascadevoice import defaults as d

        def frames(ms: float, floor: int = 1) -> int:
            return max(floor, round(ms / FRAME_DURATION_MS))

        if classifier is None:
            classifier = create_classifier(
                "silero", aggressiveness=d.VAD_WEBRTC_AGGRESSIVENESS,
                threshold=d.VAD_SILERO_THRESHOLD, release=d.VAD_SILERO_RELEASE,
            )
        return cls(
            min_rms=d.VAD_MIN_RMS,
            onset_frames=frames(d.VAD_ONSET_MS),
            eou_silence_frames=frames(d.EOU_SILENCE_MS),
            min_speech_frames=frames(d.VAD_MIN_SPEECH_MS),
            pre_roll_frames=frames(d.VAD_PRE_ROLL_MS, floor=0),
            barge_in_onset_frames=frames(d.VAD_BARGE_IN_ONSET_MS),
            # A time constant is what a person can reason about; the per-frame
            # weight it implies is not.
            noise_alpha=min(1.0, FRAME_DURATION_MS / max(FRAME_DURATION_MS, d.VAD_NOISE_ADAPT_MS)),
            noise_factor=d.VAD_NOISE_GATE_FACTOR,
            noise_cap=d.VAD_NOISE_CAP_RMS,
            speaker_focus_factor=d.SPEAKER_FOCUS_FACTOR,
            barge_in_focus_factor=d.BARGE_IN_FOCUS_FACTOR,
            speaker_blend=d.VAD_SPEAKER_BLEND,
            speaker_decay_per_frame=math.exp(-FRAME_DURATION_MS / (d.VAD_SPEAKER_DECAY_S * 1000.0)),
            classifier=classifier,
        )

    def extend_current_eou(self, extra_frames: int) -> None:
        """Give the current utterance more silence before the endpoint fires.

        Used when the pause-time transcript trails off mid-thought. Cleared on
        reset, so it applies to this utterance only.
        """
        self._eou_extension = max(self._eou_extension, extra_frames)

    def set_agent_speaking(self, speaking: bool) -> None:
        """Tell the VAD whether the agent's own voice may be in the mic."""
        self._agent_speaking = speaking

    @property
    def _required_onset_frames(self) -> int:
        return self._barge_in_onset_frames if self._agent_speaking else self._onset_frames

    # ── Internal Handlers ──────────────────────────────────────────────────────

    def _handle_voiced(self, frame: bytes, rms: float, latency_ms: float) -> VADResult:
        self._silence_frames = 0
        self._pause_hinted = False
        self._consecutive_voiced += 1
        # Accumulate toward this utterance's mean level; folded into the
        # speaker estimate only if the utterance is confirmed.
        self._utt_rms_sum += rms
        self._utt_rms_count += 1

        if not self._in_speech:
            self._onset_buffer.append(frame)

            # Require enough consecutive voiced frames before confirming speech start
            if self._consecutive_voiced >= self._required_onset_frames:
                self._in_speech = True
                self._speech_frames = len(self._onset_buffer)
                self._speech_pcm = bytearray()

                # Flush pre-roll ring buffer
                for pre_frame in self._pre_roll:
                    self._speech_pcm.extend(pre_frame)
                self._pre_roll.clear()

                # Flush onset buffer
                for onset_frame in self._onset_buffer:
                    self._speech_pcm.extend(onset_frame)
                self._onset_buffer.clear()

                logger.debug(f"[VAD] Confirmed SPEECH_START (RMS: {rms:.0f}, buffer: {len(self._speech_pcm)}B)")
                return VADResult(
                    event=VADEvent.SPEECH_START,
                    is_voiced=True,
                    rms_energy=rms,
                    silence_frames=0,
                    speech_frames=self._speech_frames,
                    vad_latency_ms=latency_ms,
                )
            else:
                # Still debouncing — do not trigger SPEECH_START yet
                return VADResult(
                    event=VADEvent.SILENCE,
                    is_voiced=True,
                    rms_energy=rms,
                    silence_frames=0,
                    speech_frames=0,
                    vad_latency_ms=latency_ms,
                )

        # Already in speech
        self._speech_pcm.extend(frame)
        self._speech_frames += 1
        return VADResult(
            event=VADEvent.SPEECH,
            is_voiced=True,
            rms_energy=rms,
            silence_frames=0,
            speech_frames=self._speech_frames,
            vad_latency_ms=latency_ms,
        )

    def _handle_silent(self, frame: bytes, rms: float, latency_ms: float) -> VADResult:
        self._consecutive_voiced = 0
        self._onset_buffer.clear()

        if not self._in_speech:
            # A fizzled debounce must not pollute the next utterance's mean.
            self._utt_rms_sum = 0.0
            self._utt_rms_count = 0
            # The speaker estimate ages between utterances, so a customer who
            # moved away from the mic (or sustained background babble, which is
            # routed here by the focus gate) is never locked out for good.
            self._speaker_ema *= self._speaker_decay
            # Maintain sliding pre-roll ring buffer
            self._pre_roll.append(frame)
            if len(self._pre_roll) > self._pre_roll_frames:
                self._pre_roll.pop(0)
            return VADResult(
                event=VADEvent.SILENCE,
                is_voiced=False,
                rms_energy=rms,
                silence_frames=self._silence_frames,
                speech_frames=0,
                vad_latency_ms=latency_ms,
            )

        # In speech — accumulate trailing silence
        self._speech_pcm.extend(frame)
        self._silence_frames += 1

        # Halfway through the silence window: probably done, not yet certain.
        if (
            not self._pause_hinted
            and self._silence_frames >= self._speculative_frames
            and self._silence_frames < self._eou_silence_frames
            and self._speech_frames >= self._min_speech_frames
        ):
            self._pause_hinted = True
            return VADResult(
                event=VADEvent.PAUSE_HINT,
                is_voiced=False,
                rms_energy=rms,
                silence_frames=self._silence_frames,
                speech_frames=self._speech_frames,
                speech_pcm=bytes(self._speech_pcm),
                vad_latency_ms=latency_ms,
            )

        if self._silence_frames >= self._eou_silence_frames + self._eou_extension:
            if self._speech_frames >= self._min_speech_frames:
                utterance_pcm = bytes(self._speech_pcm)
                # Captured before reset() zeroes them — the VADResult below
                # must report what this utterance actually had, not the
                # fresh-utterance state reset() leaves behind.
                final_speech_frames = self._speech_frames
                final_silence_frames = self._silence_frames
                logger.info(
                    f"[VAD] Confirmed EOU: {final_speech_frames} speech frames, "
                    f"{final_silence_frames} silence frames, "
                    f"{len(utterance_pcm)} PCM bytes"
                )
                self._update_speaker_level()
                self.reset()
                return VADResult(
                    event=VADEvent.END_OF_UTTERANCE,
                    is_voiced=False,
                    rms_energy=rms,
                    silence_frames=final_silence_frames,
                    speech_frames=final_speech_frames,
                    speech_pcm=utterance_pcm,
                    vad_latency_ms=latency_ms,
                )
            else:
                logger.debug(f"[VAD] Discarded noise spike ({self._speech_frames} frames < min {self._min_speech_frames})")
                self.reset()
                # SPEECH_START promised an END_OF_UTTERANCE; this onset fizzled
                # instead, and the caller needs a distinct signal to undo
                # whatever it opened (an activity, an ear).
                return VADResult(
                    event=VADEvent.SPEECH_ABORTED,
                    is_voiced=False,
                    rms_energy=rms,
                    silence_frames=0,
                    speech_frames=0,
                    vad_latency_ms=latency_ms,
                )

        return VADResult(
            event=VADEvent.SILENCE,
            is_voiced=False,
            rms_energy=rms,
            silence_frames=self._silence_frames,
            speech_frames=self._speech_frames,
            vad_latency_ms=latency_ms,
        )
