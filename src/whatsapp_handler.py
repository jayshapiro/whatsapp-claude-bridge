from typing import List, Optional

from twilio.rest import Client

from .config import settings


class WhatsAppHandler:
    """Send WhatsApp messages via Twilio, with automatic chunking."""

    def __init__(self) -> None:
        self.client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self.from_number = settings.twilio_whatsapp_from

    # ── public API ───────────────────────────────────────────────

    def send_message(self, to_number: str, body: str) -> List[str]:
        """Send *body* to *to_number*, splitting into chunks if needed."""
        to_number = self._normalise(to_number)
        chunks = self._chunk(body, settings.max_message_length)
        sids: List[str] = []
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                chunk = f"[{i + 1}/{len(chunks)}]\n\n{chunk}"
            msg = self.client.messages.create(
                body=chunk, from_=self.from_number, to=to_number
            )
            sids.append(msg.sid)
        return sids

    def send_media(
        self,
        to_number: str,
        media_url: str,
        body: Optional[str] = None,
    ) -> str:
        """Send a media message (image, audio, video) via WhatsApp.

        Args:
            to_number: Recipient phone number
            media_url: Public URL of the media file (must be HTTPS and publicly accessible)
            body: Optional caption text

        Returns:
            The Twilio message SID
        """
        to_number = self._normalise(to_number)
        kwargs = {
            "from_": self.from_number,
            "to": to_number,
            "media_url": [media_url],
        }
        if body:
            kwargs["body"] = body
        else:
            kwargs["body"] = ""
        msg = self.client.messages.create(**kwargs)
        print(f"[WHATSAPP] Sent media to {to_number}: {media_url[:80]}... SID={msg.sid}", flush=True)
        return msg.sid

    def send_approval_request(
        self, to_number: str, description: str, approval_id: str
    ) -> str:
        body = (
            f"\U0001f510 *APPROVAL REQUIRED*\n\n"
            f"{description}\n\n"
            f"Reply with:\n"
            f"  APPROVE {approval_id}\n"
            f"  DENY {approval_id}\n\n"
            f"\u23f1 Expires in 5 minutes"
        )
        to_number = self._normalise(to_number)
        msg = self.client.messages.create(
            body=body, from_=self.from_number, to=to_number
        )
        return msg.sid

    # ── helpers ───────────────────────────────────────────────────

    @staticmethod
    def _normalise(number: str) -> str:
        return number if number.startswith("whatsapp:") else f"whatsapp:{number}"

    @staticmethod
    def _chunk(text: str, limit: int) -> List[str]:
        if len(text) <= limit:
            return [text]

        chunks: List[str] = []
        current = ""

        for para in text.split("\n\n"):
            # paragraph fits in current chunk
            if len(current) + len(para) + 2 <= limit:
                current += ("" if not current else "\n\n") + para
                continue

            # flush current chunk
            if current:
                chunks.append(current)
                current = ""

            # paragraph itself is too long -> split on sentences
            if len(para) > limit:
                for sentence in para.split(". "):
                    piece = sentence if sentence.endswith(".") else sentence + ". "
                    if len(current) + len(piece) <= limit:
                        current += piece
                    else:
                        if current:
                            chunks.append(current.strip())
                        current = piece
            else:
                current = para

        if current:
            chunks.append(current.strip())

        return chunks
