"""
MCP Bridge Tool
================
Exposes the user's configured MCP servers (NotebookLM, Gmail, Google Sheets, etc.)
as a single Claude tool. Claude specifies which server and method to call, and this
tool spawns the MCP server process, communicates via JSON-RPC over stdio, and returns
the result.
"""

import asyncio
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from .base import BaseTool

# ── MCP server configs (mirrors the user's Claude Code settings.json) ──────

MCP_SERVERS: Dict[str, Dict[str, Any]] = {
    "notebooklm": {
        "command": "C:\\Users\\jay\\AppData\\Roaming\\Python\\Python314\\Scripts\\notebooklm-mcp.exe",
        "args": [],
        "env": {},
        "description": "NotebookLM — create/manage notebooks, add sources, query notebooks, generate audio/video overviews, research topics",
    },
    "gmail": {
        "command": "C:\\Program Files\\nodejs\\npx.cmd",
        "args": ["@gongrzhe/server-gmail-autoauth-mcp"],
        "env": {
            "GMAIL_MCP_CREDENTIALS_PATH": "C:\\Users\\jay\\.gmail-mcp",
        },
        "description": "Gmail — search, read, send, draft emails, manage labels and filters",
    },
    "google-sheets": {
        "command": "C:\\Users\\jay\\.local\\bin\\uvx.exe",
        "args": ["mcp-google-sheets@latest"],
        "env": {
            "CREDENTIALS_PATH": "C:\\Users\\jay\\.mcp-sheets\\credentials.json",
            "TOKEN_PATH": "C:\\Users\\jay\\.mcp-sheets\\token.json",
        },
        "description": "Google Sheets — read/write spreadsheets, manage sheets, create spreadsheets",
    },
    "elevenlabs": {
        "command": "C:\\Users\\jay\\.local\\bin\\uvx.exe",
        "args": ["elevenlabs-mcp"],
        "env": {
            "ELEVENLABS_API_KEY": "sk_c3787ae874b222f886464311b0c05c629199fe6f368ddecc",
        },
        "description": "ElevenLabs — text-to-speech, voice cloning, sound effects, music generation",
    },
    "heygen": {
        "command": "C:\\Users\\jay\\.local\\bin\\uvx.exe",
        "args": ["heygen-mcp"],
        "env": {
            "HEYGEN_API_KEY": "sk_V2_hgu_kZPgEjl9xXN_NNvk0raYsLNgtpDaxKvQ8H3KEZdQfFws",
        },
        "description": "HeyGen — generate AI avatar videos with custom voices",
    },
    "gtasks": {
        "command": "C:\\Program Files\\nodejs\\node.exe",
        "args": ["C:\\Users\\jay\\gtasks-mcp\\dist\\index.js"],
        "env": {},
        "description": "Google Tasks — create, list, search, update, delete tasks and reminders",
    },
    "google-drive": {
        "command": "C:\\Program Files\\nodejs\\node.exe",
        "args": ["C:\\Users\\jay\\google-drive-mcp\\node_modules\\@piotr-agier\\google-drive-mcp\\dist\\index.js"],
        "env": {
            "GOOGLE_DRIVE_OAUTH_CREDENTIALS": "C:\\Users\\jay\\google-drive-mcp\\node_modules\\@piotr-agier\\gcp-oauth.keys.json",
        },
        "description": "Google Drive — search, upload, create, move, rename, delete files. Use uploadFile to upload local files (images, audio, video, etc.) to Drive.",
    },
}


class MCPBridgeTool(BaseTool):
    """Call any configured MCP server tool."""

    @property
    def name(self) -> str:
        return "mcp_call"

    @property
    def description(self) -> str:
        server_list = "\n".join(
            f"  - **{name}**: {cfg['description']}"
            for name, cfg in MCP_SERVERS.items()
        )
        return (
            "Call a tool on one of the user's MCP servers.\n\n"
            "Available servers:\n"
            f"{server_list}\n\n"
            "USAGE:\n"
            "1. First call with action='list_tools' and server_name to see available tools.\n"
            "2. Then call with action='call_tool', server_name, tool_name, and arguments.\n\n"
            "IMPORTANT: You must know the exact tool name. Use list_tools first if unsure."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list_tools", "call_tool"],
                    "description": "Either 'list_tools' to discover tools, or 'call_tool' to invoke one",
                },
                "server_name": {
                    "type": "string",
                    "enum": list(MCP_SERVERS.keys()),
                    "description": "Which MCP server to use",
                },
                "tool_name": {
                    "type": "string",
                    "description": "The tool to call (required when action='call_tool')",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments to pass to the tool (required when action='call_tool')",
                },
            },
            "required": ["action", "server_name"],
        }

    async def execute(
        self,
        action: str,
        server_name: str,
        tool_name: str = "",
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        print(f"[MCP EXECUTE] action={action}, server={server_name}, tool={tool_name}", flush=True)
        if server_name not in MCP_SERVERS:
            return f"Error: Unknown server '{server_name}'. Available: {', '.join(MCP_SERVERS.keys())}"

        cfg = MCP_SERVERS[server_name]

        try:
            if action == "list_tools":
                return await self._list_tools(cfg)
            elif action == "call_tool":
                if not tool_name:
                    return "Error: tool_name is required when action='call_tool'"
                return await self._call_tool(cfg, tool_name, arguments or {})
            else:
                return f"Error: Unknown action '{action}'. Use 'list_tools' or 'call_tool'."
        except Exception as e:
            return f"MCP error: {e}"

    async def _list_tools(self, cfg: Dict[str, Any]) -> str:
        """List available tools from an MCP server."""
        print(f"[MCP] Listing tools...", flush=True)
        result = await self._send_jsonrpc(cfg, "tools/list", {})
        if "error" in result:
            return f"Error: {result['error']}"

        tools = result.get("result", {}).get("tools", [])
        if not tools:
            return "No tools found on this server."

        lines = []
        for t in tools:
            name = t.get("name", "?")
            desc = t.get("description", "")
            # Truncate long descriptions for WhatsApp readability
            if len(desc) > 100:
                desc = desc[:100] + "..."
            lines.append(f"- **{name}**: {desc}")

        return f"Available tools ({len(tools)}):\n" + "\n".join(lines)

    async def _call_tool(
        self, cfg: Dict[str, Any], tool_name: str, arguments: Dict[str, Any]
    ) -> str:
        """Call a specific tool on an MCP server."""
        print(f"[MCP] Calling tool: {tool_name} with args: {arguments}", flush=True)
        result = await self._send_jsonrpc(
            cfg,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        print(f"[MCP] Tool result keys: {list(result.keys())}", flush=True)
        if "error" in result:
            print(f"[MCP] Tool error: {result['error']}", flush=True)
            return f"Error: {result['error']}"

        content = result.get("result", {}).get("content", [])
        parts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                if text:
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)

        output = "\n".join(parts) if parts else json.dumps(result.get("result", {}), indent=2)

        # Truncate very long output
        if len(output) > 8000:
            output = output[:8000] + "\n\n... (truncated)"

        return output

    async def _send_jsonrpc(
        self, cfg: Dict[str, Any], method: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Spawn MCP server, send JSON-RPC initialize + request, return result."""

        command = cfg["command"]
        args = cfg.get("args", [])
        extra_env = cfg.get("env", {})

        env = os.environ.copy()
        env.update(extra_env)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        # Suppress npm update-notifier noise
        env["NO_UPDATE_NOTIFIER"] = "1"

        print(f"[MCP] Spawning: {command} {' '.join(args)}", flush=True)

        proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            # Step 1: Send initialize
            init_msg = _jsonrpc_message(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "whatsapp-bridge", "version": "0.1.0"},
                },
                id=1,
            )
            proc.stdin.write(init_msg)
            await proc.stdin.drain()

            # Read initialize response (generous timeout for slow servers)
            print("[MCP] Waiting for initialize response...", flush=True)
            init_response = await asyncio.wait_for(
                _read_jsonrpc_response(proc.stdout), timeout=60
            )
            print(f"[MCP] Init response: {json.dumps(init_response)[:500]}", flush=True)
            if "error" in init_response:
                stderr_out = await _drain_stderr(proc)
                print(f"[MCP] Init FAILED. Stderr: {stderr_out[:500]}", flush=True)
                return {"error": f"Init failed: {init_response['error']}. Stderr: {stderr_out}"}
            print(f"[MCP] Initialized OK", flush=True)

            # Step 2: Send initialized notification
            notif = _jsonrpc_message("notifications/initialized", {})
            proc.stdin.write(notif)
            await proc.stdin.drain()

            # Small delay to let server process notification
            await asyncio.sleep(0.2)

            # Step 3: Send the actual request
            request_msg = _jsonrpc_message(method, params, id=2)
            proc.stdin.write(request_msg)
            await proc.stdin.drain()

            # Read response
            print(f"[MCP] Waiting for {method} response...", flush=True)
            response = await asyncio.wait_for(
                _read_jsonrpc_response(proc.stdout), timeout=120
            )
            print(f"[MCP] Got response: {json.dumps(response)[:500]}", flush=True)

            return response

        except asyncio.TimeoutError:
            stderr_out = await _drain_stderr(proc)
            print(f"[MCP] Timeout! Stderr: {stderr_out[:500]}", flush=True)
            return {"error": f"MCP server timed out. Stderr: {stderr_out[:300]}"}
        except Exception as e:
            stderr_out = await _drain_stderr(proc)
            print(f"[MCP] Error: {e}. Stderr: {stderr_out[:500]}", flush=True)
            return {"error": f"MCP error: {e}. Stderr: {stderr_out[:300]}"}
        finally:
            proc.stdin.close()
            try:
                proc.kill()
            except ProcessLookupError:
                pass


async def _drain_stderr(proc) -> str:
    """Read whatever is available on stderr (non-blocking)."""
    try:
        stderr_data = await asyncio.wait_for(proc.stderr.read(16384), timeout=5)
        result = stderr_data.decode("utf-8", errors="replace").strip()
        if result:
            print(f"[MCP STDERR] {result[:1000]}", flush=True)
        return result
    except (asyncio.TimeoutError, Exception):
        return ""


def _jsonrpc_message(
    method: str, params: Dict[str, Any], id: Optional[int] = None
) -> bytes:
    """Build a JSON-RPC message as a newline-delimited JSON line.

    Some MCP servers (FastMCP) expect raw JSON lines on stdio.
    Others expect Content-Length framing.  We send BOTH formats
    (Content-Length header + body) so either flavour works.
    """
    msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params:
        msg["params"] = params
    if id is not None:
        msg["id"] = id
    body = json.dumps(msg)
    # Send as raw JSON line (no Content-Length header).
    # FastMCP (notebooklm-mcp) requires this.
    return (body + "\n").encode("utf-8")


async def _read_jsonrpc_response(stdout: asyncio.StreamReader) -> Dict[str, Any]:
    """Read a JSON-RPC response from stdout.

    Supports both:
    - Raw newline-delimited JSON (FastMCP style)
    - Content-Length framed (LSP / older MCP style)

    Skips notifications (messages without an "id" field) and
    junk lines (npm output, startup messages).
    """
    max_lines = 200  # safety valve
    content_length = 0

    for _ in range(max_lines):
        line = await stdout.readline()
        if not line:
            return {"error": "Server closed connection (EOF)"}

        line_str = line.decode("utf-8", errors="replace").strip()
        if not line_str:
            # Empty line: if we have a pending Content-Length, read framed body
            if content_length > 0:
                body = await stdout.readexactly(content_length)
                data = json.loads(body.decode("utf-8"))
                content_length = 0
                if "id" not in data:
                    # notification — skip and keep reading
                    continue
                return data
            continue

        # Check for Content-Length header (LSP framing)
        if line_str.lower().startswith("content-length:"):
            try:
                content_length = int(line_str.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue

        # Try to parse as raw JSON
        try:
            data = json.loads(line_str)
            if isinstance(data, dict):
                if "id" not in data:
                    # notification — skip
                    print(f"[MCP notification] {line_str[:300]}", flush=True)
                    continue
                return data
        except (json.JSONDecodeError, ValueError):
            pass

        # Otherwise it's junk (npm output, startup messages)
        print(f"[MCP stdout junk] {line_str[:500]}", flush=True)

    return {"error": "Exceeded max lines without receiving a JSON-RPC response"}
