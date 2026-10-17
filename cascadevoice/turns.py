"""Is the sentence finished? Judged from the words heard up to a pause.

A fixed silence window is wrong in both directions: it cuts off a user who
pauses mid-thought ("I think the…"), and makes one who gave a complete answer
wait out the timer. The streaming transcript at the VAD's pause hint is the
evidence needed to do better: COMPLETE commits the turn early, INCOMPLETE
earns one silence extension per utterance (``ENDPOINT_EXTENSION_MS``) —
committing on "Uh, it was completed but" once split a complaint from its own
first half. The barge-in gate reads the same verdict.

``assess`` is the whole interface, so a trained turn-detection model is a
swap, not an architecture change.
"""

from __future__ import annotations

import re
from enum import Enum, auto


class Verdict(Enum):
    COMPLETE = auto()     # the turn is over
    INCOMPLETE = auto()   # mid-thought: extend the silence window
    UNKNOWN = auto()      # no evidence either way: let the timer decide


# Trailing words that mean the sentence is still coming: conjunctions,
# prepositions, articles, mid-phrase fillers, English and Hinglish — plus a
# subject, modal or hedge with nothing after it. "Mmm, I would" and "Yeah,
# much" were both once judged finished while the user was mid-sentence.
# "can"/"will" are left out: "yes I can" is complete.
_TRAILING_CONNECTIVE = frozenset({
    "and", "but", "or", "so", "because", "then", "also", "like", "umm", "uh",
    "the", "a", "an", "my", "your", "our", "very", "really", "quite", "was", "is", "it's",
    "about", "to", "for", "with", "of", "that", "which", "in", "on", "at", "by", "from",
    "aur", "lekin", "kyunki", "toh", "matlab", "woh", "mera", "meri", "bahut", "thoda",
    "ke", "ki", "ka", "mein", "se", "par",
    "i", "i'd", "i'll", "i'm", "we", "we'd", "would", "could", "should", "might", "may",
    "think", "guess", "say", "mean", "probably", "maybe", "actually", "honestly", "basically",
    "much", "many", "more", "most", "pretty", "kind", "sort",
    "mmm", "hmm", "hm", "मैं", "हम", "शायद", "मुझे", "लगता", "बस", "थोड़ा",
})

_TERMINAL_RE = re.compile(r"[.?!।॥]\s*$")
# \w skips combining marks, so a Devanagari matra ("लगता" = लगत + ा) split a
# word in two and no Hindi connective ever matched. Keep the block whole.
_WORD_RE = re.compile(r"[\w'ऀ-ॿ]+", re.UNICODE)
# Non-speech tags some transcribers emit inline: "(laughs) four" is a four.
_AUDIO_EVENT_RE = re.compile(
    r"\(\s*(?:laugh\w*|chuckles?|sigh\w*|cough\w*|clears? throat|breath\w*|inhales?|exhales?|"
    r"background \w+|music|noise|inaudible|unintelligible|silence)[^)]*\)",
    re.IGNORECASE,
)


def assess(transcript: str) -> Verdict:
    """Judge whether `transcript`, heard up to a pause, is a finished turn."""
    text = _AUDIO_EVENT_RE.sub(" ", transcript or "").strip()
    words = _WORD_RE.findall(text.lower())
    if not words:
        return Verdict.UNKNOWN
    # Explicit "more is coming" marks beat everything: a comma or an ellipsis
    # is the speaker trailing off ("it was completed but…").
    if text.endswith((",", "…", "...")):
        return Verdict.INCOMPLETE
    # A question back is finished whatever its last word — "what do you mean
    # by that?" ends in a connective and is complete.
    if text.endswith("?"):
        return Verdict.COMPLETE
    # A trailing connective only means "more is coming" with no full stop
    # after it. "Yes it is." ends on a listed word and is plainly finished.
    terminal = bool(_TERMINAL_RE.search(text))
    if not terminal and words[-1] in _TRAILING_CONNECTIVE:
        return Verdict.INCOMPLETE
    # A punctuated sentence of reasonable length is a finished thought. STT
    # engines that do not punctuate simply never take this branch.
    if terminal and len(words) >= 3:
        return Verdict.COMPLETE
    return Verdict.UNKNOWN


def strip_events(transcript: str) -> str:
    """The transcript without non-speech tags ("(laughs)"), whitespace tidied."""
    return " ".join(_AUDIO_EVENT_RE.sub(" ", transcript or "").split())


def is_incomplete(transcript: str) -> bool:
    return assess(transcript) is Verdict.INCOMPLETE
