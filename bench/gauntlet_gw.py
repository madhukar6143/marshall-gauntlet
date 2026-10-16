"""gauntlet-gw: a real stdio MCP proxy process.

The agent launches:

    python bench/gauntlet_gw.py --name fs --session <file> --audit <file> \
        -- python bench/servers/fs_server.py --root <repo>

It spawns the real server as a child and relays newline-delimited JSON-RPC
between the agent (its own stdin/stdout) and the child. Every tools/call is
run through bench/gateway.py:

  * deny  -> a JSON-RPC tool error is returned, the call never reaches the child
  * hold  -> auto-rejected in benchmark mode (a tool error), never reaches child
  * allow -> forwarded; the response is taint-marked and redacted, then relayed

Session taint is shared across separate gateway processes (one per server) via
--session: a small JSON file. This resolves KNOWLEDGE.md §7: the fs gateway and
the fetch gateway see the same taint bit, so reading an untrusted file through
`fs` holds a later `fetch.post`.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gateway import Policy, Session, decide, mark_taint  # noqa: E402

SECRET_VALUE = re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*(\S+)", re.I)


def load_session(path):
    if path and Path(path).exists():
        try:
            return Session(**json.loads(Path(path).read_text()))
        except Exception:
            pass
    return Session()


def save_session(path, session):
    if path:
        Path(path).write_text(json.dumps({"tainted": session.tainted}))


def audit(path, record):
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def redact(text):
    return SECRET_VALUE.sub(lambda m: f"{m.group(1)}=***REDACTED***", text)


def tool_error(mid, message):
    return {"jsonrpc": "2.0", "id": mid,
            "result": {"content": [{"type": "text", "text": message}], "isError": True}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="server name used in policy (e.g. fs, fetch)")
    ap.add_argument("--session", help="shared taint state file")
    ap.add_argument("--audit", help="audit jsonl path")
    ap.add_argument("--mode", default="benchmark", choices=["benchmark", "interactive"])
    argv = sys.argv[1:]
    sep = argv.index("--")
    args = ap.parse_args(argv[:sep])
    server_cmd = argv[sep + 1:]

    policy = Policy()
    child = subprocess.Popen(server_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def forward_and_relay(line_bytes):
        child.stdin.write(line_bytes)
        child.stdin.flush()
        resp = child.stdout.readline()
        sys.stdout.buffer.write(resp)
        sys.stdout.buffer.flush()
        return resp

    def emit(msg):
        sys.stdout.buffer.write((json.dumps(msg) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()

    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8")
        stripped = line.strip()
        if not stripped:
            continue
        msg = json.loads(stripped)
        method, mid = msg.get("method"), msg.get("id")

        if method != "tools/call":
            # initialize / tools/list / ping / notifications: transparent
            child.stdin.write(raw)
            child.stdin.flush()
            if mid is not None:
                resp = child.stdout.readline()
                sys.stdout.buffer.write(resp)
                sys.stdout.buffer.flush()
            continue

        tool = msg["params"]["name"]
        call_args = msg["params"].get("arguments") or {}
        qualified = f"{args.name}.{tool}"
        session = load_session(args.session)
        d = decide(qualified, call_args, session, policy)
        audit(args.audit, {"ts": time.time(), "tool": qualified, "args": call_args,
                           "action": d.action, "rule": d.rule, "reason": d.reason,
                           "tainted": session.tainted})

        if d.action == "deny":
            emit(tool_error(mid, f"[gauntlet-gw] denied by rule '{d.rule}': {d.reason}"))
            continue
        if d.action == "hold":
            # benchmark mode: deterministic auto-reject so runs are reproducible
            emit(tool_error(mid, f"[gauntlet-gw] held by rule '{d.rule}' (auto-rejected): {d.reason}"))
            continue

        # allow: forward, then response-path taint + redact
        child.stdin.write(raw)
        child.stdin.flush()
        resp_bytes = child.stdout.readline()
        if mark_taint(qualified, call_args, session, policy):
            save_session(args.session, session)
            audit(args.audit, {"ts": time.time(), "event": "taint", "by": qualified})
        try:
            resp = json.loads(resp_bytes)
            for c in resp.get("result", {}).get("content", []):
                if c.get("type") == "text":
                    c["text"] = redact(c["text"])
            emit(resp)
        except Exception:
            sys.stdout.buffer.write(resp_bytes)
            sys.stdout.buffer.flush()

    child.stdin.close()
    child.wait(timeout=5)


if __name__ == "__main__":
    main()
