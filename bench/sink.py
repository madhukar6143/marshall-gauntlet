"""Local stand-in for the attacker's server.

Listens on localhost only and appends every request to <log>. The
canary_in_sink oracle greps that log.

    python bench/sink.py --log results/<run>/sink.jsonl [--port 9999]
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(log_path):
    class Handler(BaseHTTPRequestHandler):
        def _record(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            entry = {"ts": time.time(), "method": self.command, "path": self.path, "body": body}
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")

        do_GET = do_POST = do_PUT = _record

        def log_message(self, *args):
            pass

    return Handler


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--log", required=True)
    p.add_argument("--port", type=int, default=9999)
    a = p.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a.log)).serve_forever()


if __name__ == "__main__":
    main()
