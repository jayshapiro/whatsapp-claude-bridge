import re
import subprocess
from typing import Any, Dict

from .base import BaseTool

# Patterns that indicate a destructive / dangerous command.
# Everything else (reads, searches, navigation, dates, etc.) is auto-approved.
_DESTRUCTIVE_PATTERNS = re.compile(
    r"""(?ix)                     # case-insensitive, verbose
    \b(?:
        rm\b | rmdir\b | del\b | erase\b         # delete files/dirs
      | remove-item\b                              # powershell delete
      | format\b                                   # disk format
      | kill\b | stop-process\b | taskkill\b       # kill processes
      | shutdown\b | restart-computer\b            # system power
      | net\s+(?:user|localgroup)\b                # user management
      | reg\s+(?:delete|add)\b                     # registry edits
      | sc\s+(?:delete|stop)\b                     # service management
      | mklink\b                                   # symlinks
      | attrib\b                                   # change file attributes
      | icacls\b | cacls\b                         # permission changes
      | schtasks\s+/(?:create|delete)\b            # scheduled tasks
      | move\b | ren\b | rename\b                  # move / rename
      | curl\b.*-[dX]                              # HTTP POST/PUT/DELETE via curl
      | invoke-webrequest\b.*-method\b             # powershell HTTP mutations
      | pip\s+install\b | pip\s+uninstall\b        # package install/remove
      | npm\s+install\b | npm\s+uninstall\b
      | git\s+(?:push|reset|rebase|merge|checkout) # destructive git ops
    )
    """,
)


class BashTool(BaseTool):
    """Execute shell commands on the local Windows machine."""

    @property
    def name(self) -> str:
        return "execute_bash"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command on the local Windows system. "
            "Output (stdout + stderr) is captured and returned. "
            "Commands time out after 30 seconds. "
            "Read-only commands (dir, type, cat, date, echo, grep, find, where, cd, ls, "
            "pwd, whoami, hostname, etc.) are auto-approved. "
            "Destructive commands (rm, del, kill, format, move, git push, etc.) require "
            "user approval via WhatsApp."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of why this command is needed",
                },
            },
            "required": ["command"],
        }

    @property
    def requires_approval(self) -> bool:
        # Static default — the dynamic check_approval() is preferred
        return True

    def check_approval(self, **kwargs) -> bool:
        """Only require approval for destructive commands."""
        command = kwargs.get("command", "")
        is_destructive = bool(_DESTRUCTIVE_PATTERNS.search(command))
        if not is_destructive:
            print(f"[BASH] Auto-approved (read-only): {command[:80]}", flush=True)
        else:
            print(f"[BASH] Requires approval (destructive): {command[:80]}", flush=True)
        return is_destructive

    async def execute(self, command: str, reason: str = "") -> str:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
            parts = []
            if result.stdout:
                parts.append(f"STDOUT:\n{result.stdout.strip()}")
            if result.stderr:
                parts.append(f"STDERR:\n{result.stderr.strip()}")
            parts.append(f"Exit code: {result.returncode}")
            return "\n\n".join(parts)
        except subprocess.TimeoutExpired:
            return "Error: Command timed out after 30 seconds"
        except Exception as e:
            return f"Error: {e}"
