from pathlib import Path
from typing import Any, Dict

from .base import BaseTool

MAX_READ_CHARS = 10_000


class FileReadTool(BaseTool):
    """Read a file from the local filesystem."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a local file. Provide an absolute path. "
            "Output is truncated to 10 000 characters."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                }
            },
            "required": ["file_path"],
        }

    async def execute(self, file_path: str) -> str:
        try:
            p = Path(file_path)
            if not p.exists():
                return f"Error: File not found: {file_path}"
            if not p.is_file():
                return f"Error: Not a file: {file_path}"
            content = p.read_text(encoding="utf-8", errors="replace")
            if len(content) > MAX_READ_CHARS:
                return (
                    content[:MAX_READ_CHARS]
                    + f"\n\n... (truncated, {len(content)} chars total)"
                )
            return content
        except Exception as e:
            return f"Error reading file: {e}"


class FileWriteTool(BaseTool):
    """Write content to a file on the local filesystem."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a local file. Creates parent directories if needed. "
            "Overwrites the file if it already exists. Provide an absolute path."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path where the file should be written",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write",
                },
            },
            "required": ["file_path", "content"],
        }

    @property
    def requires_approval(self) -> bool:
        return True

    async def execute(self, file_path: str, content: str) -> str:
        try:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} characters to {file_path}"
        except Exception as e:
            return f"Error writing file: {e}"
