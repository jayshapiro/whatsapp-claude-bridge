"""
Send WhatsApp Media Tool
=========================
Allows Claude to send images, audio, and video back to the user via WhatsApp.

The media must be at a publicly accessible HTTPS URL (e.g. Google Drive Dropbox).
"""

from typing import Any, Dict, Optional

from .base import BaseTool


class SendWhatsAppMediaTool(BaseTool):
    """Send an image, audio clip, or video to the user via WhatsApp."""

    @property
    def name(self) -> str:
        return "send_whatsapp_media"

    @property
    def description(self) -> str:
        return (
            "Send a media file (image, audio, video) to the user on WhatsApp.\n\n"
            "The media_url must be a publicly accessible HTTPS URL. For files on "
            "Google Drive, use the direct download format:\n"
            "  https://drive.google.com/uc?export=download&id=<FILE_ID>\n\n"
            "You can include an optional caption that appears with the media.\n\n"
            "WORKFLOW:\n"
            "1. Generate or locate the file (e.g. ElevenLabs TTS, image on disk).\n"
            "2. Upload it to the Google Drive Dropbox folder via mcp_call → google-drive → uploadFile.\n"
            "3. Call this tool with the public URL and optional caption.\n\n"
            "NOTE: This tool sends to the current WhatsApp user automatically."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "media_url": {
                    "type": "string",
                    "description": (
                        "Public HTTPS URL of the media file. "
                        "For Google Drive files, use: "
                        "https://drive.google.com/uc?export=download&id=<FILE_ID>"
                    ),
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption text to display with the media",
                },
            },
            "required": ["media_url"],
        }

    async def execute(self, media_url: str, caption: str = "", **kwargs) -> str:
        """Send media to the user. The WhatsApp handler is injected at runtime."""
        # The actual sending is handled by main.py which intercepts this tool's
        # result and calls whatsapp.send_media(). We return a structured marker
        # that main.py will parse.
        import json
        return json.dumps({
            "__media_send__": True,
            "media_url": media_url,
            "caption": caption or "",
        })
