"""
Download and process inbound WhatsApp media (images, audio, video).

Twilio serves media at URLs that require HTTP Basic auth
(account SID + auth token).
"""

import base64
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .config import settings

# Media types Claude can handle natively as image content blocks
_IMAGE_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
}

# Audio types we'll transcribe before sending to Claude
_AUDIO_TYPES = {
    "audio/ogg", "audio/mpeg", "audio/mp4", "audio/amr",
    "audio/aac", "audio/opus", "audio/ogg; codecs=opus",
}

# Video types — we'll extract a frame for Claude + note the video context
_VIDEO_TYPES = {
    "video/mp4", "video/3gpp", "video/quicktime",
}

# Max image size to send to Claude (5 MB base64 ≈ 3.75 MB raw)
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _twilio_auth() -> httpx.BasicAuth:
    return httpx.BasicAuth(settings.twilio_account_sid, settings.twilio_auth_token)


async def download_media(url: str, content_type: str) -> Optional[bytes]:
    """Download media bytes from a Twilio media URL."""
    try:
        async with httpx.AsyncClient(auth=_twilio_auth(), follow_redirects=True) as client:
            resp = await client.get(url, timeout=30.0)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        print(f"[MEDIA] Failed to download {url}: {e}", flush=True)
        return None


def classify_media(content_type: str) -> str:
    """Return 'image', 'audio', 'video', or 'unknown'."""
    ct = content_type.lower().split(";")[0].strip()
    if ct in _IMAGE_TYPES:
        return "image"
    if ct in _AUDIO_TYPES or content_type.lower() in _AUDIO_TYPES:
        return "audio"
    if ct in _VIDEO_TYPES:
        return "video"
    return "unknown"


def build_image_block(data: bytes, content_type: str) -> Optional[Dict[str, Any]]:
    """Build a Claude API image content block from raw bytes."""
    if len(data) > _MAX_IMAGE_BYTES:
        print(f"[MEDIA] Image too large ({len(data)} bytes), skipping", flush=True)
        return None

    # Normalise content type for Claude (strip params)
    media_type = content_type.lower().split(";")[0].strip()
    if media_type not in _IMAGE_TYPES:
        media_type = "image/jpeg"  # fallback

    b64 = base64.standard_b64encode(data).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": b64,
        },
    }


async def extract_video_frame(data: bytes, content_type: str) -> Optional[bytes]:
    """Extract the first frame of a video as JPEG using ffmpeg.

    Returns JPEG bytes or None if ffmpeg is unavailable.
    """
    import asyncio

    suffix = ".mp4" if "mp4" in content_type else ".3gp"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
        tmp_in.write(data)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path + "_frame.jpg"

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", tmp_in_path,
            "-vframes", "1", "-q:v", "2", tmp_out_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        if proc.returncode == 0 and Path(tmp_out_path).exists():
            return Path(tmp_out_path).read_bytes()
        print("[MEDIA] ffmpeg frame extraction failed", flush=True)
        return None
    except FileNotFoundError:
        print("[MEDIA] ffmpeg not found - cannot extract video frame", flush=True)
        return None
    finally:
        Path(tmp_in_path).unlink(missing_ok=True)
        Path(tmp_out_path).unlink(missing_ok=True)


async def transcribe_audio(data: bytes, content_type: str) -> Optional[str]:
    """Transcribe audio using ElevenLabs speech-to-text MCP tool.

    Falls back to a simple note if transcription is unavailable.
    """
    # Save to a temp file so the MCP tool can read it
    suffix = ".ogg" if "ogg" in content_type else ".mp4" if "mp4" in content_type else ".amr"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=tempfile.gettempdir()) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        from .tools.mcp_tool import MCPBridgeTool
        mcp = MCPBridgeTool()
        result = await mcp.execute(
            server_name="elevenlabs",
            action="call_tool",
            tool_name="speech_to_text",
            arguments={
                "input_file_path": tmp_path,
                "return_transcript_to_client_directly": True,
                "save_transcript_to_file": False,
            },
        )
        if result and not result.startswith("Error"):
            return result
        print(f"[MEDIA] ElevenLabs transcription returned: {result[:200] if result else 'None'}", flush=True)
        return None
    except Exception as e:
        print(f"[MEDIA] Transcription failed: {e}", flush=True)
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def process_inbound_media(
    media_url: str, content_type: str, body: str
) -> List[Dict[str, Any]]:
    """Process a single inbound media attachment.

    Returns a list of Claude content blocks (text and/or image) to include
    in the user message.
    """
    content_blocks: List[Dict[str, Any]] = []
    kind = classify_media(content_type)
    print(f"[MEDIA] Processing {kind} ({content_type}) from {media_url[:80]}...", flush=True)

    data = await download_media(media_url, content_type)
    if data is None:
        content_blocks.append({
            "type": "text",
            "text": f"[Media attachment ({content_type}) could not be downloaded]",
        })
        return content_blocks

    print(f"[MEDIA] Downloaded {len(data)} bytes", flush=True)

    if kind == "image":
        img_block = build_image_block(data, content_type)
        if img_block:
            content_blocks.append(img_block)
        else:
            content_blocks.append({
                "type": "text",
                "text": "[Image was too large to process]",
            })

    elif kind == "video":
        # Extract a frame for Claude to see
        frame = await extract_video_frame(data, content_type)
        if frame:
            img_block = build_image_block(frame, "image/jpeg")
            if img_block:
                content_blocks.append(img_block)
                content_blocks.append({
                    "type": "text",
                    "text": "[This is a frame extracted from a video the user sent. Describe what you see and ask if they need more detail.]",
                })
        else:
            content_blocks.append({
                "type": "text",
                "text": "[User sent a video but frame extraction is unavailable. Ask them to describe what's in it.]",
            })

    elif kind == "audio":
        transcript = await transcribe_audio(data, content_type)
        if transcript:
            content_blocks.append({
                "type": "text",
                "text": f"[Voice message transcription]: {transcript}",
            })
        else:
            content_blocks.append({
                "type": "text",
                "text": "[User sent a voice message but transcription failed. Let them know and ask them to type their message instead.]",
            })

    else:
        content_blocks.append({
            "type": "text",
            "text": f"[Unsupported media type: {content_type}]",
        })

    return content_blocks
