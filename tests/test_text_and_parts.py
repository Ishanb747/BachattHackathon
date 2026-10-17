"""Sentence chunking, transcript filters, the playout clock, the sentence
judge, language detection, keys, the LLM stream parser and history window."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cascadevoice.audio.codecs import pcm16_to_wav, rms_energy
from cascadevoice.cache import AudioCache
from cascadevoice.defaults import MissingKeyError, load_keys
from cascadevoice.language import detect_local
from cascadevoice.llm import Conversation, OpenAILLM, TextDelta, ToolCall
from cascadevoice.playback import PlaybackClock
from cascadevoice.text import SentenceBuffer, is_backchannel, is_noise_transcript
from cascadevoice.turns import Verdict, assess, strip_events
from tests.fakes import FakeClock


def chunks(buffer, text, step=3):
    out = []
    for i in range(0, len(text), step):
        out += list(buffer.push(text[i:i + step]))
    tail = buffer.flush()
    return out + ([tail] if tail else [])


def test_sentences_come_out_as_they_complete():
    assert chunks(SentenceBuffer(), "Hello there. How are you today? I am fine!") == [
        "Hello there.", "How are you today?", "I am fine!"]


def test_the_first_unit_may_be_cut_early_at_a_clause():
    units = chunks(SentenceBuffer(eager_first=True, min_eager_chars=28),
                   "Thanks for waiting on the line, I have your order here. It ships tomorrow.")
    assert units[0] == "Thanks for waiting on the line,"
    assert units[1:] == ["I have your order here.", "It ships tomorrow."]


def test_short_sentences_after_the_first_are_joined():
    units = chunks(SentenceBuffer(min_unit_chars=20), "Sure. Okay. That is all set now for you.")
    assert units == ["Sure.", "Okay. That is all set now for you."]


def test_abbreviations_and_danda():
    assert chunks(SentenceBuffer(), "Dr. Rao will call. धन्यवाद। ठीक है।") == ["Dr. Rao will call.", "धन्यवाद।", "ठीक है।"]


def test_noise_and_backchannels():
    assert is_noise_transcript("") and is_noise_transcript("Hmm.") and is_noise_transcript("M.")
    assert not is_noise_transcript("3") and not is_noise_transcript("हाँ")
    assert is_backchannel("haan ji") and is_backchannel("Okay.") and is_backchannel("ठीक है")
    assert not is_backchannel("okay but wait")


def test_the_playout_clock_knows_what_was_heard():
    clock = FakeClock()
    playback = PlaybackClock(tail_padding=0.25, now=clock)
    playback.enqueue("First sentence.", 1.0)
    playback.enqueue("", 0.5)                 # more chunks of the same sentence
    playback.enqueue("Second sentence.", 1.0)
    assert playback.is_speaking and round(playback.remaining, 2) == 2.5
    clock.t += 1.2
    assert playback.spoken_text() == "First sentence."
    clock.t += 0.4
    assert playback.spoken_text() == "First sentence. Second sentence."
    assert playback.stop() == "First sentence. Second sentence."
    assert not playback.is_speaking


def test_a_new_run_of_speech_starts_its_own_clock():
    clock = FakeClock()
    playback = PlaybackClock(tail_padding=0.25, now=clock)
    playback.enqueue("Old line.", 1.0)
    clock.t += 5.0
    playback.enqueue("New line.", 1.0)
    clock.t += 0.2
    assert playback.speaking_for == pytest.approx(0.2) and playback.spoken_text() == "New line."


def test_sentence_judge():
    assert assess("It was completed but") is Verdict.INCOMPLETE
    assert assess("Yeah, much") is Verdict.INCOMPLETE
    assert assess("I was saying,") is Verdict.INCOMPLETE
    assert assess("what do you mean by that?") is Verdict.COMPLETE
    assert assess("Yes it is.") is Verdict.COMPLETE, "a full stop after a connective is finished"
    assert assess("Yes.") is Verdict.UNKNOWN
    assert assess("मुझे लगता") is Verdict.INCOMPLETE
    assert strip_events("(laughs) four") == "four"


def test_language_from_the_words():
    assert detect_local("Yes, that's right.") == "en-IN"
    assert detect_local("हाँ जी, हो गया") == "hi-IN"
    assert detect_local("haan ji theek hai") == "hi-IN"
    assert detect_local("My name is राहुल and I live in Pune") == "en-IN", "one transliterated name is not a switch"


def test_keys_load_from_env_file_and_a_missing_one_is_named(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("# comment\nOPENAI_API_KEY=sk-test\nELEVENLABS_API_KEY='el-test'\n")
    keys = load_keys(env)
    assert (keys.openai, keys.elevenlabs) == ("sk-test", "el-test")
    env.write_text("OPENAI_API_KEY=\nELEVENLABS_API_KEY=el\n")
    with pytest.raises(MissingKeyError, match="OPENAI_API_KEY"):
        load_keys(env)


async def test_the_openai_stream_becomes_text_and_assembled_tool_calls():
    def chunk(content=None, tool=None):
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool))])

    def part(index, id=None, name=None, args=None):
        return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=args))

    async def fake_stream():
        for c in (chunk("Let me "), chunk("check."), chunk(tool=[part(0, "call_1", "order_status", '{"id"')]),
                  chunk(tool=[part(0, None, None, ': "42"}')]), SimpleNamespace(choices=[])):
            yield c

    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return fake_stream()

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    llm = OpenAILLM("unused", client=client)
    events = [e async for e in llm.stream([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])]
    assert events == [TextDelta("Let me "), TextDelta("check."), ToolCall("call_1", "order_status", {"id": "42"})]
    assert captured["model"] == "gpt-4o" and captured["stream"] is True and captured["tools"]


def test_history_window_never_splits_a_tool_result_from_its_call():
    conversation = Conversation(max_turns=2)
    for i in range(3):
        conversation.add_user(f"u{i}")
        conversation.extend([{"role": "assistant", "content": None, "tool_calls": []},
                             {"role": "tool", "tool_call_id": "x", "content": "{}"}])
        conversation.add_agent(f"a{i}")
    window = conversation.window()
    assert window[0] == {"role": "user", "content": "u1"} and len(window) == 8


def test_cache_keys_on_text_voice_and_rate():
    cache = AudioCache(max_items=2)
    cache.put("Hello  there.", "v1", 22050, b"a")
    assert cache.get("hello there.", "v1", 22050) == b"a"
    assert cache.get("Hello there.", "v2", 22050) is None and cache.get("Hello there.", "v1", 16000) is None
    assert cache.has_prefix("Hello", "v1", 22050)
    cache.put("b", "v1", 22050, b"b")
    cache.put("c", "v1", 22050, b"c")
    assert cache.get("Hello there.", "v1", 22050) is None, "least recently used goes first"


def test_wav_header_and_rms():
    wav = pcm16_to_wav(b"\x00\x10" * 100, 16000)
    assert wav[:4] == b"RIFF" and len(wav) == 244
    assert rms_energy(b"\x00\x10" * 100) == 4096.0
