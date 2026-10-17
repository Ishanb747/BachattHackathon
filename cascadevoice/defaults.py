"""The one pipeline's fixed configuration, and where the keys come from.

Every number here was tuned on live calls in the system this was distilled
from; the comments say why each one is what it is. They are constants, not
settings: change one by editing it here, deliberately, with a reason.

Keys are read once, from ``.env`` at the project root (or the process
environment): ``OPENAI_API_KEY`` and ``ELEVENLABS_API_KEY``. A missing key is
a startup error naming it — never a call that half-works.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ── The pipeline ─────────────────────────────────────────────────────────────
LLM_MODEL = "gpt-4o"
# Replies are kept short by the prompt; this cap only has to be high enough
# that it never truncates a sentence mid-word.
LLM_MAX_OUTPUT_TOKENS = 1024
LLM_TEMPERATURE = 0.3
# Exchanges of history sent each turn. A tight window keeps the prompt prefix
# cacheable and the first token fast.
LLM_HISTORY_TURNS = 8
# Rounds of tool calls one turn may take (call → result → speak).
LLM_MAX_TOOL_ROUNDS = 3

# ElevenLabs Flash v2.5: the low-latency multilingual model (Hindi included),
# and the family that streams fastest.
TTS_MODEL = "eleven_flash_v2_5"
# Rachel — a premade voice present in every ElevenLabs account.
TTS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
TTS_SAMPLE_RATE = 22050
TTS_VOICE_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True}
# How many sentences may be in synthesis at once. Playout stays in order.
TTS_PIPELINE_DEPTH = 3
# Cut the reply's opening unit at a clause boundary once it is this long, so
# speech starts without waiting for the full stop.
EAGER_FIRST_CHUNK_MIN_CHARS = 28
# A completed sentence shorter than this is spoken with the next one, so the
# voice does not reset its pitch for "Okay." / "Sure." every few words. Never
# applied to the opening unit — that one is the user's wait.
TTS_MIN_UNIT_CHARS = 20
# Fixed lines (the greeting, hook replies) are cached by text + voice + rate.
# Free-form model sentences are said once and never cached.
AUDIO_CACHE_MAX_ITEMS = 256

# Scribe v2 Realtime: one stream per utterance, opened at speech onset and
# committed at end of utterance. The commit (125 ms measured, against 512 ms
# for batch on the same audio) is what the turn waits on. Connect runs while
# the user is still talking. Past the commit budget, batch is faster anyway.
SCRIBE_CONNECT_TIMEOUT_S = 3.0
SCRIBE_COMMIT_TIMEOUT_S = 2.0
# The fallback when the realtime stream fails: batch Scribe on the utterance.
SCRIBE_BATCH_MODEL = "scribe_v2"
SCRIBE_BATCH_TIMEOUT_S = 8.0

# The call's starting language. It then follows the words the user speaks
# (Devanagari or Hinglish switch it; an STT label alone never does).
LANGUAGE = "en-IN"

# ── Endpointing ───────────────────────────────────────────────────────────────
# Silence that ends a turn — the knob that decides whether a user gets cut off
# mid-sentence. A pause while hunting for a word runs 300-600 ms; 220 was
# chosen for first-word latency, and the pause-hint extension below rescues
# the mid-thought pauses it would otherwise cut.
EOU_SILENCE_MS = 220
# The pause hint fires halfway through that window: the Scribe partial is
# judged there. A complete sentence commits the turn early; one that trails
# off ("Uh, it was completed but") gets this much more silence, once.
ENDPOINT_EXTENSION_MS = 400
# Commit early on a complete-looking partial. The cost: Scribe punctuates every
# clause, so long narration can be cut at a full stop. False = the silence
# timer alone decides (the extension still applies).
EARLY_COMMIT = True

# ── What counts as speech at all ──────────────────────────────────────────────
# A spoken "Yes." is 150-250 ms; a floor above that swallows the most
# important answers. Below ~120 ms, desk taps become turns.
VAD_MIN_SPEECH_MS = 140
# Speech this long confirms someone started talking.
VAD_ONSET_MS = 60
# Stricter while the agent is audible, where a false trigger cuts it off:
# echo cancellation is imperfect on speakerphones.
VAD_BARGE_IN_ONSET_MS = 100
# Audio kept from before speech was confirmed. Too low and "four" arrives as "or".
VAD_PRE_ROLL_MS = 350
# Quiet-room loudness floor, 0-32767. Normal speech is 800-6000.
VAD_MIN_RMS = 450.0
# Never demand more than this, or a loud room goes permanently deaf.
VAD_NOISE_CAP_RMS = 6000.0
VAD_NOISE_ADAPT_MS = 400
# How far above ambient a frame must sit. Lowered 2.0 -> 1.5 after quiet
# single-digit answers over ~600 RMS background never started an onset; 1.0
# would treat half of ambient's own fluctuation as speech.
VAD_NOISE_GATE_FACTOR = 1.5
# Ignore background voices quieter than this fraction of the user's own level
# (the user is near-field, a TV is not); stricter while the agent speaks.
SPEAKER_FOCUS_FACTOR = 0.35
BARGE_IN_FOCUS_FACTOR = 0.5
VAD_SPEAKER_BLEND = 0.5
# A user who moved away from the mic is forgiven after about this long.
VAD_SPEAKER_DECAY_S = 60.0
# Silero separates speech from fans/traffic/TV far better than webrtcvad's
# formant heuristic; webrtcvad is the automatic fallback if it cannot load.
VAD_SILERO_THRESHOLD = 0.5
VAD_SILERO_RELEASE = 0.35   # hysteresis once triggered — must be < threshold
VAD_WEBRTC_AGGRESSIVENESS = 3

# ── Barge-in ──────────────────────────────────────────────────────────────────
# Ignored for this long after the agent starts a run of speech, so a
# throat-clear or a lingering "hello" over its first syllable cannot cut it.
BARGE_IN_GRACE_S = 0.35
# Speech sustained this long over the agent interrupts at once — real
# interruptions run long, grunts and echo do not. Lowered 900 -> 600 -> 450
# on "barge-in takes too long" reports; coughs and horns rarely reach it.
# Anything shorter waits for end of utterance, where the transcript decides.
BARGE_IN_HARD_MS = 450
# A transcript this short (words) that is not a complete answer is a
# backchannel ("haan", "hmm"), not an interruption: the agent keeps talking.
BARGE_IN_MAX_BACKCHANNEL_WORDS = 2
# A complete-looking answer interrupts only when the agent is within this many
# seconds of finishing its line — on the question's tail. Raised 1.5 -> 3.5 ->
# 6.0 on "single words don't interrupt".
BARGE_IN_TAIL_WINDOW_S = 6.0
# The client ramps its gain to zero over this long instead of a hard mute.
BARGE_IN_FADE_MS = 90
# Between the server writing audio and the client rendering it, so the
# barge-in window does not close while the user can still hear the agent.
PLAYBACK_TAIL_PADDING_S = 0.25


# ── Keys ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Keys:
    openai: str
    elevenlabs: str


class MissingKeyError(RuntimeError):
    pass


def _read_env_file(path: Path) -> dict:
    values: dict = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def load_keys(env_file: Path | None = None) -> Keys:
    """Read both keys once. The process environment wins over ``.env``."""
    file_values = _read_env_file(env_file or PROJECT_ROOT / ".env")
    found = {name: os.environ.get(name) or file_values.get(name, "")
             for name in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY")}
    missing = [name for name, value in found.items() if not value]
    if missing:
        raise MissingKeyError(
            f"Missing {' and '.join(missing)} — add {'them' if len(missing) > 1 else 'it'} to "
            f"{env_file or PROJECT_ROOT / '.env'} (see .env.example)."
        )
    return Keys(openai=found["OPENAI_API_KEY"], elevenlabs=found["ELEVENLABS_API_KEY"])
