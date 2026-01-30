import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Ensure .env is loaded from the project root
_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"

# Force .env values to override empty OS environment variables
load_dotenv(_env_file, override=True)


class Settings(BaseSettings):
    # Twilio
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_from: str = "whatsapp:+14155238886"

    # Authorization
    approved_phone_number: str

    # Anthropic
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 4096

    # Server
    server_host: str = "127.0.0.1"
    server_port: int = 8001

    # Database
    database_url: str = f"sqlite:///{_project_root / 'conversations.db'}"

    # Conversation
    conversation_timeout_minutes: int = 60
    max_conversation_messages: int = 50

    # Security
    require_approval_for_bash: bool = True
    approval_timeout_seconds: int = 300

    # WhatsApp
    max_message_length: int = 1600

    model_config = {
        "env_file": str(_env_file),
        "env_file_encoding": "utf-8",
    }


settings = Settings()
