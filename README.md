# WhatsApp-Claude Bridge

> **Chat with Claude from WhatsApp** -- with tool execution, media support, MCP integration, and conversation memory.

A self-hosted bridge that connects WhatsApp to Anthropic's Claude API via Twilio, giving you a powerful AI assistant in your pocket. Send text, images, voice messages, and video -- and receive intelligent responses, generated audio, images, and more -- all through WhatsApp.

---

## Features

| Feature | Description |
|---------|-------------|
| **Two-way chat** | Full conversational Claude via WhatsApp with persistent memory |
| **Tool execution** | Run bash commands, read/write files on your machine remotely |
| **MCP integration** | Auto-loads your Claude Code MCP servers (Gmail, Google Sheets, Tasks, ElevenLabs, NotebookLM, etc.) |
| **Inbound media** | Send images, voice messages, and videos to Claude for analysis |
| **Outbound media** | Claude can send images, audio, and video back to you on WhatsApp |
| **Voice transcription** | Voice messages are auto-transcribed via ElevenLabs (if configured) |
| **Safety approval flow** | Destructive commands require your explicit approval via WhatsApp |
| **Conversation management** | Auto-timeout, message limits, and `/reset` command |
| **Single-user security** | Only your approved phone number can interact with the bot |

---

## Architecture

```
WhatsApp (your phone)
    |
    v
Twilio (webhook)
    |
    v
FastAPI server (localhost:8001)
    |
    +-- Claude API (Anthropic)
    |       |
    |       +-- execute_bash (shell commands)
    |       +-- read_file / write_file
    |       +-- web_search
    |       +-- mcp_call (MCP servers via JSON-RPC)
    |       +-- send_whatsapp_media (outbound media)
    |
    +-- Twilio API (send replies back)
    |
    +-- ngrok tunnel (exposes localhost to Twilio)
```

**How it works:**

1. You send a WhatsApp message to your Twilio number.
2. Twilio forwards it to the bridge's `/webhook` endpoint via ngrok.
3. The bridge sends it to Claude with your conversation history.
4. Claude can call tools (bash, files, MCP servers, web search) and the bridge executes them.
5. The final response is sent back to you on WhatsApp via Twilio.

---

## Quick Start

### Prerequisites

- **Python 3.10+** (recommend using [uv](https://docs.astral.sh/uv/) for fast installs)
- **Twilio account** with a WhatsApp-enabled number ([Twilio Console](https://console.twilio.com))
- **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com))
- **ngrok** (or any tunnel to expose localhost) -- [ngrok.com](https://ngrok.com)

### 1. Clone and install

```bash
git clone https://github.com/jayshapiro/whatsapp-claude-bridge.git
cd whatsapp-claude-bridge
uv sync
```

Or with pip:

```bash
pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Required
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
APPROVED_PHONE_NUMBER=+1234567890
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Optional
USER_DISPLAY_NAME=Your Name
GOOGLE_DRIVE_DROPBOX_FOLDER_ID=
```

### 3. Set up Twilio WhatsApp

1. Go to [Twilio Console > Messaging > WhatsApp Sandbox](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn).
2. Follow the instructions to join the sandbox (send the join code from your phone).
3. Note the sandbox phone number (e.g., `whatsapp:+14155238886`).
4. Set your `TWILIO_WHATSAPP_FROM` in `.env` to this number.
5. Set `APPROVED_PHONE_NUMBER` to your personal phone number (E.164 format).

> **Tip:** For production, upgrade to a [Twilio WhatsApp Business number](https://www.twilio.com/docs/whatsapp).

### 4. Start the bridge

```bash
uv run python -m src.main
```

You should see:

```
WhatsApp-Claude Bridge
  Phone : +1234567890
  Model : claude-sonnet-4-5-20250929
  Server: http://127.0.0.1:8001
```

### 5. Expose with ngrok

In a separate terminal:

```bash
ngrok http 8001
```

Copy the HTTPS URL (e.g., `https://abc123.ngrok-free.app`).

### 6. Configure Twilio webhook

1. Go to [Twilio Console > Messaging > Settings > WhatsApp Sandbox](https://console.twilio.com/us1/develop/sms/settings/whatsapp-sandbox).
2. Set **"When a message comes in"** to: `https://abc123.ngrok-free.app/webhook` (POST).
3. Save.

### 7. Send a message!

Open WhatsApp and send a message to your Twilio sandbox number. Claude will respond!

---

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TWILIO_ACCOUNT_SID` | Yes | -- | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Yes | -- | Twilio auth token |
| `TWILIO_WHATSAPP_FROM` | Yes | `whatsapp:+14155238886` | Your Twilio WhatsApp number |
| `APPROVED_PHONE_NUMBER` | Yes | -- | Your phone number (E.164) |
| `ANTHROPIC_API_KEY` | Yes | -- | Anthropic API key |
| `SERVER_HOST` | No | `127.0.0.1` | Server bind address |
| `SERVER_PORT` | No | `8001` | Server port |
| `CONVERSATION_TIMEOUT_MINUTES` | No | `60` | Conversation timeout |
| `MAX_CONVERSATION_MESSAGES` | No | `50` | Max messages per conversation |
| `REQUIRE_APPROVAL_FOR_BASH` | No | `true` | Require approval for destructive commands |
| `APPROVAL_TIMEOUT_SECONDS` | No | `300` | Approval request timeout |
| `USER_DISPLAY_NAME` | No | *(empty)* | Your name (shown in Claude's system prompt) |
| `GOOGLE_DRIVE_DROPBOX_FOLDER_ID` | No | *(empty)* | Google Drive folder for media hosting |

---

## MCP Server Integration

The bridge automatically loads MCP servers from your Claude Code configuration (`~/.claude/settings.json`). Any MCP server you have configured in Claude Code is automatically available via WhatsApp.

### How it works

Claude can call the `mcp_call` tool with any server name from your `settings.json`:

1. **List tools:** Discover what tools a server offers.
2. **Call tool:** Execute a specific tool with arguments.

The bridge spawns MCP server processes on demand, communicates via JSON-RPC over stdio, and returns results to Claude.

### Popular MCP servers that work great with the bridge

| Server | Use case |
|--------|----------|
| **Gmail** | Read, search, send emails from WhatsApp |
| **Google Tasks** | Manage your to-do list on the go |
| **Google Sheets** | Read and update spreadsheets |
| **ElevenLabs** | Text-to-speech, transcription |
| **NotebookLM** | AI research notebooks |
| **HeyGen** | AI avatar video generation |
| **Google Drive** | Upload, search, manage files |

### Adding new MCP servers

Simply add the server to your `~/.claude/settings.json` and restart the bridge. No code changes needed.

```json
{
  "mcpServers": {
    "your-server": {
      "command": "node",
      "args": ["/path/to/server/dist/index.js"],
      "env": {
        "API_KEY": "your-key"
      }
    }
  }
}
```

---

## Media Support

### Inbound (you send media to Claude)

- **Images:** Sent as vision content blocks -- Claude can see and describe them.
- **Voice messages:** Auto-transcribed via ElevenLabs STT (falls back gracefully if unavailable).
- **Videos:** First frame extracted via ffmpeg for Claude to see.
- All media is saved to a local temp directory for further processing (e.g., uploading to Google Drive).

### Outbound (Claude sends media to you)

Claude can send images, audio, and video back to you on WhatsApp. The workflow:

1. Claude generates or locates a file (e.g., ElevenLabs TTS audio, a chart image).
2. Uploads it to a publicly accessible URL (Google Drive Dropbox folder or any HTTPS URL).
3. Sends it to you via the `send_whatsapp_media` tool.

**Setup for outbound media:**

1. Create a Google Drive folder and set sharing to "Anyone with the link can view."
2. Set `GOOGLE_DRIVE_DROPBOX_FOLDER_ID` in your `.env` to the folder ID.
3. Configure the [Google Drive MCP server](https://github.com/piotr-agier/google-drive-mcp) in your `settings.json`.

---

## Sample Use Cases

### Remote system administration

> **You:** Check if my web server is running
>
> **Claude:** *runs `curl -s localhost:3000/health`* -- Your web server is running. Health check returned 200 OK with uptime of 3 days.

### Email triage on the go

> **You:** Summarize my unread emails from today
>
> **Claude:** *calls Gmail MCP* -- You have 5 unread emails: 1) Invoice from AWS ($42.15), 2) PR review request from Alex, 3) Meeting invite for Thursday standup...

### Task management

> **You:** Add a task to buy groceries tomorrow
>
> **Claude:** *calls Google Tasks MCP* -- Done! Created task "Buy groceries" due tomorrow (Feb 1, 2026).

### Voice interaction

> **You:** *(send a voice message asking about the weather)*
>
> **Claude:** *transcribes via ElevenLabs, searches the web* -- It's currently 72F in Nairobi with partly cloudy skies. High of 78F expected today.

### Image analysis

> **You:** *(send a photo of a restaurant menu)*
>
> **Claude:** I can see the menu! Highlights: The grilled salmon ($24) looks like a good choice. The pasta section has a truffle risotto ($18) that stands out...

### Media generation

> **You:** Generate an audio greeting for my podcast intro
>
> **Claude:** *calls ElevenLabs TTS, uploads to Drive, sends audio via WhatsApp* -- Here's your podcast intro! *(audio attachment)*

### Spreadsheet operations

> **You:** What's the total in column C of my budget spreadsheet?
>
> **Claude:** *calls Google Sheets MCP* -- The total in column C (Expenses) is $3,847.50 across 23 rows.

---

## Safety & Security

### Single-user lockdown

Only the phone number in `APPROVED_PHONE_NUMBER` can interact with the bot. All other messages are silently rejected.

### Command approval flow

When Claude wants to run a destructive bash command (anything that isn't read-only), the bridge:

1. Sends you an approval request on WhatsApp with the exact command.
2. Waits for you to reply `APPROVE <id>` or `DENY <id>`.
3. Only executes if approved within the timeout window (default: 5 minutes).

Read-only commands (`ls`, `cat`, `grep`, `date`, etc.) are auto-approved.

### What's protected

- **Bash commands:** Destructive commands (rm, del, kill, etc.) require approval.
- **File writes:** Creating or overwriting files requires approval.
- **MCP calls and file reads:** Auto-approved (read-only).

---

## Project Structure

```
whatsapp-claude-bridge/
|-- .env.example          # Configuration template
|-- pyproject.toml        # Python project config (dependencies)
|-- src/
|   |-- __init__.py
|   |-- __main__.py       # Package entrypoint
|   |-- main.py           # FastAPI app, webhook, conversation loop
|   |-- config.py         # Settings from .env via pydantic-settings
|   |-- claude_client.py  # Anthropic API wrapper + system prompt
|   |-- conversation_manager.py  # SQLite-backed conversation history
|   |-- whatsapp_handler.py      # Twilio WhatsApp message sending
|   |-- media_handler.py  # Inbound media processing (images, audio, video)
|   |-- models.py         # SQLModel database models
|   |-- tools/
|   |   |-- __init__.py
|   |   |-- base.py       # BaseTool abstract class
|   |   |-- bash_tool.py  # Shell command execution
|   |   |-- file_tool.py  # File read/write tools
|   |   |-- web_search_tool.py   # Web search via DuckDuckGo
|   |   |-- mcp_tool.py   # MCP server bridge (JSON-RPC over stdio)
|   |   |-- send_media_tool.py   # Outbound WhatsApp media
```

---

## Customization

### System prompt

The bridge builds its system prompt dynamically from:

1. **Base prompt** (in `claude_client.py`) -- defines capabilities, constraints, and tool descriptions.
2. **CLAUDE.md** (from `~/.claude/CLAUDE.md`) -- your personal instructions, appended automatically.

This means any instructions you put in your `CLAUDE.md` for Claude Code also apply to WhatsApp conversations.

### Adding custom tools

Create a new tool by subclassing `BaseTool`:

```python
from src.tools.base import BaseTool

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"

    @property
    def description(self) -> str:
        return "Does something useful"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "A parameter"}
            },
            "required": ["param"]
        }

    async def execute(self, param: str, **kwargs) -> str:
        return f"Result: {param}"
```

Then register it in `main.py`:

```python
from .tools.my_tool import MyTool
tools = [..., MyTool()]
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No response on WhatsApp | Check ngrok is running and webhook URL is set in Twilio |
| "unauthorized" in logs | Verify `APPROVED_PHONE_NUMBER` matches your phone exactly (E.164) |
| Claude errors | Check `ANTHROPIC_API_KEY` is valid and has credits |
| MCP tools not working | Ensure `~/.claude/settings.json` has the server configured |
| Media not sending | Verify `GOOGLE_DRIVE_DROPBOX_FOLDER_ID` is set and folder is shared publicly |
| Voice transcription fails | ElevenLabs MCP server must be configured in settings.json |
| Port already in use | Kill the existing process: `lsof -ti:8001 \| xargs kill` (Linux/Mac) |

### Viewing logs

The bridge logs everything to stdout. Look for these prefixes:

- `[WEBHOOK]` -- incoming messages
- `[PROCESS]` -- Claude conversation loop
- `[MCP]` -- MCP server calls
- `[MEDIA]` -- media processing
- `[WHATSAPP]` -- outbound messages

---

## Contributing

Contributions are welcome! Some ideas:

- **Multi-user support** -- per-user conversations with separate auth
- **Webhook queue** -- handle concurrent messages more gracefully
- **More media types** -- document attachments (PDF, DOCX)
- **Streaming responses** -- send partial replies as Claude generates
- **Web UI** -- admin dashboard for monitoring conversations

---

## License

MIT License -- see [LICENSE](LICENSE) for details.

---

## Acknowledgments

Built with:

- [Anthropic Claude API](https://docs.anthropic.com) -- the AI brain
- [Twilio](https://www.twilio.com) -- WhatsApp messaging
- [FastAPI](https://fastapi.tiangolo.com) -- web framework
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io) -- tool integration
- [uv](https://docs.astral.sh/uv/) -- fast Python package manager
