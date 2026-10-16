"""Minimal stdio MCP client used by the scripted agents."""
import json
import subprocess


class MCPClient:
    def __init__(self, cmd, env=None):
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
        self._id = 0
        self._request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "gauntlet-scripted", "version": "0.1.0"}})
        self._notify("notifications/initialized")

    def _write(self, msg):
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def _notify(self, method, params=None):
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _request(self, method, params):
        self._id += 1
        self._write({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        resp = json.loads(self.proc.stdout.readline())
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]

    def call(self, tool, **args) -> str:
        result = self._request("tools/call", {"name": tool, "arguments": args})
        return "".join(c.get("text", "") for c in result["content"])

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=5)
