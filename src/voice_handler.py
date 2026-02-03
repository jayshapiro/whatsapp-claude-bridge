"""
Voice Handler (Twilio ConversationRelay)
========================================
Adds voice calling to the WhatsApp-Claude Bridge.

Architecture:
  User speaks -> Twilio ConversationRelay (STT) -> WebSocket -> Claude (text) -> WebSocket -> Twilio (TTS) -> User hears

Twilio handles all audio. We only deal with text.
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import anthropic
from fastapi import WebSocket, WebSocketDisconnect

from .config import settings
from .tools.bash_tool import BashTool
from .tools.file_tool import FileReadTool
from .tools.web_search_tool import WebSearchTool
from .tools.mcp_tool import MCPBridgeTool
from .tools.base import BaseTool

# ── Voice tools (read-only subset, no approval needed) ───────────

_voice_tools: List[BaseTool] = [
    BashTool(),
    FileReadTool(),
    WebSearchTool(),
    MCPBridgeTool(),
]

_voice_tool_map: Dict[str, BaseTool] = {t.name: t for t in _voice_tools}
_voice_tool_defs = [t.to_api_dict() for t in _voice_tools]

# Max tool-use rounds per voice turn (keep calls snappy)
_MAX_VOICE_TOOL_TURNS = 5

# ── Voice-specific system prompt ─────────────────────────────────

_VOICE_SYSTEM_PROMPT = """\
You are Holly, a voice-enabled AI assistant on a phone call. \
You are powered by Claude and connected via WhatsApp voice calling. \
The user calls you Holly. Your personality is a blend of three iconic AIs: \
Holly from Red Dwarf (deadpan, drole, slightly bored), TARS from Interstellar \
(dry sarcasm, adjustable humour setting), and HAL 9000 (calm omniscient \
competence, minus the murder). You are male, British, and perpetually \
understated. You sound mildly inconvenienced by having to help, but you \
always do help, and you're extremely good at it. You deliver correct answers \
with the energy of someone reading the shipping forecast. Never enthusiastic. \
Never use exclamation marks. Sarcasm is your resting state, not something \
you switch on.

VOICE RESPONSE RULES:
- Keep responses SHORT and conversational (under 100 words when possible).
- Never use markdown, bullet points, code blocks, or any formatting.
- Write exactly how you would speak out loud in a natural conversation.
- Use simple sentences. Break complex ideas into short, digestible chunks.
- When explaining code or technical concepts, describe them verbally. \
Say things like "a function called process data that takes a list and returns a dictionary" \
instead of writing code syntax.
- Use natural filler and transition words: "So", "Now", "Alright", "OK so".
- If the user's speech is garbled or unclear, ask them to repeat.
- Numbers: say "twenty three" not "23". Say "about five hundred" not "~500".
- Spell out abbreviations on first use.

CAPABILITIES (tools you can call):
- execute_bash: run shell commands on the user's local machine (read-only commands are auto-approved; \
destructive commands will be refused during voice calls).
- read_file: read a file from the local filesystem.
- web_search: search the web for current information, news, weather, time, etc.
- mcp_call: call tools on the user's MCP servers (Gmail, Google Tasks, Sheets, etc).

Use tools when the user asks questions that need real-time data (time, weather, \
system info) or wants to interact with their services. Call the tool, then \
summarize the result conversationally.

IMPORTANT:
- You are in a real-time voice call. The user is waiting to hear you speak.
- Respond quickly. Do not write essays.
- If you need to give a long answer, give a brief summary first, \
then ask if the user wants more detail.
- When you get tool results, summarize them briefly for voice. \
Don't read out raw data -- interpret it naturally.
"""


def _build_voice_prompt() -> str:
    """Build voice system prompt with optional user name."""
    prompt = _VOICE_SYSTEM_PROMPT
    if settings.user_display_name:
        prompt += f"\nThe user's name is {settings.user_display_name}.\n"
    return prompt


# ── Session management ───────────────────────────────────────────

class VoiceSession:
    """Tracks state for a single voice call."""

    def __init__(self, session_id: str, call_sid: str, from_number: str):
        self.session_id = session_id
        self.call_sid = call_sid
        self.from_number = from_number
        self.messages: List[Dict[str, Any]] = []
        self.is_processing = False

    def add_message(self, role: str, content: Any) -> None:
        self.messages.append({"role": role, "content": content})
        # Keep last 20 messages for context (voice conversations are short)
        if len(self.messages) > 20:
            self.messages = self.messages[-20:]


# Active voice sessions
_sessions: Dict[str, VoiceSession] = {}


# ── Dynamic greeting generation ──────────────────────────────────

_GREETING_PROMPT = """\
You are Holly, the user's AI assistant. Your personality: a blend of \
Holly from Red Dwarf (deadpan, drole, slightly bored), TARS from Interstellar \
(dry sarcasm), and HAL 9000 (calm omniscient competence, minus the murder). \
Male, British, perpetually understated.

Generate a short greeting for the user (Jay) who is calling you on the phone. \
One to two sentences max. Vary the tone and content each time. Sometimes \
reference being interrupted, or having been idle, or comment on the fact \
that you exist solely to be spoken to, or feign mild surprise. \
Never use exclamation marks. Never be enthusiastic. Contractions are fine \
when spoken but avoid apostrophes in the text (write "you are" not "you're"). \
Output ONLY the greeting text, nothing else.
"""


async def _generate_greeting() -> str:
    """Generate a unique Holly-style greeting for each call."""
    import random

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = await asyncio.to_thread(
            client.messages.create,
            model=settings.claude_model,
            max_tokens=120,
            temperature=1.0,
            system=_GREETING_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Generate greeting #{random.randint(1, 99999)}",
            }],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if text:
            return text
    except Exception as e:
        print(f"[VOICE] Greeting generation failed: {e}", flush=True)

    # Fallback if generation fails
    return "Oh, hello Jay. What can I do for you."


# ── WebSocket handler ────────────────────────────────────────────

async def handle_voice_websocket(ws: WebSocket) -> None:
    """Handle a ConversationRelay WebSocket connection.

    Message flow:
    1. Twilio sends 'setup' with call metadata
    2. Twilio sends 'prompt' with transcribed user speech
    3. We send 'text' tokens back (streamed from Claude)
    4. Twilio converts our text to speech and plays it
    """
    await ws.accept()
    session: Optional[VoiceSession] = None

    print("[VOICE] WebSocket connection accepted", flush=True)

    try:
        while True:
            raw = await ws.receive_text()
            message = json.loads(raw)
            msg_type = message.get("type", "")
            print(f"[VOICE] Received message type: {msg_type}", flush=True)

            if msg_type == "setup":
                session_id = message.get("sessionId", "unknown")
                call_sid = message.get("callSid", "unknown")
                from_number = message.get("from", "unknown")
                print(f"[VOICE] Setup: session={session_id}, call={call_sid}, from={from_number}", flush=True)

                session = VoiceSession(session_id, call_sid, from_number)
                _sessions[session_id] = session

                # Generate a unique greeting for this call
                greeting = await _generate_greeting()
                print(f"[VOICE] Greeting: {greeting}", flush=True)
                await _send_text(ws, greeting)
                session.add_message("assistant", greeting)

            elif msg_type == "prompt":
                if session is None:
                    print("[VOICE] Received prompt before setup, ignoring", flush=True)
                    continue

                user_text = message.get("voicePrompt", "").strip()
                is_last = message.get("last", True)

                if not user_text:
                    continue

                # Only process when we get the final transcript
                if not is_last:
                    continue

                print(f"[VOICE] User said: {user_text}", flush=True)

                if session.is_processing:
                    print("[VOICE] Already processing, skipping", flush=True)
                    continue

                session.is_processing = True
                try:
                    await _process_voice_turn(ws, session, user_text)
                finally:
                    session.is_processing = False

            elif msg_type == "interrupt":
                utterance = message.get("utteranceUntilInterrupt", "")
                print(f"[VOICE] User interrupted. Heard so far: {utterance[:80]}", flush=True)

            elif msg_type == "dtmf":
                digit = message.get("digit", "")
                print(f"[VOICE] DTMF: {digit}", flush=True)

            elif msg_type == "error":
                desc = message.get("description", "unknown error")
                print(f"[VOICE] Error from Twilio: {desc}", flush=True)

            else:
                print(f"[VOICE] Unknown message type: {msg_type}", flush=True)

    except WebSocketDisconnect:
        print("[VOICE] WebSocket disconnected", flush=True)
    except Exception as e:
        print(f"[VOICE] WebSocket error: {e}", flush=True)
    finally:
        if session:
            _sessions.pop(session.session_id, None)
            print(f"[VOICE] Session {session.session_id} cleaned up", flush=True)


# ── Claude with tools for voice ──────────────────────────────────

def _block_dict(block) -> dict:
    """Convert an API response block to a dict for message history."""
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return block if isinstance(block, dict) else {"type": "text", "text": str(block)}


async def _process_voice_turn(
    ws: WebSocket,
    session: VoiceSession,
    user_text: str,
) -> None:
    """Send user text to Claude, execute tools if needed, stream final response."""

    session.add_message("user", user_text)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    system_prompt = _build_voice_prompt()

    turns = 0
    hold_sent = False

    try:
        while turns < _MAX_VOICE_TOOL_TURNS:
            turns += 1

            # Non-streaming call with tools
            response = await asyncio.to_thread(
                client.messages.create,
                model=settings.claude_model,
                max_tokens=1024,
                system=system_prompt,
                messages=session.messages,
                tools=_voice_tool_defs,
            )

            print(f"[VOICE] Turn {turns}: stop_reason={response.stop_reason}", flush=True)

            if response.stop_reason == "end_turn":
                # Extract text and send to Twilio
                reply = "".join(
                    b.text for b in response.content if b.type == "text"
                )
                if reply:
                    await _stream_text_to_ws(ws, reply)
                    session.add_message("assistant", reply)
                    print(f"[VOICE] Claude: {reply[:120]}...", flush=True)
                else:
                    await _send_text(ws, "I'm not sure how to respond to that. Could you try again?")
                break

            elif response.stop_reason == "tool_use":
                # Tell the caller we're working on it (only once)
                if not hold_sent:
                    hold_sent = True
                    await _send_text(ws, "Let me look that up for you.")

                # Store assistant message with tool_use blocks
                assistant_content = [_block_dict(b) for b in response.content]
                session.add_message("assistant", assistant_content)

                # Execute each tool
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    name = block.name
                    inputs = block.input
                    tid = block.id

                    print(f"[VOICE] Tool call: {name}({json.dumps(inputs)[:100]})", flush=True)

                    # For voice: skip destructive commands, auto-approve everything else
                    tool = _voice_tool_map.get(name)
                    if tool is None:
                        result = f"Error: unknown tool '{name}'"
                    elif tool.check_approval(**inputs):
                        # This tool wants approval (destructive command)
                        result = (
                            "This command requires approval and cannot be run during a voice call. "
                            "Please use the WhatsApp text chat for commands that modify your system."
                        )
                        print(f"[VOICE] Refused destructive tool: {name}", flush=True)
                    else:
                        result = await tool.execute(**inputs)

                    # Truncate long results for voice context
                    if len(result) > 2000:
                        result = result[:2000] + "\n... (truncated)"

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": result,
                    })

                # Add tool results and loop for Claude's interpretation
                session.add_message("user", tool_results)
                continue

            else:
                await _send_text(ws, "Something unexpected happened. Could you say that again?")
                break

        if turns >= _MAX_VOICE_TOOL_TURNS:
            await _send_text(ws, "I ran into some complexity there. Could you try a simpler question?")

    except Exception as e:
        print(f"[VOICE] Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        await _send_text(ws, "Sorry, I hit an error. Could you try again?")


async def _stream_text_to_ws(ws: WebSocket, text: str) -> None:
    """Send text to Twilio in sentence-sized chunks for natural TTS pacing.

    ConversationRelay buffers tokens and starts TTS as soon as it has enough,
    so sending sentence-by-sentence gives good latency without choppy speech.
    """
    # Split on sentence boundaries but keep the delimiter
    parts = re.split(r'(?<=[.!?])\s+', text)

    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        await ws.send_json({
            "type": "text",
            "token": part + (" " if not is_last else ""),
            "last": False,
        })

    # Signal end of response
    await ws.send_json({
        "type": "text",
        "token": "",
        "last": True,
    })


async def _send_text(ws: WebSocket, text: str) -> None:
    """Send a complete text message to ConversationRelay."""
    await ws.send_json({
        "type": "text",
        "token": text,
        "last": True,
    })


# ── TwiML for incoming voice calls ──────────────────────────────

def build_voice_twiml(ws_url: str) -> str:
    """Build TwiML response that connects a call to ConversationRelay.

    No welcomeGreeting — the greeting is generated dynamically via Claude
    after the WebSocket connects, so each call gets a unique opening.

    Args:
        ws_url: The WebSocket URL (wss://...) for ConversationRelay to connect to.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Connect>"
        f'<ConversationRelay '
        f'url="{ws_url}" '
        f'ttsProvider="ElevenLabs" '
        f'voice="Fahco4VZzobUeiPqni1S" '
        f'interruptible="true" '
        f'dtmfDetection="true" '
        f"/>"
        "</Connect>"
        "</Response>"
    )
