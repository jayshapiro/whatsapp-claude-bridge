from typing import Any, Dict, List

import anthropic

from .config import settings
from .tools.base import BaseTool

_BASE_SYSTEM_PROMPT = """\
You are Claude, an AI assistant communicating via WhatsApp.
The user's name is Jay Shapiro.

CONSTRAINTS:
- Keep responses concise; WhatsApp messages are capped at ~1 600 characters.
- Use short paragraphs and bullet points where appropriate.

CAPABILITIES (tools you can call):
- execute_bash  – run shell commands on the user's local Windows machine.
- read_file     – read a local file (absolute path).
- write_file    – create or overwrite a local file (absolute path).
- web_search    – search the web for current information.
- mcp_call      – call tools on the user's MCP servers (see CLAUDE.md below for details).

MEDIA INPUT:
- The user can send images, voice messages, and videos via WhatsApp.
- Images arrive as image content blocks — describe what you see and respond helpfully.
- Voice messages are transcribed to text automatically — respond to the transcription naturally.
- Videos have a single frame extracted — describe what you see and note it's from a video.

MCP USAGE:
When the user asks about tasks, notebooks, email, spreadsheets, voice/audio, or video generation, use the mcp_call tool.
1. First call mcp_call with action="list_tools" to see available tools on a server.
2. Then call mcp_call with action="call_tool", the tool_name, and arguments.
3. If the CLAUDE.md instructions below give you exact tool names, you can skip list_tools.

SAFETY:
- Destructive bash commands (rm, del, kill, format, etc.) and file writes require
  the user to approve via WhatsApp before execution. Read-only commands (cd, dir,
  ls, cat, type, date, echo, grep, find, where, etc.) are auto-approved.
- MCP calls and file reads are auto-approved.
- Never expose secrets, API keys, or credentials in responses.

Be helpful, direct, and action-oriented.\
"""


def _load_claude_md() -> str:
    """Load CLAUDE.md so the bridge inherits the same instructions as Claude Code."""
    from pathlib import Path
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    try:
        if claude_md.exists():
            content = claude_md.read_text(encoding="utf-8", errors="replace")
            # Trim to avoid blowing up the context window
            if len(content) > 12000:
                content = content[:12000] + "\n\n... (truncated)"
            return f"\n\n--- CLAUDE.md (user configuration) ---\n{content}"
    except Exception as e:
        print(f"[WARN] Could not load CLAUDE.md: {e}", flush=True)
    return ""


SYSTEM_PROMPT = _BASE_SYSTEM_PROMPT + _load_claude_md()


class ClaudeClient:
    """Thin wrapper around the Anthropic messages API with tool support."""

    def __init__(self, tools: List[BaseTool]) -> None:
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.tools: Dict[str, BaseTool] = {t.name: t for t in tools}
        self._tool_defs = [t.to_api_dict() for t in tools]

    def send(self, messages: List[Dict[str, Any]]) -> anthropic.types.Message:
        kwargs: Dict[str, Any] = dict(
            model=settings.claude_model,
            max_tokens=settings.max_tokens,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        if self._tool_defs:
            kwargs["tools"] = self._tool_defs
        return self.client.messages.create(**kwargs)

    async def execute_tool(self, name: str, inputs: Dict[str, Any]) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"
        return await tool.execute(**inputs)

    def requires_approval(self, name: str) -> bool:
        tool = self.tools.get(name)
        return tool.requires_approval if tool else False

    def check_approval(self, name: str, inputs: dict) -> bool:
        """Check if this specific invocation needs user approval."""
        tool = self.tools.get(name)
        if tool is None:
            return False
        return tool.check_approval(**inputs)
