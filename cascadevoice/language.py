"""Zero-latency spoken-language identification from a transcript.

Unicode script blocks plus romanised-Hindi markers — no network, so it can sit
on a turn's critical path. The session uses it to let the call's language
follow the user: the *words* decide, never an STT vendor's label (a one-word
English answer labelled Hindi once flipped a whole call to Hindi mid-way).

English and anything unrecognised come back as ``en-IN``: this layer grew up
on Indian phone lines. Pass ``english=`` to name it differently.
"""

from __future__ import annotations

import re
from typing import Dict

DEFAULT_LANGUAGE = "en-IN"

# Indic Unicode blocks, mapped to BCP-47.
_SCRIPT_RANGES: Dict[str, str] = {
    "hi-IN": r"[ऀ-ॿ]",   # Devanagari
    "bn-IN": r"[ঀ-৿]",   # Bengali
    "pa-IN": r"[਀-੿]",   # Gurmukhi
    "gu-IN": r"[઀-૿]",   # Gujarati
    "od-IN": r"[଀-୿]",   # Odia
    "ta-IN": r"[஀-௿]",   # Tamil
    "te-IN": r"[ఀ-౿]",   # Telugu
    "kn-IN": r"[ಀ-೿]",   # Kannada
    "ml-IN": r"[ഀ-ൿ]",   # Malayalam
}

# Romanised Hindi markers. Short particles ("ha", "ho") also occur inside
# English words, which is why matching is on whole words only.
_HINGLISH_MARKERS = frozenset({
    "haan", "han", "haa", "bol", "boli", "bolo", "boliye",
    "nahi", "nahin",
    "accha", "acha", "theek", "thik", "shukriya", "dhanyawad",
    "namaste", "kripya", "madad",
    "kaise", "kya", "kyun", "kab", "kahan", "kaha",
    "mera", "meri", "mere", "hum", "aap", "aapka", "aapki", "apna",
    "pani", "kharaab", "kharab", "chal", "arre", "yaar", "matlab",
    "bhai", "ji", "bataiye", "badhiya", "sahi",
    "karo", "kariye", "kijiye", "baat", "sunai",
    "raha", "rahi", "gaya", "gayi", "bataye",
    "ha", "ho", "hai", "hain", "tha", "thi", "de",
})

_WORD_RE = re.compile(r"\b\w+\b")
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)

# Share of a transcript's letters that must be in one Indic script before the
# reply switches to it. A single transliterated proper noun (STT engines write
# "Rahul" as "राहुल" when asked for Hindi) is not the user changing language.
_SCRIPT_SHARE_THRESHOLD = 0.35


def detect_local(text: str, *, english: str = DEFAULT_LANGUAGE) -> str:
    """Language of `text` from script blocks and Hinglish markers."""
    if not text:
        return english
    letters = len(_LETTER_RE.findall(text))
    if letters:
        counts = {lang: len(re.findall(pattern, text)) for lang, pattern in _SCRIPT_RANGES.items()}
        best_language, best_count = max(counts.items(), key=lambda item: item[1])
        if best_count / letters >= _SCRIPT_SHARE_THRESHOLD:
            return best_language
    words = set(_WORD_RE.findall(text.lower()))
    return "hi-IN" if words & _HINGLISH_MARKERS else english
