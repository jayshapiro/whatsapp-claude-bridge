# WhatsApp-Claude Bridge

> **Chat with Claude from WhatsApp -- by text or voice call** -- with tool execution, media support, MCP integration, and conversation memory.

A self-hosted bridge that connects WhatsApp to Anthropic's Claude API via Twilio, giving you a powerful AI assistant in your pocket. Send text, images, voice messages, and video -- and receive intelligent responses, generated audio, images, and more -- all through WhatsApp. Or just **call the number and talk to Claude directly** using Twilio's ConversationRelay for real-time voice conversations.

---

## Features

| Feature | Description |
|---------|-------------|
| **Two-way chat** | Full conversational Claude via WhatsApp with persistent memory |
| **Voice calling** | Call the number and talk to Claude in real-time via Twilio ConversationRelay |
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

### Text messaging

```
WhatsApp (your phone)
    |
    v
Twilio (webhook POST)
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

### Voice calling (ConversationRelay)

```
You speak into your phone
    |
    v
Twilio receives the call, returns TwiML from POST /voice
    |
    v
ConversationRelay opens WebSocket to /ws
    |
    +-- Twilio STT (speech-to-text, cloud-side)
    |       |
    |       v
    |   Bridge receives transcribed text via WebSocket
    |       |
    |       v
    |   Claude API processes text (with read-only tools)
    |       |
    |       v
    |   Bridge sends reply text back over WebSocket
    |       |
    |       v
    +-- ElevenLabs TTS (text-to-speech, via ConversationRelay)
            |
            v
        You hear Claude's response
```

**How text messaging works:**

1. You send a WhatsApp message to your Twilio number.
2. Twilio forwards it to the bridge's `/webhook` endpoint via ngrok.
3. The bridge sends it to Claude with your conversation history.
4. Claude can call tools (bash, files, MCP servers, web search) and the bridge executes them.
5. The final response is sent back to you on WhatsApp via Twilio.

**How voice calling works:**

1. You call your Twilio number (phone call, not WhatsApp voice note).
2. Twilio hits the bridge's `/voice` endpoint, which returns TwiML pointing to a ConversationRelay WebSocket.
3. Twilio opens a persistent WebSocket connection to `/ws` on the bridge.
4. Twilio transcribes your speech to text (cloud STT) and sends the transcript over the WebSocket.
5. The bridge sends the transcript to Claude, which can call read-only tools (bash, files, web search, MCP).
6. Claude's text response is sent back over the WebSocket.
7. ConversationRelay converts the text to speech using ElevenLabs TTS and plays it back to you.
8. The call stays open -- you keep talking, Claude keeps responding, until you hang up.

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

## Voice Calling (Twilio ConversationRelay)

The bridge supports full real-time voice calls, powered by [Twilio ConversationRelay](https://www.twilio.com/docs/voice/conversation-relay). You call your Twilio number, speak naturally, and hear Claude respond -- with access to tools, MCP servers, and web search, all hands-free.

### How ConversationRelay works

ConversationRelay is a Twilio product that bridges a phone call to a WebSocket. It handles the hard parts (speech-to-text and text-to-speech) so the bridge only deals with text. The flow:

1. **Inbound call** arrives at Twilio. Twilio hits `POST /voice` on the bridge.
2. The bridge returns **TwiML** that tells Twilio to open a ConversationRelay session, pointing to the bridge's WebSocket endpoint (`wss://<ngrok-url>/ws`).
3. Twilio opens the WebSocket and sends a `setup` message with call metadata (session ID, call SID, caller number).
4. The bridge generates a **dynamic greeting** using Claude (each call gets a unique opening line) and sends it back as text. ConversationRelay converts it to speech.
5. When you speak, Twilio's **cloud STT** transcribes your speech and sends the text to the bridge as a `prompt` message.
6. The bridge sends the text to Claude (with conversation history and tools). Claude may call tools and then produces a text response.
7. The bridge sends Claude's response back as text, split into **sentence-sized chunks** for natural TTS pacing.
8. ConversationRelay converts each chunk to speech using **ElevenLabs TTS** and streams the audio to the caller.
9. Steps 5-8 repeat until you hang up.

### Voice personality

Voice calls use a separate system prompt with a character called **Holly** -- a deadpan, drily sarcastic British AI assistant (a blend of Holly from Red Dwarf, TARS from Interstellar, and HAL 9000 minus the homicidal tendencies). The voice prompt enforces:

- Short responses (under 100 words when possible)
- No markdown, bullet points, or code blocks
- Natural speech patterns and filler words
- Numbers spoken as words ("twenty three", not "23")
- Abbreviations spelled out on first use

You can change the personality by editing `_VOICE_SYSTEM_PROMPT` in `src/voice_handler.py`.

### Tools available during voice calls

Voice calls have access to a **read-only subset** of tools:

| Tool | Voice behavior |
|------|---------------|
| `execute_bash` | Read-only commands auto-approved. Destructive commands **refused** (no approval flow possible mid-call). |
| `read_file` | Available, auto-approved |
| `web_search` | Available, auto-approved |
| `mcp_call` | Available (Gmail, Tasks, Sheets, etc.) |
| `write_file` | **Not available** during voice calls |
| `send_whatsapp_media` | **Not available** during voice calls |

When Claude needs to call a tool, the bridge sends a brief hold message ("Let me look that up for you") so you know something is happening. Tool results are truncated to 2,000 characters and summarized conversationally.

There is a **5 tool-turn limit** per voice exchange to keep responses snappy.

### Setting up voice calling

Voice calling requires additional Twilio configuration beyond what's needed for WhatsApp messaging.

#### 1. Get a Twilio phone number with voice capability

You need a Twilio phone number that supports **voice calls** (not just SMS/WhatsApp). In the [Twilio Console](https://console.twilio.com):

1. Go to **Phone Numbers > Manage > Buy a number**.
2. Select a number with **Voice** capability.
3. Or use your existing number if it already supports voice.

#### 2. Enable ConversationRelay

ConversationRelay is a Twilio product currently available as part of Twilio's Voice platform. Check the [ConversationRelay documentation](https://www.twilio.com/docs/voice/conversation-relay) for current availability and any required account flags.

#### 3. Configure the voice webhook

In the Twilio Console, configure your phone number's **voice** webhook:

1. Go to **Phone Numbers > Manage > Active Numbers** and select your number.
2. Under **Voice Configuration**, set **"A call comes in"** to: `https://<your-ngrok-url>/voice` (HTTP POST).
3. Save.

This is a **separate webhook** from the WhatsApp messaging webhook (`/webhook`). You need both configured:
- **WhatsApp webhook:** `https://<ngrok-url>/webhook` (POST)
- **Voice webhook:** `https://<ngrok-url>/voice` (POST)

#### 4. ElevenLabs TTS (required for voice)

ConversationRelay uses **ElevenLabs as the TTS provider**. This is configured in the TwiML response (in `voice_handler.py`). The current configuration uses:

- **TTS Provider:** ElevenLabs
- **Voice ID:** `Fahco4VZzobUeiPqni1S` (can be changed in `build_voice_twiml()`)
- **Interruptible:** Yes (you can interrupt Claude mid-sentence)
- **DTMF detection:** Enabled

For ElevenLabs TTS to work through ConversationRelay, you need an ElevenLabs account connected to your Twilio account. See [Twilio's ConversationRelay TTS documentation](https://www.twilio.com/docs/voice/conversation-relay) for setup instructions.

#### 5. Test it

Call your Twilio phone number. You should hear Holly greet you. Speak naturally and Claude will respond.

### Costs

Voice calling involves multiple billable services. You should understand the cost structure before enabling it.

| Service | What it costs | Approximate rate |
|---------|--------------|-----------------|
| **Twilio Voice** | Per-minute inbound call charges | ~$0.0085/min (US local numbers; varies by country and number type) |
| **Twilio ConversationRelay** | Per-minute charge on top of base voice | Check [Twilio pricing](https://www.twilio.com/en-us/voice/pricing/us) for current ConversationRelay rates |
| **Twilio phone number** | Monthly rental for the phone number | ~$1.15/month (US local); varies by country |
| **ElevenLabs TTS** | Per-character text-to-speech via ConversationRelay | Depends on your ElevenLabs plan; billed through Twilio's integration |
| **Twilio STT** | Speech-to-text (included in ConversationRelay) | Bundled with ConversationRelay per-minute pricing |
| **Anthropic Claude API** | Per-token for Claude messages + tool use | Depends on model; see [Anthropic pricing](https://www.anthropic.com/pricing) |
| **ngrok** | Tunnel for exposing localhost | Free tier available; paid plans for reserved domains |

**A typical 5-minute voice call** will incur costs from Twilio (voice + ConversationRelay minutes), ElevenLabs (TTS characters for each response), and Anthropic (Claude API tokens for each exchange plus any tool calls). Exact costs depend on how much you talk, how long Claude's responses are, and how many tool calls are made.

**Cost management tips:**
- Voice calls with tool use (web search, MCP calls) will cost more in Claude API tokens than simple conversation.
- The 5 tool-turn limit per exchange helps cap API costs per utterance.
- Short, direct questions get short responses, keeping TTS and API costs low.
- Monitor your Twilio, ElevenLabs, and Anthropic dashboards regularly.

### Risks and limitations

**Latency.** There are multiple round-trips in the voice pipeline: your speech is sent to Twilio's cloud for STT, the transcript goes to the bridge, the bridge calls Claude's API (and potentially tools), then the response goes back through ConversationRelay to ElevenLabs for TTS. End-to-end latency is typically 2-5 seconds per exchange, depending on Claude's response time and whether tools are called. This is noticeable but functional for conversational use.

**No destructive commands.** The voice handler intentionally refuses any command that would require the text-based approval flow. There's no way to approve a destructive bash command during a voice call. If you need to run something that modifies your system, use text chat.

**No file writes or media sending.** Voice calls don't have access to `write_file` or `send_whatsapp_media`. Voice is read-only by design.

**STT accuracy.** Twilio's speech-to-text is generally accurate but can struggle with technical jargon, code identifiers, file paths, or uncommon proper nouns. The voice prompt instructs Claude to ask for clarification when speech is unclear.

**Session isolation.** Voice calls maintain their own message history (last 20 messages), separate from your WhatsApp text conversation. Context doesn't carry over between the two.

**Single concurrent call.** The bridge doesn't guard against multiple simultaneous voice calls. If two calls arrive at the same time, both would connect but may interfere with each other. The single-user design means this is unlikely in practice.

**ngrok dependency.** The WebSocket connection for ConversationRelay goes through ngrok. If ngrok drops or the URL changes, active voice calls will disconnect. For production use, consider a stable tunnel or direct server hosting.

**ElevenLabs dependency.** If ElevenLabs is down or your account runs out of credits, ConversationRelay won't be able to convert Claude's text responses to speech. The call will still connect but the caller won't hear responses.

### Advantages over text chat

- **Hands-free.** Query your system, check emails, manage tasks, search the web -- all by voice while driving, cooking, or walking.
- **Speed of input.** Speaking is faster than typing on a phone keyboard, especially for complex queries.
- **Natural interaction.** The conversational voice format (with interruption support) feels more natural than async text messaging.
- **Tool access.** Unlike a basic voice assistant, Claude can actually execute commands, query your MCP servers, search the web, and read files on your machine -- all during the call.
- **Dynamic personality.** Each call gets a unique greeting. The voice persona adds character without sacrificing capability.

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

### Voice message (WhatsApp)

> **You:** *(send a voice message asking about the weather)*
>
> **Claude:** *transcribes via ElevenLabs, searches the web* -- It's currently 72F in Nairobi with partly cloudy skies. High of 78F expected today.

### Voice call (ConversationRelay)

> *(You call the Twilio number)*
>
> **Holly:** Oh, hello Jay. I was just sitting here contemplating the void. What can I do for you.
>
> **You:** "What's on my task list for today?"
>
> **Holly:** *calls Google Tasks MCP* -- Right. You have three tasks due today. Buy groceries, call the dentist, and finish the quarterly report. Shall I mark any of those as done, or would you like to keep pretending they will happen on their own.

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

Any personal AI agent that can run shell commands, read files, send emails, and manage your accounts on your behalf is a powerful tool -- and a potential security risk. This project takes that seriously. The security model is **not optional** -- it's structural, enforced in code, and on by default.

### Threat model

This bridge gives Claude access to your local machine (bash, files), your cloud services (via MCP), and your WhatsApp number. The main risks are:

1. **Unauthorized access** -- someone other than you interacting with the bot.
2. **Destructive commands** -- Claude (or a prompt injection attack) running `rm -rf /` or equivalent.
3. **Credential leakage** -- API keys or tokens exposed through logs, prompts, or tool output.
4. **Prompt injection** -- malicious content in emails, web pages, or tool results tricking Claude into harmful actions.
5. **Malicious tools/skills** -- a compromised MCP server or tool executing unintended actions.

Here's how each is addressed:

### Single-user lockdown

Only the phone number in `APPROVED_PHONE_NUMBER` can interact with the bot. All other messages are **silently rejected** -- no error message, no acknowledgment, nothing. This is enforced at the webhook handler level before any processing occurs.

There is no multi-user mode. There are no shared accounts. There is no admin backdoor.

### Command approval flow

When Claude wants to run a destructive bash command (anything that isn't read-only), the bridge:

1. Sends you an approval request on WhatsApp with **the exact command** that will be executed.
2. Waits for you to reply `APPROVE <id>` or `DENY <id>`.
3. Only executes if approved within the timeout window (default: 5 minutes).
4. If the timeout expires, the command is **denied automatically**.

Read-only commands (`ls`, `cat`, `grep`, `date`, etc.) are auto-approved. The classification is based on a conservative regex allowlist -- if a command doesn't match a known safe pattern, it requires approval.

**During voice calls, destructive commands are refused entirely.** There is no approval flow available mid-call. If Claude tries to run something dangerous, the voice handler returns a refusal message and tells the caller to use text chat instead.

### What's protected

| Action | Text chat | Voice call |
|--------|----------|------------|
| Read-only bash (`ls`, `cat`, `grep`) | Auto-approved | Auto-approved |
| Destructive bash (`rm`, `kill`, `git push`) | Requires approval | **Refused** |
| File reads | Auto-approved | Auto-approved |
| File writes | Requires approval | **Not available** |
| MCP tool calls | Auto-approved | Auto-approved |
| Web search | Auto-approved | Auto-approved |
| Send media to WhatsApp | Auto-approved | **Not available** |

### Credential and secret handling

- **No credentials are stored in the codebase.** All secrets (API keys, Twilio tokens) live in `.env`, which is `.gitignore`d.
- **No credentials are logged.** The bridge does not log message content at the level where API keys would appear.
- **The system prompt explicitly warns Claude** not to expose secrets, API keys, or credentials in responses.
- **MCP server credentials** are loaded from `~/.claude/settings.json` (your existing Claude Code config) and passed as environment variables to subprocess -- never exposed to Claude's context.

### Prompt injection surface

Like any AI agent connected to external data sources (email, web pages, documents), this bridge is exposed to prompt injection -- malicious instructions embedded in content that Claude processes. The bridge mitigates this through:

- **Approval flow as a firewall.** Even if a prompt injection tricks Claude into wanting to run `rm -rf /`, the command goes through the approval flow. You see the exact command on WhatsApp and must explicitly approve it. The injection can fool Claude but it cannot fool you.
- **Voice calls are read-only.** The most dangerous attack surface (system-modifying commands) is completely unavailable during voice calls.
- **Tool result truncation.** Voice call tool results are capped at 2,000 characters, limiting the surface area for injection via tool output.
- **No community skills or plugin marketplace.** The only tools available are the ones you explicitly configure: the built-in tools (bash, files, web search, media) and your own MCP servers from `settings.json`. There is no mechanism for third parties to inject skills, plugins, or tool definitions.

### MCP server trust model

The bridge loads MCP servers from your `~/.claude/settings.json`. This means:

- **You control which servers are available.** No server runs unless you configured it.
- **Each server runs as a local subprocess** with the credentials you provided. Servers don't share credentials with each other or with Claude.
- **There is no auto-discovery, no marketplace, and no remote loading.** Adding a new MCP server requires you to edit a local config file and restart the bridge.

If you add a malicious or compromised MCP server, that's a risk -- but it's a risk you opted into explicitly, not one that was injected via a supply chain attack.

### What this project does NOT do

For clarity on scope and limitations:

- **No account creation.** The bridge never creates accounts on your behalf.
- **No credential storage beyond `.env`.** There is no password vault, no token database.
- **No outbound network calls except to APIs you configured** (Anthropic, Twilio, and your MCP servers).
- **No telemetry, analytics, or phoning home.** The bridge does not report usage to anyone.
- **No persistent background execution.** When you stop the bridge, it stops. There are no scheduled tasks, no cron jobs, no daemons that survive a restart unless you set them up yourself.

---

## Project Structure

```
whatsapp-claude-bridge/
|-- .env.example          # Configuration template
|-- pyproject.toml        # Python project config (dependencies)
|-- src/
|   |-- __init__.py
|   |-- __main__.py       # Package entrypoint
|   |-- main.py           # FastAPI app, webhooks (/webhook, /voice, /ws)
|   |-- config.py         # Settings from .env via pydantic-settings
|   |-- claude_client.py  # Anthropic API wrapper + system prompt
|   |-- conversation_manager.py  # SQLite-backed conversation history
|   |-- whatsapp_handler.py      # Twilio WhatsApp message sending
|   |-- media_handler.py  # Inbound media processing (images, audio, video)
|   |-- voice_handler.py  # Twilio ConversationRelay voice calling
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
| Voice call connects but no audio | Check ElevenLabs TTS integration with Twilio; verify voice ID in `voice_handler.py` |
| Voice call doesn't connect | Ensure `/voice` webhook is set on your Twilio number's **Voice** config (not messaging) |
| "WebSocket disconnected" in logs | ngrok may have dropped; restart ngrok and update the Twilio voice webhook URL |
| Long silence during voice call | Claude is calling tools; the "Let me look that up" hold message should play. Check tool execution logs. |
| Port already in use | Kill the existing process: `lsof -ti:8001 \| xargs kill` (Linux/Mac) |

### Viewing logs

The bridge logs everything to stdout. Look for these prefixes:

- `[WEBHOOK]` -- incoming messages
- `[PROCESS]` -- Claude conversation loop
- `[MCP]` -- MCP server calls
- `[MEDIA]` -- media processing
- `[WHATSAPP]` -- outbound messages
- `[VOICE]` -- voice call events (setup, transcripts, tool calls, errors)

---

## Contributing

Contributions are welcome! Some ideas:

- **Multi-user support** -- per-user conversations with separate auth
- **Shared context between voice and text** -- carry conversation state across modalities
- **Voice call recording and transcripts** -- save call history alongside text conversations
- **Configurable TTS voice** -- pick ElevenLabs voice via `.env` instead of hardcoding
- **Webhook queue** -- handle concurrent messages more gracefully
- **More media types** -- document attachments (PDF, DOCX)
- **Streaming responses** -- send partial replies as Claude generates
- **Web UI** -- admin dashboard for monitoring conversations

---

## License

MIT License -- see [LICENSE](LICENSE) for details.

---

## About

This project was built from the ground up and open-sourced by **[Jay Shapiro](https://www.linkedin.com/in/jayshapiro)**, founder of **[Mzee.ai](https://mzee.ai)** -- an Africa-based #AIforGood company that works with NGOs and non-profit foundations to solve real-world problems through AI.

With more than 3 billion WhatsApp users around the world -- many of them in the Global South -- we believe that voice-based AI interfaces over WhatsApp have the potential to bring cutting-edge AI tools to the masses, including populations with lower literacy rates. A farmer in rural Kenya, a health worker in Bangladesh, a small business owner in Brazil -- none of them need to read or type to have a conversation. Voice is the most natural interface there is, and WhatsApp is already on their phone.

That conviction is what drove the addition of real-time voice calling to this bridge. Text chat is powerful, but voice calling over WhatsApp removes the last barrier: literacy itself.

---

## Acknowledgments

Built with:

- [Anthropic Claude API](https://docs.anthropic.com) -- the AI brain
- [Twilio](https://www.twilio.com) -- WhatsApp messaging + voice calling
- [Twilio ConversationRelay](https://www.twilio.com/docs/voice/conversation-relay) -- real-time voice-to-text-to-voice bridge
- [ElevenLabs](https://elevenlabs.io) -- text-to-speech for voice calls + speech-to-text for voice messages
- [FastAPI](https://fastapi.tiangolo.com) -- web framework
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io) -- tool integration
- [uv](https://docs.astral.sh/uv/) -- fast Python package manager
