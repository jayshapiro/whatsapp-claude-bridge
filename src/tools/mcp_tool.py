"""
MCP Bridge Tool
================
Exposes the user's configured MCP servers (NotebookLM, Gmail, Google Sheets, etc.)
as a single Claude tool. Claude specifies which server and method to call, and this
tool communicates via JSON-RPC over stdio with persistent server processes.

Architecture:
  - MCP servers are spawned ONCE and kept alive for the bridge's lifetime.
  - This mirrors how Claude Code manages MCP servers (persistent connections).
  - Auth sessions, cookies, and state are preserved across tool calls.
  - Servers are lazily started on first use and restarted if they crash.
"""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from .base import BaseTool

# ── Load MCP server configs from settings.json (single source of truth) ──────

def _load_mcp_servers() -> Dict[str, Dict[str, Any]]:
    """Load MCP server configurations from ~/.claude/settings.json."""
    from pathlib import Path
    settings_path = Path.home() / ".claude" / "settings.json"
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        servers = data.get("mcpServers", {})
        result = {}
        for name, cfg in servers.items():
            result[name] = {
                "command": cfg.get("command", ""),
                "args": cfg.get("args", []),
                "env": cfg.get("env", {}),
                "description": cfg.get("description", f"{name} MCP server"),
            }
        print(f"[MCP] Loaded {len(result)} servers from {settings_path}: {', '.join(result.keys())}", flush=True)
        return result
    except Exception as e:
        print(f"[MCP] WARNING: Could not load settings.json: {e}", flush=True)
        return {}


MCP_SERVERS: Dict[str, Dict[str, Any]] = _load_mcp_servers()


# ── Persistent MCP server connections ────────────────────────────────────────

class MCPConnection:
    """A persistent connection to a single MCP server process."""

    def __init__(self, name: str, cfg: Dict[str, Any]):
        self.name = name
        self.cfg = cfg
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._request_id = 10  # Start above init IDs
        self._initialized = False

    async def ensure_running(self) -> None:
        """Start the server if not running, or restart if it crashed."""
        if self.proc is not None and self.proc.returncode is None:
            if self._initialized:
                return
        # Need to start or restart
        await self._start()

    async def _start(self) -> None:
        """Spawn the MCP server and initialize it."""
        # Kill old process if any
        if self.proc is not None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
            self.proc = None
            self._initialized = False

        command = self.cfg["command"]
        args = self.cfg.get("args", [])
        extra_env = self.cfg.get("env", {})

        env = os.environ.copy()
        env.update(extra_env)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["NO_UPDATE_NOTIFIER"] = "1"

        print(f"[MCP:{self.name}] Starting: {command} {' '.join(args)}", flush=True)

        self.proc = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Initialize
        init_msg = _jsonrpc_message(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "whatsapp-bridge", "version": "0.2.0"},
            },
            id=1,
        )
        self.proc.stdin.write(init_msg)
        await self.proc.stdin.drain()

        init_response = await asyncio.wait_for(
            _read_jsonrpc_response(self.proc.stdout), timeout=60
        )

        if "error" in init_response:
            stderr_out = await self._drain_stderr()
            raise RuntimeError(f"Init failed for {self.name}: {init_response['error']}. Stderr: {stderr_out}")

        print(f"[MCP:{self.name}] Initialized OK", flush=True)

        # Send initialized notification
        notif = _jsonrpc_message("notifications/initialized", {})
        self.proc.stdin.write(notif)
        await self.proc.stdin.drain()
        await asyncio.sleep(0.2)

        self._initialized = True

    async def send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON-RPC request to the running server."""
        async with self._lock:
            await self.ensure_running()

            self._request_id += 1
            rid = self._request_id

            request_msg = _jsonrpc_message(method, params, id=rid)
            self.proc.stdin.write(request_msg)
            await self.proc.stdin.drain()

            print(f"[MCP:{self.name}] Sent {method} (id={rid})", flush=True)

            try:
                response = await asyncio.wait_for(
                    _read_jsonrpc_response(self.proc.stdout), timeout=120
                )
                return response
            except asyncio.TimeoutError:
                stderr_out = await self._drain_stderr()
                # Server might be stuck — kill and let it restart next time
                self._initialized = False
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass
                self.proc = None
                return {"error": f"MCP server '{self.name}' timed out. Stderr: {stderr_out[:300]}"}

    async def _drain_stderr(self) -> str:
        """Read available stderr."""
        if self.proc is None or self.proc.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(self.proc.stderr.read(16384), timeout=5)
            result = data.decode("utf-8", errors="replace").strip()
            if result:
                print(f"[MCP:{self.name} STDERR] {result[:1000]}", flush=True)
            return result
        except (asyncio.TimeoutError, Exception):
            return ""

    async def shutdown(self) -> None:
        """Cleanly stop the server."""
        if self.proc is not None:
            try:
                self.proc.stdin.close()
                self.proc.kill()
            except (ProcessLookupError, BrokenPipeError):
                pass
            self.proc = None
            self._initialized = False
            print(f"[MCP:{self.name}] Shut down", flush=True)


# Global connection pool — one persistent connection per server
_connections: Dict[str, MCPConnection] = {}


def _get_connection(server_name: str) -> MCPConnection:
    """Get or create a persistent connection to a server."""
    if server_name not in _connections:
        _connections[server_name] = MCPConnection(server_name, MCP_SERVERS[server_name])
    return _connections[server_name]


async def shutdown_all_mcp() -> None:
    """Shut down all persistent MCP connections. Called on bridge exit."""
    for conn in _connections.values():
        await conn.shutdown()
    _connections.clear()


# ── The tool itself ──────────────────────────────────────────────────────────

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

        conn = _get_connection(server_name)

        try:
            if action == "list_tools":
                return await self._list_tools(conn)
            elif action == "call_tool":
                if not tool_name:
                    return "Error: tool_name is required when action='call_tool'"
                return await self._call_tool(conn, tool_name, arguments or {})
            else:
                return f"Error: Unknown action '{action}'. Use 'list_tools' or 'call_tool'."
        except Exception as e:
            print(f"[MCP:{server_name}] Error: {e}", flush=True)
            return f"MCP error: {e}"

    async def _list_tools(self, conn: MCPConnection) -> str:
        """List available tools from an MCP server."""
        result = await conn.send_request("tools/list", {})
        if "error" in result:
            return f"Error: {result['error']}"

        tools = result.get("result", {}).get("tools", [])
        if not tools:
            return "No tools found on this server."

        lines = []
        for t in tools:
            name = t.get("name", "?")
            desc = t.get("description", "")
            if len(desc) > 100:
                desc = desc[:100] + "..."
            lines.append(f"- **{name}**: {desc}")

        return f"Available tools ({len(tools)}):\n" + "\n".join(lines)

    async def _call_tool(
        self, conn: MCPConnection, tool_name: str, arguments: Dict[str, Any]
    ) -> str:
        """Call a specific tool on an MCP server."""
        result = await conn.send_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )
        if "error" in result:
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


# ── JSON-RPC helpers ─────────────────────────────────────────────────────────

def _jsonrpc_message(
    method: str, params: Dict[str, Any], id: Optional[int] = None
) -> bytes:
    """Build a JSON-RPC message as a newline-delimited JSON line."""
    msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params:
        msg["params"] = params
    if id is not None:
        msg["id"] = id
    body = json.dumps(msg)
    return (body + "\n").encode("utf-8")


async def _read_jsonrpc_response(stdout: asyncio.StreamReader) -> Dict[str, Any]:
    """Read a JSON-RPC response from stdout.

    Supports both:
    - Raw newline-delimited JSON (FastMCP style)
    - Content-Length framed (LSP / older MCP style)

    Skips notifications (messages without an "id" field) and
    junk lines (npm output, startup messages).
    """
    max_lines = 200
    content_length = 0

    for _ in range(max_lines):
        line = await stdout.readline()
        if not line:
            return {"error": "Server closed connection (EOF)"}

        line_str = line.decode("utf-8", errors="replace").strip()
        if not line_str:
            if content_length > 0:
                body = await stdout.readexactly(content_length)
                data = json.loads(body.decode("utf-8"))
                content_length = 0
                if "id" not in data:
                    continue
                return data
            continue

        if line_str.lower().startswith("content-length:"):
            try:
                content_length = int(line_str.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue

        try:
            data = json.loads(line_str)
            if isinstance(data, dict):
                if "id" not in data:
                    continue
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    return {"error": "Exceeded max lines without receiving a JSON-RPC response"}
