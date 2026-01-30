"""
WhatsApp-Claude Bridge
======================
Two-way WhatsApp <-> Claude chat with bash/file tools and approval flow.

Start with:  uv run python -m src.main
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlmodel import SQLModel, Session, create_engine, select

from .config import settings
from .models import Conversation, Message, PendingApproval  # noqa: F401 (registers tables)
from .claude_client import ClaudeClient
from .conversation_manager import ConversationManager
from .whatsapp_handler import WhatsAppHandler
from .media_handler import process_inbound_media
from .tools.bash_tool import BashTool
from .tools.file_tool import FileReadTool, FileWriteTool
from .tools.web_search_tool import WebSearchTool
from .tools.mcp_tool import MCPBridgeTool

# ── Initialise components ────────────────────────────────────────

app = FastAPI(title="WhatsApp-Claude Bridge")

engine = create_engine(settings.database_url, echo=False)
SQLModel.metadata.create_all(engine)

tools = [BashTool(), FileReadTool(), FileWriteTool(), WebSearchTool(), MCPBridgeTool()]
claude = ClaudeClient(tools=tools)
conversations = ConversationManager(engine)
whatsapp = WhatsAppHandler()

# guard against concurrent processing per conversation
_busy: dict[int, bool] = {}

MAX_TOOL_TURNS = 10


# ── Routes ───────────────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "running", "service": "WhatsApp-Claude Bridge"}


@app.get("/webhook")
async def webhook_verify():
    return {"status": "ok", "message": "Webhook endpoint ready"}


@app.post("/webhook")
async def webhook(request: Request):
    form = await request.form()

    # ── debug: log everything Twilio sends ──
    print("[WEBHOOK POST] All form fields:")
    for key, value in form.items():
        print(f"  {key} = {value}")

    from_raw = form.get("From", "")
    body = (form.get("Body") or "").strip()
    status = form.get("MessageStatus")

    # ignore status-only callbacks
    if status and not body:
        print(f"[STATUS CALLBACK] {status} - ignoring")
        return JSONResponse({"status": "ok"})

    from_number = from_raw.replace("whatsapp:", "")
    print(f"[FROM] raw={from_raw!r} -> cleaned={from_number!r}")
    print(f"[EXPECTED] {settings.approved_phone_number!r}")

    # ── security: only the authorised number ──
    if from_number != settings.approved_phone_number:
        print(f"[REJECT] {from_number!r} != {settings.approved_phone_number!r}")
        return JSONResponse({"status": "unauthorized"})

    print(f"[MSG] {from_number}: {body[:80]}")

    # ── extract media attachments ──
    num_media = int(form.get("NumMedia", "0"))
    media_items = []
    for i in range(num_media):
        url = form.get(f"MediaUrl{i}")
        ct = form.get(f"MediaContentType{i}", "application/octet-stream")
        if url:
            media_items.append({"url": url, "content_type": ct})
            print(f"[MEDIA] Attachment {i}: {ct} -> {url[:80]}")

    # ── special commands ──
    upper = body.upper()

    if upper == "/RESET":
        conversations.reset(from_number)
        whatsapp.send_message(from_number, "Conversation reset. Starting fresh!")
        return JSONResponse({"status": "ok"})

    if upper.startswith("APPROVE ") or upper.startswith("DENY "):
        _handle_approval(from_number, body)
        return JSONResponse({"status": "ok"})

    # ── normal message -> Claude ──
    # run in background so Twilio gets a quick 200
    print(f"[WEBHOOK] Creating _process task for: {body[:60]}", flush=True)
    task = asyncio.ensure_future(_process(from_number, body, media_items))
    task.add_done_callback(_task_done)
    print(f"[WEBHOOK] Task created: {task!r}", flush=True)
    return JSONResponse({"status": "ok"})


def _task_done(task: asyncio.Task) -> None:
    """Log any unhandled exception from the background task."""
    try:
        exc = task.exception()
        if exc:
            import traceback
            print(f"[TASK ERROR] Unhandled exception in _process:")
            traceback.print_exception(type(exc), exc, exc.__traceback__)
    except asyncio.CancelledError:
        pass


# ── Approval handling ────────────────────────────────────────────

def _handle_approval(from_number: str, body: str) -> None:
    parts = body.upper().split(maxsplit=1)
    if len(parts) != 2:
        whatsapp.send_message(from_number, "Invalid format. Use: APPROVE <id> or DENY <id>")
        return

    action, approval_id = parts
    new_status = "approved" if action == "APPROVE" else "denied"

    with Session(engine) as session:
        stmt = select(PendingApproval).where(
            PendingApproval.approval_id == approval_id,
            PendingApproval.status == "pending",
        )
        approval = session.exec(stmt).first()

        if not approval:
            whatsapp.send_message(from_number, f"Approval {approval_id} not found or already handled.")
            return

        if datetime.utcnow() > approval.expires_at:
            approval.status = "expired"
            session.add(approval)
            session.commit()
            whatsapp.send_message(from_number, f"Approval {approval_id} has expired.")
            return

        approval.status = new_status
        approval.responded_at = datetime.utcnow()
        session.add(approval)
        session.commit()

    icon = "\u2705" if new_status == "approved" else "\u274c"
    whatsapp.send_message(from_number, f"{icon} Request {approval_id} {new_status}.")


# ── Media processing ──────────────────────────────────────────────

async def _build_user_content(text: str, media_items: list) -> str | list:
    """Build user message content: plain string or list of content blocks.

    If there's no media, returns the plain text string (unchanged behaviour).
    If there is media, returns a list of content blocks for the Claude API.
    """
    if not media_items:
        return text

    blocks = []

    # Process each media attachment
    for item in media_items:
        media_blocks = await process_inbound_media(
            item["url"], item["content_type"], text
        )
        blocks.extend(media_blocks)

    # Add the text message (may be empty for media-only messages)
    if text:
        blocks.append({"type": "text", "text": text})
    elif not any(b.get("type") == "text" for b in blocks):
        # No text and no text blocks from media processing — add a prompt
        blocks.append({"type": "text", "text": "[The user sent this media without a caption.]"})

    return blocks


# ── Claude conversation loop ─────────────────────────────────────

async def _process(from_number: str, text: str, media_items: list | None = None) -> None:
    import sys
    print(f"[PROCESS] Starting for {from_number}: {text[:60]}", flush=True)
    conv = conversations.get_or_create(from_number)
    print(f"[PROCESS] Conversation ID: {conv.id}, busy keys: {list(_busy.keys())}", flush=True)

    if conv.id in _busy:
        print(f"[PROCESS] BLOCKED - conv {conv.id} is busy, sending wait message", flush=True)
        whatsapp.send_message(from_number, "Please wait for the previous request to finish...")
        return

    _busy[conv.id] = True
    try:
        # Build user content blocks (text + any media)
        user_content = await _build_user_content(text, media_items or [])

        # store user message
        conversations.add_message(conv.id, "user", user_content)
        messages = conversations.get_messages(conv.id)
        print(f"[PROCESS] Sending {len(messages)} messages to Claude...", flush=True)

        turns = 0
        ack_sent = False  # only send "working on it" once
        while turns < MAX_TOOL_TURNS:
            turns += 1
            print(f"[PROCESS] Turn {turns}...", flush=True)
            response = await asyncio.to_thread(claude.send, messages)
            print(f"[PROCESS] Claude response: stop_reason={response.stop_reason}", flush=True)

            if response.stop_reason == "end_turn":
                # extract text and send it
                reply = "".join(
                    b.text for b in response.content if b.type == "text"
                )
                if reply:
                    conversations.add_assistant_blocks(conv.id, response.content)
                    whatsapp.send_message(from_number, reply)
                break

            if response.stop_reason == "tool_use":
                # Send a quick acknowledgment on the first tool call
                if not ack_sent:
                    ack_sent = True
                    whatsapp.send_message(
                        from_number,
                        "On it Jay - give me a minute to work through that..."
                    )

                # persist assistant message FIRST (before tool results)
                conversations.add_assistant_blocks(conv.id, response.content)

                # process each tool-use block
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    name = block.name
                    inputs = block.input
                    tid = block.id

                    if claude.check_approval(name, inputs):
                        approved = await _request_approval(
                            conv.id, from_number, name, inputs
                        )
                        if approved:
                            result = await claude.execute_tool(name, inputs)
                        else:
                            result = "Denied by user."
                    else:
                        result = await claude.execute_tool(name, inputs)

                    # persist tool result
                    conversations.add_message(
                        conv.id, "tool_result", result,
                        tool_use_id=tid, tool_name=name,
                    )
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": tid, "content": result}
                    )

                # append to in-memory messages and loop
                messages.append({"role": "assistant", "content": [_block_dict(b) for b in response.content]})
                messages.append({"role": "user", "content": tool_results})
                continue

            # unexpected stop reason
            whatsapp.send_message(
                from_number, f"Unexpected stop reason: {response.stop_reason}"
            )
            break

        if turns >= MAX_TOOL_TURNS:
            whatsapp.send_message(from_number, "Reached max tool turns. Please try a simpler request.")

    except Exception as exc:
        import traceback
        print(f"[ERROR] {exc}", flush=True)
        traceback.print_exc()
        whatsapp.send_message(from_number, f"Something went wrong: {exc}")
    finally:
        print(f"[PROCESS] Done, releasing busy lock for conv {conv.id}", flush=True)
        _busy.pop(conv.id, None)


# ── Approval flow ────────────────────────────────────────────────

async def _request_approval(
    conv_id: int, phone: str, tool_name: str, tool_input: dict
) -> bool:
    aid = str(uuid.uuid4())[:8].upper()
    expires = datetime.utcnow() + timedelta(seconds=settings.approval_timeout_seconds)

    # friendly description
    if tool_name == "execute_bash":
        desc = f"Run command:\n{tool_input.get('command', '?')}"
    elif tool_name == "write_file":
        desc = f"Write file:\n{tool_input.get('file_path', '?')} ({len(tool_input.get('content', ''))} chars)"
    else:
        desc = f"Tool: {tool_name}\n{json.dumps(tool_input)[:200]}"

    with Session(engine) as session:
        session.add(
            PendingApproval(
                approval_id=aid,
                conversation_id=conv_id,
                tool_name=tool_name,
                tool_input=json.dumps(tool_input),
                description=desc,
                expires_at=expires,
            )
        )
        session.commit()

    whatsapp.send_approval_request(phone, desc, aid)

    # poll for response
    start = datetime.utcnow()
    while (datetime.utcnow() - start).total_seconds() < settings.approval_timeout_seconds:
        with Session(engine) as session:
            row = session.exec(
                select(PendingApproval).where(PendingApproval.approval_id == aid)
            ).first()
            if row and row.status != "pending":
                return row.status == "approved"
        await asyncio.sleep(2)

    # timed out
    with Session(engine) as session:
        row = session.exec(
            select(PendingApproval).where(PendingApproval.approval_id == aid)
        ).first()
        if row:
            row.status = "expired"
            session.add(row)
            session.commit()

    whatsapp.send_message(phone, f"Approval {aid} expired.")
    return False


# ── Helpers ──────────────────────────────────────────────────────

def _block_dict(block) -> dict:
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return block if isinstance(block, dict) else {"type": "text", "text": str(block)}


# ── Entrypoint ───────────────────────────────────────────────────

def main():
    import uvicorn

    print("WhatsApp-Claude Bridge")
    print(f"  Phone : {settings.approved_phone_number}")
    print(f"  Model : {settings.claude_model}")
    print(f"  Server: http://{settings.server_host}:{settings.server_port}")
    print()
    print("Expose with:  ngrok http", settings.server_port)
    print("Set Twilio webhook to:  https://<ngrok-url>/webhook  (POST)")
    print()

    uvicorn.run(
        app,
        host=settings.server_host,
        port=settings.server_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
