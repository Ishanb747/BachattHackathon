"""The brain: an OpenAI text model, streamed, with optional function tools.

The model streams a sequence of typed events — text deltas and tool calls —
so the session can start speaking at the first complete sentence and run a
tool without knowing anything about the vendor's wire format.
"""

from __future__ import annotations

import inspect
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Union

from cascadevoice import defaults as d

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: Dict[str, Any] = field(default_factory=dict)


LLMEvent = Union[TextDelta, ToolCall]


@dataclass
class Tool:
    """A function the model may call. ``fn(args)`` may be sync or async; its
    return value (JSON-serialisable) goes back to the model, which then speaks."""

    name: str
    description: str
    parameters: Dict[str, Any]
    fn: Callable[[Dict[str, Any]], Union[Any, Awaitable[Any]]]

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}

    async def run(self, args: Dict[str, Any]) -> Any:
        result = self.fn(args)
        return await result if inspect.isawaitable(result) else result


# Built in, handled by the session itself: the model's way to end the call.
END_CALL = Tool(
    name="end_call",
    description="End the call. Use only after saying goodbye, when the user is done or asks to end the call.",
    parameters={"type": "object", "properties": {"reason": {"type": "string"}}, "required": []},
    fn=lambda args: {"status": "ending"},
)

VOICE_GUIDANCE = (
    "You are speaking on a live voice call; everything you write is read aloud. Reply in one to three short "
    "sentences. No markdown, no lists, no emojis, no URLs. Ask one question at a time. Reply in the language "
    "the user last spoke."
)


class OpenAILLM:
    """gpt-4o over Chat Completions streaming."""

    def __init__(self, api_key: str, *, model: str = d.LLM_MODEL, client: Any = None) -> None:
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key)
        self.client = client
        self.model = model
        self.name = f"openai:{model}"

    async def stream(self, messages: List[dict], *, tools: Optional[List[dict]] = None) -> AsyncIterator[LLMEvent]:
        started = time.perf_counter()
        stream = await self.client.chat.completions.create(
            model=self.model, messages=messages, stream=True,
            temperature=d.LLM_TEMPERATURE, max_completion_tokens=d.LLM_MAX_OUTPUT_TOKENS,
            **({"tools": tools} if tools else {}),
        )
        # Tool calls arrive as fragments keyed by index: the name first, then
        # the arguments JSON a few characters at a time.
        calls: Dict[int, dict] = {}
        first = True
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if first and (delta.content or delta.tool_calls):
                logger.info(f"[LLM] first token in {(time.perf_counter() - started) * 1000:.0f} ms ({self.model})")
                first = False
            if delta.content:
                yield TextDelta(delta.content)
            for part in delta.tool_calls or []:
                call = calls.setdefault(part.index, {"id": "", "name": "", "args": ""})
                call["id"] = part.id or call["id"]
                if part.function is not None:
                    call["name"] += part.function.name or ""
                    call["args"] += part.function.arguments or ""
        for index in sorted(calls):
            call = calls[index]
            try:
                args = json.loads(call["args"]) if call["args"] else {}
            except json.JSONDecodeError:
                logger.warning(f"[LLM] Unparseable arguments for {call['name']}: {call['args'][:80]!r}")
                args = {}
            yield ToolCall(id=call["id"] or f"call_{index}", name=call["name"], args=args if isinstance(args, dict) else {})


class Conversation:
    """The call's history, in Chat Completions messages.

    Only the most recent ``LLM_HISTORY_TURNS`` user turns are sent, cut at a
    user message so a tool result is never separated from its call.
    """

    def __init__(self, max_turns: int = d.LLM_HISTORY_TURNS) -> None:
        self.messages: List[dict] = []
        self._max_turns = max_turns

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_agent(self, text: str) -> None:
        if text:
            self.messages.append({"role": "assistant", "content": text})

    def extend(self, messages: List[dict]) -> None:
        self.messages.extend(messages)

    def window(self) -> List[dict]:
        starts = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        if len(starts) <= self._max_turns:
            return list(self.messages)
        return self.messages[starts[-self._max_turns]:]
