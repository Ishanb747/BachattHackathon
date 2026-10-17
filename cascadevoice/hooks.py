"""The host project's say in each turn — optional, pass-through by default.

Before the model answers, the hook sees the transcript and may:

* return None — let the model answer as usual;
* ``TurnPlan(reply="…")`` — say this fixed line instead (no model call; the
  line is cached, so a repeated one plays in ~0 ms);
* ``TurnPlan(instructions="…")`` — add context for this turn only (a lookup
  result, a policy reminder) without touching the system prompt;
* ``end_call=True`` on either — hang up once the reply has been spoken.

The model can also end the call itself through its built-in ``end_call``
tool. You can gate a tool call; you cannot un-say a sentence — so anything
with a consequence belongs here or in a tool, never in free text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable


@dataclass
class TurnPlan:
    reply: Optional[str] = None
    instructions: Optional[str] = None
    end_call: bool = False


@runtime_checkable
class TurnHook(Protocol):
    async def before_reply(self, transcript: str, *, language: str, history: List[dict]) -> Optional[TurnPlan]: ...


class PassThrough:
    """The default: the model answers every turn."""

    async def before_reply(self, transcript: str, *, language: str, history: List[dict]) -> Optional[TurnPlan]:
        return None
