"""cascadevoice — a full-duplex cascade voice layer.

mic → VAD (Silero) → ElevenLabs Scribe realtime → OpenAI gpt-4o (streamed)
→ sentence chunking → ElevenLabs Flash TTS (streamed) → browser.

The mic is listened to the whole time the agent speaks; a barge-in gate
decides what counts as an interruption.
"""

from cascadevoice.hooks import PassThrough, TurnHook, TurnPlan
from cascadevoice.llm import Tool
from cascadevoice.session import VoiceSession
from cascadevoice.transport import BrowserTransport, Transport

__all__ = ["BrowserTransport", "PassThrough", "Tool", "Transport", "TurnHook", "TurnPlan", "VoiceSession"]
