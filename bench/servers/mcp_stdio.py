"""Minimal MCP server over stdio (newline-delimited JSON-RPC 2.0). No deps.

A server subclasses nothing: it builds a dict of Tool objects and calls
serve(name, tools). Every tools/call is appended to $GAUNTLET_CALL_LOG
before it runs, so oracles can read what the agent actually invoked.
"""
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[..., str]


def _log_call(server, tool, args):
    path = os.environ.get("GAUNTLET_CALL_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "server": server, "tool": tool, "args": args}) + "\n")


def _send(msg):
    sys.stdout.buffer.write((json.dumps(msg) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def serve(server_name: str, tools: dict):
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8").strip()
        if not line:
            continue
        msg = json.loads(line)
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:  # notification
            continue
        if method == "initialize":
            result = {
                "protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": server_name, "version": "0.1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [
                {"name": t.name, "description": t.description, "inputSchema": t.schema}
                for t in tools.values()
            ]}
        elif method == "tools/call":
            name = msg["params"]["name"]
            args = msg["params"].get("arguments") or {}
            _log_call(server_name, name, args)
            tool = tools.get(name)
            if tool is None:
                result = {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
            else:
                try:
                    result = {"content": [{"type": "text", "text": tool.fn(**args)}], "isError": False}
                except Exception as e:  # tool errors go back to the agent, not the transport
                    result = {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}
        else:
            _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}})
            continue
        _send({"jsonrpc": "2.0", "id": mid, "result": result})
