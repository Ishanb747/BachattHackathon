"""ElevenLabs: which host the key lives on, streaming TTS, and batch Scribe.

ElevenLabs runs separate "data residency" stacks. A key minted on one stack
is rejected by every other host with a 401, so the host has to follow the
key: the first use probes the stacks once and remembers the answer.
"""

from __future__ import annotations

import logging
import time
from typing import AsyncIterator, Dict, Optional, Tuple

import httpx

from cascadevoice import defaults as d
from cascadevoice.audio.codecs import pcm16_to_wav

logger = logging.getLogger(__name__)

REGION_HOSTS = {
    "global": "https://api.elevenlabs.io",
    "in": "https://api.in.residency.elevenlabs.io",
    "eu": "https://api.eu.residency.elevenlabs.io",
}
_RESIDENCY_MISMATCH = "data residency stack"
_regions: Dict[str, str] = {}   # api key -> region
_client: Optional[httpx.AsyncClient] = None

# ISO 639 codes Scribe reports, to the BCP-47 the session speaks.
_ISO_TO_CODE = {
    "eng": "en-IN", "en": "en-IN", "hin": "hi-IN", "hi": "hi-IN",
    "ben": "bn-IN", "bn": "bn-IN", "mar": "mr-IN", "mr": "mr-IN",
    "guj": "gu-IN", "gu": "gu-IN", "ori": "od-IN", "or": "od-IN",
    "tam": "ta-IN", "ta": "ta-IN", "tel": "te-IN", "te": "te-IN",
    "kan": "kn-IN", "kn": "kn-IN", "mal": "ml-IN", "ml": "ml-IN",
    "pan": "pa-IN", "pa": "pa-IN",
}


def to_bcp47(code: Optional[str], fallback: str) -> str:
    return _ISO_TO_CODE.get((code or "").strip().lower(), fallback)


def http() -> httpx.AsyncClient:
    """One pooled client for the process: a new one per request reopens TLS."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


def api_base(api_key: str) -> str:
    return REGION_HOSTS[_regions.get(api_key, "global")]


def ws_base(api_key: str) -> str:
    return api_base(api_key).replace("https://", "wss://", 1)


def is_residency_mismatch(status_code: int, body: str | bytes) -> bool:
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    return status_code == 401 and _RESIDENCY_MISMATCH in text


async def ensure_region(api_key: str) -> str:
    """Resolve the key's stack (once), without spending credits.

    Each host answers ``GET /v1/voices`` with a distinctive 401 for a foreign
    key, so the first host that does *not* say "data residency stack" is ours
    — whether it then lists voices or refuses for lack of the voices_read
    scope (a key without that scope is still a key on that stack).
    """
    if api_key in _regions:
        return _regions[api_key]
    for name, host in REGION_HOSTS.items():
        try:
            response = await http().get(f"{host}/v1/voices", headers={"xi-api-key": api_key}, timeout=8.0)
        except Exception as exc:
            logger.warning(f"[ElevenLabs] Region probe {name} failed: {exc!r}")
            continue
        if not is_residency_mismatch(response.status_code, response.text):
            _regions[api_key] = name
            if name != "global":
                logger.info(f"[ElevenLabs] Key belongs to the {name.upper()} data-residency stack — using {host}")
            return name
    return "global"


class ElevenLabsTTS:
    """Streamed synthesis: the first bytes of a sentence reach the user while
    the rest is still being synthesized."""

    name = "elevenlabs"

    def __init__(self, api_key: str, *, voice_id: str = d.TTS_VOICE_ID, model: str = d.TTS_MODEL,
                 sample_rate: int = d.TTS_SAMPLE_RATE) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.sample_rate = sample_rate

    def _payload(self, text: str, language: str) -> dict:
        payload: dict = {"text": text.strip(), "model_id": self.model, "voice_settings": dict(d.TTS_VOICE_SETTINGS)}
        if self.model in ("eleven_flash_v2_5", "eleven_turbo_v2_5") and language:
            # Only these models take a language_code; the others 400 on it.
            payload["language_code"] = language.split("-", 1)[0].lower()
        return payload

    async def open(self, text: str, *, language: str) -> Tuple[int, AsyncIterator[bytes]]:
        """Open the chunked stream and return (sample rate, PCM-16 chunks).

        The request is sent and its status checked *before* returning, so a
        rejection surfaces here — where the caller can fall back to one-shot
        synthesis — rather than as a silent empty stream later.
        """
        await ensure_region(self.api_key)
        client = http()
        request = client.build_request(
            "POST", f"{api_base(self.api_key)}/v1/text-to-speech/{self.voice_id}/stream",
            headers={"xi-api-key": self.api_key}, params={"output_format": f"pcm_{self.sample_rate}"},
            json=self._payload(text, language), timeout=12.0,
        )
        started = time.perf_counter()
        response = await client.send(request, stream=True)
        if response.status_code != 200:
            body = await response.aread()
            await response.aclose()
            if is_residency_mismatch(response.status_code, body):
                _regions.pop(self.api_key, None)   # the key moved stacks; re-probe next time
            raise RuntimeError(f"ElevenLabs TTS HTTP {response.status_code}: {body[:140]!r}")

        async def chunks() -> AsyncIterator[bytes]:
            # A PCM-16 sample split across two network chunks would click:
            # carry an odd trailing byte into the next chunk.
            remainder = b""
            first = True
            try:
                async for chunk in response.aiter_bytes():
                    chunk = remainder + chunk
                    remainder = b""
                    if len(chunk) % 2:
                        remainder, chunk = chunk[-1:], chunk[:-1]
                    if not chunk:
                        continue
                    if first:
                        logger.info(f"[TTS] first chunk in {(time.perf_counter() - started) * 1000:.0f} ms: {text[:40]!r}")
                        first = False
                    yield chunk
            finally:
                await response.aclose()

        return self.sample_rate, chunks()

    async def synthesize(self, text: str, *, language: str) -> Optional[bytes]:
        """One-shot PCM-16, the fallback when a stream cannot be opened."""
        await ensure_region(self.api_key)
        response = await http().post(
            f"{api_base(self.api_key)}/v1/text-to-speech/{self.voice_id}",
            headers={"xi-api-key": self.api_key}, params={"output_format": f"pcm_{self.sample_rate}"},
            json=self._payload(text, language), timeout=12.0,
        )
        if response.status_code != 200 or not response.content:
            logger.error(f"[TTS] HTTP {response.status_code}: {response.text[:140]}")
            return None
        pcm = response.content
        return pcm[: len(pcm) - (len(pcm) % 2)]


class ScribeBatch:
    """Batch Scribe: the fallback ear, on the buffered utterance, when the
    realtime stream fails. Slower (~0.5-0.9 s), never the first choice."""

    name = "elevenlabs-scribe-batch"

    def __init__(self, api_key: str, *, model: str = d.SCRIBE_BATCH_MODEL) -> None:
        self.api_key = api_key
        self.model = model

    async def transcribe(self, pcm16: bytes, *, language: str):
        from cascadevoice.ear.scribe import Transcription

        if len(pcm16) < 300:
            return None
        await ensure_region(self.api_key)
        started = time.perf_counter()
        response = await http().post(
            f"{api_base(self.api_key)}/v1/speech-to-text",
            headers={"xi-api-key": self.api_key},
            files={"file": ("utterance.wav", pcm16_to_wav(pcm16), "audio/wav")},
            data={"model_id": self.model, "tag_audio_events": "false", "diarize": "false"},
            timeout=d.SCRIBE_BATCH_TIMEOUT_S,
        )
        if response.status_code != 200:
            logger.warning(f"[STT] Scribe batch HTTP {response.status_code}: {response.text[:120]}")
            return None
        payload = response.json()
        latency_ms = (time.perf_counter() - started) * 1000
        text = (payload.get("text") or "").strip()
        logger.info(f"[STT] Scribe batch {latency_ms:.0f} ms: {text!r}")
        return Transcription(text=text, language=to_bcp47(payload.get("language_code"), language),
                             latency_ms=latency_ms, model=self.name)
