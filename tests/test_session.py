"""The session with fake vendors: pipeline order, barge-in, what the history
records, endpointing, hooks and tools."""

from __future__ import annotations

import asyncio

from cascadevoice.audio.vad import VADEvent
from cascadevoice.cache import AudioCache
from cascadevoice.hooks import TurnPlan
from cascadevoice.llm import Tool, ToolCall
from cascadevoice.session import VoiceSession
from tests.fakes import FakeBatch, FakeClock, FakeEar, FakeLLM, FakeTTS, RecordingTransport, StubVAD, until, vad


def make(llm=None, *, tts=None, ear_text="Hello.", ear=None, batch=None, hook=None, tools=(), greeting=None,
         clock=None):
    ears: list = []

    def ear_factory(language):
        made = ear or FakeEar(ear_text)
        ears.append(made)
        return made

    transport = RecordingTransport()
    session = VoiceSession(
        transport, llm=llm or FakeLLM(), tts=tts or FakeTTS(), ear_factory=ear_factory,
        batch_stt=batch or FakeBatch(), vad=StubVAD(), greeting=greeting, hook=hook, tools=tools,
        cache=AudioCache(),
    )
    if clock is not None:
        session._playback.now = clock
    session.ears = ears
    return session, transport


async def utterance(session, frames: int = 20) -> None:
    """Onset, then end of utterance, as the VAD reports them."""
    await session._handle_vad(vad(VADEvent.SPEECH_START))
    await session._handle_vad(vad(VADEvent.END_OF_UTTERANCE, frames))


def agent_audible(session, clock, text="Could you tell me the order number for that purchase?", seconds=3.0):
    """Put a line on the playout clock, past the grace window."""
    session._playback.enqueue(text, seconds)
    clock.t += 0.5


# ── The pipeline ─────────────────────────────────────────────────────────────

async def test_first_audio_goes_out_after_the_first_sentence_not_the_whole_reply():
    llm = FakeLLM(["Sure, I can help with that today. ", 0.4, "Here is the rest of the answer."])
    session, transport = make(llm, tts=FakeTTS(first_delay=0.02))
    await session.submit_text("Can you help?")
    await until(lambda: transport.first_chunk_at)
    assert llm.finished_at == 0.0, "audio was already playing while the model was still generating"
    await until(lambda: transport.of_type("turn_complete"))
    assert transport.first_chunk_at < llm.finished_at
    assert transport.agent_lines() == ["Sure, I can help with that today.", "Here is the rest of the answer."]


async def test_sentences_play_in_order_even_when_a_later_one_synthesizes_first():
    first, second = "The first sentence is a long one.", "The second sentence is quicker."
    tts = FakeTTS(delays={first: 0.15, second: 0.0}, chunks=1)
    session, transport = make(FakeLLM([first + " ", second]), tts=tts)
    await session.submit_text("Go.")
    await until(lambda: transport.of_type("turn_complete"))
    begins = [i for i, e in enumerate(transport.events) if e["type"] == "audio_begin"]
    assert len(begins) == 2 and len(transport.chunks) == 2
    assert tts.opened == [first, second], "both were in synthesis at once"


async def test_metrics_report_every_stage_from_end_of_utterance():
    session, transport = make(FakeLLM([0.05, "Your order ships tomorrow morning."]),
                              tts=FakeTTS(first_delay=0.03), ear=FakeEar("Where is my order?", delay=0.02))
    await utterance(session)
    await until(lambda: transport.of_type("metrics"))
    m = transport.of_type("metrics")[0]
    assert m["stt_source"] == "realtime"
    assert m["stt_ms"] >= 15 and m["llm_first_token_ms"] >= 45 and m["tts_first_audio_ms"] >= 25
    assert m["total_ms"] >= m["stt_ms"] + m["llm_first_sentence_ms"] + m["tts_first_audio_ms"] - 5
    assert m["true_e2e_ms"] == m["total_ms"] + m["endpoint_wait_ms"]


async def test_the_model_sees_the_history_and_the_turn_is_recorded():
    llm = FakeLLM(["Hi there!"], ["You said hello."])
    session, transport = make(llm)
    await session.submit_text("Hello")
    await until(lambda: transport.of_type("turn_complete"))
    await session.submit_text("What did I say?")
    await until(lambda: len(transport.of_type("turn_complete")) == 2)
    second = llm.calls[1]
    assert second[0]["role"] == "system"
    assert [m["content"] for m in second[1:]] == ["Hello", "Hi there!", "What did I say?"]


async def test_realtime_failure_falls_back_to_batch_scribe():
    batch = FakeBatch("Fallback words.")
    session, transport = make(FakeLLM(["Got it."]), ear=FakeEar(fail=True), batch=batch)
    await utterance(session)
    await until(lambda: transport.of_type("metrics"))
    assert batch.calls == 1 and transport.of_type("metrics")[0]["stt_source"] == "batch"
    assert transport.of_type("transcript")[0]["text"] == "Fallback words."


async def test_noise_transcripts_never_reach_the_model():
    llm = FakeLLM()
    session, transport = make(llm, ear=FakeEar("Hmm."))
    await utterance(session)
    await asyncio.sleep(0.05)
    assert llm.calls == []


# ── Interruptions and the history ────────────────────────────────────────────

async def test_a_cut_reply_is_recorded_only_as_far_as_it_was_heard():
    clock = FakeClock()
    llm = FakeLLM(["First, let me explain the plan. ", "Second, the price is ten dollars. ", "Third, it renews yearly."])
    session, transport = make(llm, tts=FakeTTS(chunks=1, chunk_s=2.0), clock=clock)
    await session.submit_text("Tell me about the plan.")
    await until(lambda: len(transport.chunks) >= 2)   # two sentences sent, 4 s of audio queued
    clock.t += 1.0                                    # the user has heard 1 s: the first sentence only
    await session.interrupt(reason="barge_in")
    assert transport.stops == 1
    assert session.conversation.messages == [
        {"role": "user", "content": "Tell me about the plan."},
        {"role": "assistant", "content": "First, let me explain the plan."},
    ]


async def test_a_reply_cut_after_it_was_fully_sent_is_truncated_in_place():
    clock = FakeClock()
    session, transport = make(FakeLLM(["One thing first. ", "Then another thing."]),
                              tts=FakeTTS(chunks=1, chunk_s=2.0), clock=clock)
    await session.submit_text("Go on.")
    await until(lambda: transport.of_type("turn_complete"))
    assert session.conversation.messages[-1]["content"] == "One thing first. Then another thing."
    clock.t += 1.0   # all sent and recorded, but the user is still inside the first sentence
    await session.interrupt(reason="barge_in")
    assert session.conversation.messages[-1]["content"] == "One thing first."


async def test_a_stop_when_nothing_is_playing_keeps_the_history():
    clock = FakeClock()
    session, transport = make(FakeLLM(["Done."]), clock=clock)
    await session.submit_text("Go on.")
    await until(lambda: transport.of_type("turn_complete"))
    clock.t += 10
    await session.interrupt(reason="client_request")
    assert session.conversation.messages[-1]["content"] == "Done."


async def test_a_follow_up_before_the_reply_played_is_merged_into_one_turn():
    llm = FakeLLM([0.3, "Too late."], ["Answer to both."])
    session, transport = make(llm)
    await session.submit_text("I want to change")
    await asyncio.sleep(0.05)
    await session.submit_text("my delivery address.")
    await until(lambda: transport.of_type("turn_complete"))
    assert llm.calls[-1][-1]["content"] == "I want to change my delivery address."
    assert [m["content"] for m in session.conversation.messages] == [
        "I want to change my delivery address.", "Answer to both."]


async def test_the_greeting_is_cached_and_interruptible():
    clock = FakeClock()
    tts = FakeTTS(chunks=1, chunk_s=2.0)
    session, transport = make(tts=tts, greeting="Hello, this is Asha. How can I help?", clock=clock)
    await session.start()
    await until(lambda: transport.of_type("turn_complete"))
    assert session.conversation.messages == [{"role": "assistant", "content": "Hello, this is Asha. How can I help?"}]
    again, transport2 = make(tts=tts, greeting="Hello, this is Asha. How can I help?")
    again.cache = session.cache
    await again.start()
    await until(lambda: transport2.of_type("turn_complete"))
    assert tts.opened == ["Hello, this is Asha. How can I help?"], "the second greeting came from the cache"


# ── The barge-in gate ────────────────────────────────────────────────────────

async def test_sustained_speech_over_the_agent_interrupts():
    clock = FakeClock()
    session, transport = make(clock=clock)
    agent_audible(session, clock)
    await session._handle_vad(vad(VADEvent.SPEECH_START))
    assert session._pending_barge_in and transport.stops == 0
    await session._handle_vad(vad(VADEvent.SPEECH, speech_frames=15))   # 300 ms: not yet
    assert transport.stops == 0
    await session._handle_vad(vad(VADEvent.SPEECH, speech_frames=23))   # 460 ms
    assert transport.stops == 1 and not session._agent_audible()


async def test_a_backchannel_over_the_agent_is_parked_not_an_interruption():
    clock = FakeClock()
    llm = FakeLLM(["Okay, noted."])
    session, transport = make(llm, ear=FakeEar("haan"), clock=clock)
    agent_audible(session, clock, seconds=8.0)   # far from the tail
    await utterance(session, frames=8)
    await asyncio.sleep(0.05)
    assert transport.stops == 0 and llm.calls == []
    assert session._parked_backchannel is not None
    clock.t += 9.0   # the line finishes; the parked "haan" is answered
    await until(lambda: llm.calls, timeout=3)
    assert llm.calls[0][-1]["content"] == "haan"


async def test_a_complete_short_answer_on_the_tail_interrupts():
    clock = FakeClock()
    llm = FakeLLM(["Great."])
    session, transport = make(llm, ear=FakeEar("No, I don't."), clock=clock)
    agent_audible(session, clock, seconds=2.0)
    await utterance(session, frames=12)
    await until(lambda: llm.calls)
    assert transport.stops == 1
    assert llm.calls[0][-1]["content"] == "No, I don't."


async def test_a_real_interruption_mid_line_cuts_it():
    clock = FakeClock()
    llm = FakeLLM(["Sure."])
    session, transport = make(llm, ear=FakeEar("Wait, I need to change the delivery address"), clock=clock)
    agent_audible(session, clock, seconds=8.0)
    await utterance(session, frames=40)
    await until(lambda: llm.calls)
    assert transport.stops == 1


async def test_an_aborted_onset_or_noise_over_the_agent_changes_nothing():
    clock = FakeClock()
    llm = FakeLLM()
    session, transport = make(llm, ear=FakeEar("Mm."), clock=clock)
    agent_audible(session, clock)
    await session._handle_vad(vad(VADEvent.SPEECH_START))
    await session._handle_vad(vad(VADEvent.SPEECH_ABORTED))
    assert not session._pending_barge_in and transport.stops == 0
    await utterance(session, frames=6)
    await asyncio.sleep(0.05)
    assert transport.stops == 0 and llm.calls == [] and session._parked_backchannel is None


async def test_the_first_moments_of_the_agent_line_are_not_barge_in():
    clock = FakeClock()
    session, transport = make(clock=clock)
    session._playback.enqueue("Hello there, how are you?", 3.0)
    clock.t += 0.1   # inside the grace window
    await session._handle_vad(vad(VADEvent.SPEECH_START))
    assert not session._pending_barge_in


# ── Endpointing ──────────────────────────────────────────────────────────────

async def test_a_mid_thought_pause_extends_the_window():
    session, _ = make(ear=FakeEar(partial="It was completed but"))
    await session._handle_vad(vad(VADEvent.SPEECH_START))
    await session._handle_vad(vad(VADEvent.PAUSE_HINT))
    assert session._vad.extended == 20 and not session._vad.committed


async def test_a_complete_sentence_at_the_pause_commits_early():
    llm = FakeLLM(["Thanks."])
    session, transport = make(llm, ear=FakeEar("My order number is four two one.",
                                                partial="My order number is four two one."))
    await session._handle_vad(vad(VADEvent.SPEECH_START))
    await session._handle_vad(vad(VADEvent.PAUSE_HINT))
    assert session._vad.committed
    await until(lambda: llm.calls)
    await until(lambda: transport.of_type("metrics"))
    assert transport.of_type("metrics")[0]["endpoint_wait_ms"] == 110.0


# ── Hooks and tools ──────────────────────────────────────────────────────────

class ReplaceHook:
    async def before_reply(self, transcript, *, language, history):
        if "price" in transcript:
            return TurnPlan(reply="Our plan costs ten dollars a month.")
        if "bye" in transcript:
            return TurnPlan(reply="Goodbye!", end_call=True)
        return TurnPlan(instructions="The user's name is Priya.")


async def test_a_hook_can_replace_the_reply_add_instructions_or_end_the_call():
    llm = FakeLLM(["Hello Priya."])
    session, transport = make(llm, hook=ReplaceHook())
    await session.submit_text("What's the price?")
    await until(lambda: transport.of_type("turn_complete"))
    assert llm.calls == [] and transport.agent_lines() == ["Our plan costs ten dollars a month."]
    assert transport.of_type("metrics")[0]["hooked"] is True

    await session.submit_text("Hi")
    await until(lambda: len(transport.of_type("turn_complete")) == 2)
    assert {"role": "system", "content": "The user's name is Priya."} in llm.calls[0]

    await session.submit_text("bye now")
    await until(lambda: transport.of_type("control"))
    assert transport.of_type("control")[0] == {"type": "control", "action": "hangup", "reason": "end_call"}


async def test_a_tool_runs_and_the_model_speaks_its_result():
    seen = []
    lookup = Tool("order_status", "Look up an order.", {"type": "object", "properties": {"id": {"type": "string"}}},
                  lambda args: seen.append(args) or {"status": "shipped"})
    llm = FakeLLM(["Let me check. ", ToolCall("c1", "order_status", {"id": "42"})], ["It has shipped."])
    session, transport = make(llm, tools=[lookup])
    await session.submit_text("Where is order 42?")
    await until(lambda: transport.of_type("turn_complete"))
    assert seen == [{"id": "42"}]
    assert transport.agent_lines() == ["Let me check.", "It has shipped."]
    second = llm.calls[1]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "order_status"
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"status": "shipped"}'}
    roles = [m["role"] for m in session.conversation.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]


async def test_the_model_can_end_the_call():
    llm = FakeLLM(["Goodbye, take care! ", ToolCall("c9", "end_call", {"reason": "done"})])
    session, transport = make(llm)
    await session.submit_text("That's all, thanks.")
    await until(lambda: transport.of_type("control"))
    assert transport.of_type("control")[0]["action"] == "hangup"
    assert len(llm.calls) == 1, "no second round after end_call"


async def test_language_follows_the_words():
    session, transport = make(FakeLLM(["ठीक है।"]))
    await session.submit_text("मेरा ऑर्डर कहाँ है")
    await until(lambda: transport.of_type("turn_complete"))
    assert session.language == "hi-IN"
    assert transport.of_type("transcript")[0]["language"] == "hi-IN"
