"""Streaming text helpers: sentence segmentation and transcript filtering.

Emitting the reply per sentence rather than per turn is what lets synthesis
start while the model is still generating.
"""

from __future__ import annotations

import re
from typing import Callable, Iterator, Optional

# Sentence terminators, including the Devanagari danda (।) and double danda (॥).
SENTENCE_RE = re.compile(r"([.?!।॥]+(?:\s+|\n+|$))")
ABBREVIATION_RE = re.compile(r"^(Mr|Mrs|Ms|Dr|e\.g|i\.e)\.$", re.IGNORECASE)

# Clause boundaries the eager splitter may cut on — a comma or dash reads as a
# natural pause when spoken, so an early cut here is not audible as a cut.
CLAUSE_RE = re.compile(r"[,;:](?:\s+)|\s+[—–-]\s+")

# Keep Indic combining marks (matras, chandrabindu): Python's \w excludes
# them, and stripping them shrank "हाँ" — a bare Hindi yes — below the noise
# length threshold.
_PUNCTUATION_RE = re.compile(r"[^\w\s\u0900-\u0D7F]")
# STT engines emit these for pure silence or a dial tone.
_NOISE_TRANSCRIPTS = frozenset({"00:00", "00", "--", "0"})

# Pure interjections: a hum or a throat-clear the STT dressed up as a word
# ("M.M.", "Oh.", "Ah."). Answering one costs a wasted turn — an ack plus a
# re-asked question — so they are treated like silence instead.
_INTERJECTIONS = frozenset({
    "oh", "ah", "uh", "um", "umm", "uhh", "mm", "mmm", "m", "hmm", "hm",
    "huh", "eh", "er", "erm", "mhm", "हम्म", "हम्म्म",
})

# Backchannel acknowledgments — a user confirming they are listening, not
# answering or interrupting. Heard over the agent mid-question ("haan",
# "ठीक है") these must not be mistaken for a real interruption. Romanised and
# Devanagari forms both appear depending on which STT engine is active.
_BACKCHANNEL_WORDS = frozenset({
    "haan", "han", "haa", "ha", "ji", "achha", "accha", "acha", "theek", "thik", "hai",
    "ok", "okay", "yes", "yeah", "yep", "right", "sure", "alright",
    "हाँ", "हां", "जी", "अच्छा", "ठीक", "है",
})


class SentenceBuffer:
    """Accumulates streamed LLM tokens and yields speakable units.

    Emitting per sentence rather than per turn is what lets synthesis start
    while the model is still generating.

    The *first* unit of a reply is the one the user waits on, so it may also
    be cut at a clause boundary once it is long enough to sound natural
    (``eager_first``). That trade — a slightly shorter opening phrase for an
    earlier first word — only pays when the text has to be synthesized anyway,
    so ``is_cached_prefix`` lets the caller veto the cut while the text so far
    still matches the start of an already-cached line.
    """

    def __init__(
        self,
        *,
        eager_first: bool = False,
        min_eager_chars: int = 28,
        min_unit_chars: int = 0,
        is_cached_prefix: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._buffer = ""
        self._eager_first = eager_first
        self._min_eager_chars = min_eager_chars
        self._min_unit_chars = min_unit_chars
        self._is_cached_prefix = is_cached_prefix
        self._emitted = 0
        # A completed sentence too short to speak on its own, waiting to be
        # joined to the next one (see min_unit_chars).
        self._held = ""

    def push(self, chunk: str) -> Iterator[str]:
        """Add a token chunk and yield every unit it completed."""
        self._buffer += chunk

        while True:
            sentence = self._take_sentence()
            if sentence is None:
                break
            if not sentence:
                continue
            sentence = self._join_held(sentence)
            if self._should_hold(sentence):
                self._held = sentence
                continue
            self._emitted += 1
            yield sentence

        clause = self._take_eager_clause()
        if clause:
            self._emitted += 1
            yield clause

    def flush(self) -> str:
        """Return whatever text never terminated in punctuation."""
        leftover = self._join_held(self._buffer.strip())
        self._buffer = ""
        if leftover:
            self._emitted += 1
        return leftover

    def _join_held(self, text: str) -> str:
        if not self._held:
            return text
        held, self._held = self._held, ""
        return f"{held} {text}".strip() if text else held

    def _should_hold(self, sentence: str) -> bool:
        """A short sentence after the opener is spoken with the next one, so
        the voice does not restart its intonation for a three-word "Sure."

        The opener is exempt: it is what the user is waiting on. A short
        sentence that already matches a cached line is also spoken as-is —
        joining it would trade a 0 ms hit for a synthesis round trip.
        """
        if self._min_unit_chars <= 0 or not self._emitted:
            return False
        if len(sentence) >= self._min_unit_chars:
            return False
        if self._is_cached_prefix is not None and self._is_cached_prefix(sentence):
            return False
        return True

    # ── Internals ─────────────────────────────────────────────────────────────

    def _take_sentence(self) -> Optional[str]:
        """Pop the next complete sentence. None when there isn't one yet; the
        empty string when a match was consumed but is not speakable."""
        start = 0
        while True:
            match = SENTENCE_RE.search(self._buffer, start)
            if not match:
                return None
            end = match.end()
            sentence = self._buffer[:end].strip()
            words = sentence.split()
            # An abbreviation's period ("Dr.", "e.g.") is not a sentence end:
            # look past it. (Treating it as an unspeakable "sentence" used to
            # consume it, and "Dr. Rao will call." was spoken "Rao will call.")
            if words and ABBREVIATION_RE.match(words[-1]):
                start = end
                continue
            self._buffer = self._buffer[end:]
            # A lone terminator is not a sentence.
            return "" if len(sentence) <= 1 else sentence

    def _take_eager_clause(self) -> Optional[str]:
        """Pop an opening clause when waiting for the full stop costs more than
        the shorter phrase does."""
        if not self._eager_first or self._emitted:
            return None

        pending = self._buffer.lstrip()
        if len(pending) < self._min_eager_chars:
            return None

        # Holding on will land a 0 ms cache hit — worth more than cutting early.
        if self._is_cached_prefix is not None and self._is_cached_prefix(pending):
            return None

        match = CLAUSE_RE.search(pending, self._min_eager_chars)
        if not match:
            return None

        clause = pending[: match.end()].strip()
        self._buffer = pending[match.end():]
        return clause


def is_noise_transcript(transcript: str) -> bool:
    """True for STT output that is silence artefacts rather than speech.

    Single digits survive: "3" is a valid answer to "how many?".
    """
    if not transcript or transcript in _NOISE_TRANSCRIPTS:
        return True
    stripped = _PUNCTUATION_RE.sub("", transcript).strip()
    if len(stripped) < 2 and not stripped.isdigit():
        return True
    words = stripped.lower().split()
    return bool(words) and all(word in _INTERJECTIONS for word in words)


def is_backchannel(transcript: str) -> bool:
    """True when the whole utterance is acknowledgment words — "haan", "ji",
    "theek hai", "ok" — and nothing else, in either script.

    Mirrors :func:`is_noise_transcript`'s interjection check: every word must
    be a backchannel word, so a real sentence that happens to end in "hai"
    (very common — "is/am") is untouched.
    """
    stripped = _PUNCTUATION_RE.sub("", transcript or "").strip()
    if not stripped:
        return False
    words = stripped.lower().split()
    return bool(words) and all(word in _BACKCHANNEL_WORDS for word in words)
