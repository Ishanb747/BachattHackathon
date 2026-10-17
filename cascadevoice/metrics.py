"""Per-turn latency: wall-clock stamps for each stage of one turn."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from cascadevoice.events import MetricsEvent

logger = logging.getLogger(__name__)


def _ms(later: float, earlier: float) -> float:
    return round((later - earlier) * 1000, 1) if later and earlier and later >= earlier else 0.0


@dataclass
class TurnMetrics:
    t_eou: float = 0.0             # end of utterance (the VAD, or an early commit)
    # How long the user had already been silent when the turn committed. The
    # turn clock starts at the commit, so without this the endpoint wait —
    # 220 ms on a normal turn — sits outside every number while being time
    # the user spends waiting like any other.
    endpoint_wait_ms: float = 0.0
    t_stt_done: float = 0.0        # transcript in hand
    t_llm_first_token: float = 0.0
    t_llm_first_sentence: float = 0.0
    t_tts_first: float = 0.0       # first TTS bytes of the first sentence
    t_audio_out: float = 0.0       # those bytes handed to the transport
    stt_source: str = ""
    cache_hit: bool = False
    hooked: bool = False

    def event(self) -> MetricsEvent:
        total = _ms(self.t_audio_out, self.t_eou)
        return MetricsEvent(
            endpoint_wait_ms=round(self.endpoint_wait_ms, 1),
            stt_ms=_ms(self.t_stt_done, self.t_eou),
            llm_first_token_ms=_ms(self.t_llm_first_token, self.t_stt_done),
            llm_first_sentence_ms=_ms(self.t_llm_first_sentence, self.t_stt_done),
            tts_first_audio_ms=_ms(self.t_tts_first, self.t_llm_first_sentence),
            total_ms=total,
            true_e2e_ms=round(total + self.endpoint_wait_ms, 1) if total else 0.0,
            stt_source=self.stt_source, cache_hit=self.cache_hit, hooked=self.hooked,
        )

    def log(self) -> MetricsEvent:
        e = self.event()
        logger.info(
            f"[Turn] stt {e.stt_ms:.0f} · llm 1st token {e.llm_first_token_ms:.0f} · "
            f"1st sentence {e.llm_first_sentence_ms:.0f} · tts 1st audio {e.tts_first_audio_ms:.0f} · "
            f"EOU→audio {e.total_ms:.0f} ms (last words→audio {e.true_e2e_ms:.0f}, stt={e.stt_source}"
            + (", cache hit" if e.cache_hit else "") + ")"
        )
        return e
