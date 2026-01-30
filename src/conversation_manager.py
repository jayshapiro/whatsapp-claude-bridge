import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from .config import settings
from .models import Conversation, Message


class ConversationManager:
    """Persist and retrieve conversation history in SQLite."""

    def __init__(self, engine) -> None:
        self.engine = engine

    # ── conversations ────────────────────────────────────────────

    def get_or_create(self, phone_number: str) -> Conversation:
        with Session(self.engine) as session:
            stmt = select(Conversation).where(
                Conversation.phone_number == phone_number,
                Conversation.is_active == True,  # noqa: E712
            )
            conv = session.exec(stmt).first()

            # expire stale conversation
            if conv:
                timeout = timedelta(minutes=settings.conversation_timeout_minutes)
                if datetime.utcnow() - conv.last_activity > timeout:
                    conv.is_active = False
                    session.add(conv)
                    session.commit()
                    conv = None

            if conv is None:
                conv = Conversation(
                    phone_number=phone_number,
                    started_at=datetime.utcnow(),
                    last_activity=datetime.utcnow(),
                )
                session.add(conv)
                session.commit()
                session.refresh(conv)

            return conv

    def reset(self, phone_number: str) -> None:
        with Session(self.engine) as session:
            stmt = select(Conversation).where(
                Conversation.phone_number == phone_number,
                Conversation.is_active == True,  # noqa: E712
            )
            conv = session.exec(stmt).first()
            if conv:
                conv.is_active = False
                session.add(conv)
                session.commit()

    # ── messages ─────────────────────────────────────────────────

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: Any,
        tool_use_id: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> None:
        # Serialize list/dict content to JSON string for storage
        if isinstance(content, (list, dict)):
            stored = json.dumps(content)
        else:
            stored = content

        with Session(self.engine) as session:
            session.add(
                Message(
                    conversation_id=conversation_id,
                    role=role,
                    content=stored,
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                )
            )
            conv = session.get(Conversation, conversation_id)
            if conv:
                conv.last_activity = datetime.utcnow()
                session.add(conv)
            session.commit()

    def add_assistant_blocks(
        self, conversation_id: int, content_blocks: list
    ) -> None:
        """Store the raw assistant content-blocks as JSON."""
        self.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=json.dumps(
                [self._block_to_dict(b) for b in content_blocks]
            ),
        )

    def get_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        """Return message history formatted for the Anthropic API.

        Key constraint: each tool_result block must appear in a "user" message
        immediately after the "assistant" message that contained the
        corresponding tool_use block.  We group consecutive tool_result rows
        into one "user" message and strip orphaned tool results.
        """
        with Session(self.engine) as session:
            stmt = (
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
            rows = list(session.exec(stmt).all())

        # trim to the most recent N messages
        if len(rows) > settings.max_conversation_messages:
            rows = rows[-settings.max_conversation_messages :]

        messages: List[Dict[str, Any]] = []
        # Collect tool_use IDs present in the last assistant message
        pending_tool_ids: set = set()

        for row in rows:
            if row.role == "user":
                pending_tool_ids.clear()
                # Content may be plain text or JSON-encoded blocks (media)
                try:
                    parsed = json.loads(row.content)
                    if isinstance(parsed, list):
                        content = parsed
                    else:
                        content = row.content
                except (json.JSONDecodeError, TypeError):
                    content = row.content
                messages.append({"role": "user", "content": content})

            elif row.role == "assistant":
                pending_tool_ids.clear()
                try:
                    blocks = json.loads(row.content)
                except (json.JSONDecodeError, TypeError):
                    blocks = row.content
                # Track which tool_use IDs this assistant message contains
                if isinstance(blocks, list):
                    for b in blocks:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            pending_tool_ids.add(b.get("id"))
                messages.append({"role": "assistant", "content": blocks})

            elif row.role == "tool_result":
                # Only include if this tool_use_id was in the last assistant msg
                if row.tool_use_id not in pending_tool_ids:
                    continue  # orphaned tool result — skip

                result_block = {
                    "type": "tool_result",
                    "tool_use_id": row.tool_use_id,
                    "content": row.content,
                }
                # Merge into previous user message if it's already a tool_result list
                if (
                    messages
                    and messages[-1]["role"] == "user"
                    and isinstance(messages[-1]["content"], list)
                    and messages[-1]["content"]
                    and isinstance(messages[-1]["content"][0], dict)
                    and messages[-1]["content"][0].get("type") == "tool_result"
                ):
                    messages[-1]["content"].append(result_block)
                else:
                    messages.append(
                        {"role": "user", "content": [result_block]}
                    )

        # Final safety: ensure alternating user/assistant roles
        # Strip any leading assistant messages (API requires user first)
        while messages and messages[0]["role"] != "user":
            messages.pop(0)

        return messages

    # ── helpers ───────────────────────────────────────────────────

    @staticmethod
    def _block_to_dict(block) -> dict:
        """Convert an Anthropic content-block object to a plain dict."""
        if hasattr(block, "model_dump"):
            return block.model_dump()
        if isinstance(block, dict):
            return block
        return {"type": "text", "text": str(block)}
