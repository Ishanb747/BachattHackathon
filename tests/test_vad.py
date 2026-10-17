"""VADProcessor on synthetic audio."""

from __future__ import annotations

import numpy as np
import pytest

from cascadevoice.audio.vad import FRAME_SIZE_BYTES, VADEvent, VADProcessor
from cascadevoice.audio.vad_engines import DEFAULT_MODEL_PATH, EnergyClassifier, create_classifier

SR = 16000


def events(processor: VADProcessor, signal: np.ndarray) -> list:
    pcm = np.clip(signal, -32768, 32767).astype(np.int16).tobytes()
    out = []
    for i in range(0, len(pcm) - FRAME_SIZE_BYTES + 1, FRAME_SIZE_BYTES):
        result = processor.process_frame(pcm[i:i + FRAME_SIZE_BYTES])
        if result.event not in (VADEvent.SILENCE, VADEvent.SPEECH):
            out.append((i // FRAME_SIZE_BYTES, result.event, result.speech_frames))
    return out


def tone(ms: int, amp: float = 6000, hz: float = 220) -> np.ndarray:
    t = np.arange(int(SR * ms / 1000)) / SR
    return np.sin(2 * np.pi * hz * t) * amp


def silence(ms: int) -> np.ndarray:
    return np.zeros(int(SR * ms / 1000))


def speechlike(ms: int) -> np.ndarray:
    """Harmonic voice with a wandering pitch and a 4 Hz syllable envelope."""
    t = np.arange(int(SR * ms / 1000)) / SR
    f0 = 140 + 20 * np.sin(2 * np.pi * 1.5 * t)
    phase = 2 * np.pi * np.cumsum(f0) / SR
    voiced = sum(np.sin(k * phase) / k for k in range(1, 15))
    return voiced * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)) ** 2 * 6000


def energy_vad(**kwargs) -> VADProcessor:
    """The state machine with the energy gate as the only judge."""
    return VADProcessor(classifier=EnergyClassifier(), **kwargs)


def test_silence_never_starts_speech():
    assert events(energy_vad(), silence(2000)) == []


def test_a_sustained_sound_is_one_utterance_with_a_pause_hint_before_its_end():
    found = events(energy_vad(), np.concatenate([silence(200), tone(400), silence(400)]))
    kinds = [e[1] for e in found]
    assert kinds == [VADEvent.SPEECH_START, VADEvent.PAUSE_HINT, VADEvent.END_OF_UTTERANCE]
    start, eou = found[0][0], found[2][0]
    assert start == 10 + 2, "confirmed on the 3rd voiced frame (60 ms onset)"
    assert found[2][2] >= 20, "the utterance reports its own speech frames"
    assert eou - (10 + 20) + 1 == 11, "the 11th silent frame (220 ms) ends the turn"


def test_a_click_is_aborted_not_a_turn():
    found = events(energy_vad(), np.concatenate([silence(200), tone(80), silence(400)]))
    assert [e[1] for e in found] == [VADEvent.SPEECH_START, VADEvent.SPEECH_ABORTED]


def test_a_quiet_sound_under_the_floor_is_ignored():
    assert events(energy_vad(), tone(500, amp=300)) == []


def test_extension_holds_the_endpoint_open():
    vad = energy_vad()
    pcm = np.concatenate([tone(400), silence(100)])
    events(vad, pcm)
    vad.extend_current_eou(20)
    later = events(vad, silence(600))
    assert later and later[-1][1] is VADEvent.END_OF_UTTERANCE
    assert later[-1][0] >= 20 + 11 - 5 - 1, "the window grew by the extension"


def test_onset_is_stricter_while_the_agent_speaks():
    vad = energy_vad(onset_frames=3, barge_in_onset_frames=5)
    vad.set_agent_speaking(True)
    found = events(vad, np.concatenate([tone(300), silence(300)]))
    assert found[0][0] == 4, "five voiced frames before believing a barge-in"


def test_steady_background_raises_the_gate():
    vad = energy_vad()
    floor = vad.energy_threshold
    rng = np.random.default_rng(0)
    # Background the classifier rejects teaches the ambient level.
    vad._vad = type("Never", (), {"is_speech": lambda self, f, r: False, "reset": lambda self: None})()
    events(vad, rng.normal(0, 600, SR * 2))
    assert vad.energy_threshold > floor


def test_from_defaults_converts_milliseconds_to_frames():
    vad = VADProcessor.from_defaults(classifier=EnergyClassifier())
    assert vad._eou_silence_frames == 11 and vad._onset_frames == 3 and vad._barge_in_onset_frames == 5
    assert vad._speculative_frames == 5 and vad._pre_roll_frames == 18 and vad._min_speech_frames == 7


def test_webrtc_hears_nothing_in_silence():
    assert events(VADProcessor(classifier=create_classifier("webrtc")), silence(1000)) == []


@pytest.mark.skipif(not DEFAULT_MODEL_PATH.exists(), reason="Silero model not present (downloaded on first use)")
@pytest.mark.parametrize("name,signal", [
    ("silence", silence(2000)),
    ("white noise", np.random.default_rng(0).normal(0, 3000, SR * 2)),
    ("pure tone", tone(2000, amp=8000)),
])
def test_silero_rejects_what_is_not_a_voice(name, signal):
    vad = VADProcessor(classifier=create_classifier("silero"))
    assert events(vad, signal) == [], name


def test_an_early_commit_returns_the_utterance_and_resets():
    vad = energy_vad()
    events(vad, np.concatenate([tone(300), silence(80)]))
    assert vad.in_speech and vad.silence_ms_so_far == 80
    pcm = vad.commit()
    assert pcm and not vad.in_speech and vad.commit() is None


@pytest.mark.skipif(not DEFAULT_MODEL_PATH.exists(), reason="Silero model not present (downloaded on first use)")
def test_silero_hears_a_voice_like_signal():
    vad = VADProcessor(classifier=create_classifier("silero"))
    found = events(vad, np.concatenate([silence(500), speechlike(1000), silence(1000)]))
    assert VADEvent.SPEECH_START in [e[1] for e in found]
    assert found[-1][1] is VADEvent.END_OF_UTTERANCE
