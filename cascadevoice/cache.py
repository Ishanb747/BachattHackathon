"""A small in-memory cache for fixed lines (the greeting, hook replies).

Keyed by text + voice + sample rate, so switching voices or rates can never
replay the wrong audio. Free-form model sentences are said once and never
again, so they are not cached — that only grows the store with no hits.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Optional

from cascadevoice import defaults as d

_SPACES = re.compile(r"\s+")


def _key(text: str, voice: str, rate: int) -> tuple:
    # Whitespace varies between two renderings of the same line; normalising
    # it keeps hits without risking cross-sentence collisions.
    return (_SPACES.sub(" ", text.strip()).lower(), voice, rate)


class AudioCache:
    def __init__(self, max_items: int = d.AUDIO_CACHE_MAX_ITEMS) -> None:
        self._items: "OrderedDict[tuple, bytes]" = OrderedDict()
        self._max = max_items

    def get(self, text: str, voice: str, rate: int) -> Optional[bytes]:
        key = _key(text, voice, rate)
        pcm = self._items.get(key)
        if pcm is not None:
            self._items.move_to_end(key)
        return pcm

    def put(self, text: str, voice: str, rate: int, pcm: bytes) -> None:
        if not pcm:
            return
        self._items[_key(text, voice, rate)] = pcm
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def has_prefix(self, partial: str, voice: str, rate: int) -> bool:
        """Whether some cached line starts with `partial` — the sentence
        chunker holds off an eager cut while the reply may still land a hit."""
        start = _SPACES.sub(" ", partial.strip()).lower()
        return bool(start) and any(k[0].startswith(start) and k[1] == voice and k[2] == rate for k in self._items)


# Shared across sessions: the greeting is the same line on every call.
audio_cache = AudioCache()
