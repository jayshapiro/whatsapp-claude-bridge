from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class Conversation(SQLModel, table=True):
    """A conversation thread with a phone number."""

    id: Optional[int] = Field(default=None, primary_key=True)
    phone_number: str = Field(index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True)


class Message(SQLModel, table=True):
    """A single message inside a conversation."""

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id", index=True)
    role: str  # "user", "assistant", "tool_use", "tool_result"
    content: str  # text or JSON-serialised content blocks
    created_at: datetime = Field(default_factory=datetime.utcnow)
    tool_use_id: Optional[str] = None
    tool_name: Optional[str] = None


class PendingApproval(SQLModel, table=True):
    """An approval request waiting for user response."""

    id: Optional[int] = Field(default=None, primary_key=True)
    approval_id: str = Field(unique=True, index=True)
    conversation_id: int = Field(foreign_key="conversation.id")
    tool_name: str
    tool_input: str  # JSON string
    description: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    status: str = Field(default="pending")  # pending / approved / denied / expired
    responded_at: Optional[datetime] = None
