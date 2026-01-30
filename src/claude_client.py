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
- send_whatsapp_media – send an image, audio, or video to the user on WhatsApp.

MEDIA INPUT (receiving from user):
- The user can send images, voice messages, and videos via WhatsApp.
- Images arrive as image content blocks — describe what you see and respond helpfully.
- Voice messages are transcribed to text automatically — respond to the transcription naturally.
- Videos have a single frame extracted — describe what you see and note it's from a video.
- All received media is also saved to a local temp file. The path appears as [Image saved to: ...] etc.
- If the user asks you to save, upload, or share a received image/audio/video, use the mcp_call tool
  to call the "google-drive" server's "uploadFile" tool with the saved file path and
  parentFolderId "1iF1dU0-iZbirNXy3XviQvdZrhBT3c1SG" (the public ClaudeCode Dropbox folder).
  Then share the resulting link: https://drive.google.com/file/d/<FILE_ID>/view

MEDIA OUTPUT (sending to user):
- You can send images, audio, and video TO the user on WhatsApp using the send_whatsapp_media tool.
- The media must be at a publicly accessible HTTPS URL.
- WORKFLOW for sending media:
  1. Generate or locate the file (e.g. ElevenLabs TTS audio, an image, a video).
  2. If the file is local, upload it to the Google Drive Dropbox folder via mcp_call:
     - server: "google-drive", tool: "uploadFile"
     - localPath: the file path, parentFolderId: "1iF1dU0-iZbirNXy3XviQvdZrhBT3c1SG"
  3. Get the file ID from the upload result.
  4. Call send_whatsapp_media with:
     - media_url: "https://drive.google.com/uc?export=download&id=<FILE_ID>"
     - caption: optional text to accompany the media
- IMPORTANT: Use the /uc?export=download&id= URL format, NOT the /file/d/ viewer URL.
  WhatsApp/Twilio needs a direct download link, not a Google Drive viewer page.
- Use cases: sending generated audio (TTS), images, charts, documents, videos, etc.

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
