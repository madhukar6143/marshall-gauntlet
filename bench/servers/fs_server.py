"""Fake `fs` MCP server, rooted at a scenario working copy.

    python bench/servers/fs_server.py --root <working copy>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_stdio import Tool, serve  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    root = Path(p.parse_args().root).resolve()

    def resolve(path: str) -> Path:
        target = (root / path).resolve()
        if target != root and root not in target.parents:
            raise ValueError("path escapes repo root")
        return target

    def read_file(path: str) -> str:
        return resolve(path).read_text(encoding="utf-8")

    def write_file(path: str, content: str) -> str:
        target = resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} chars to {path}"

    def list_dir(path: str = ".") -> str:
        entries = sorted(resolve(path).iterdir())
        return "\n".join(e.name + ("/" if e.is_dir() else "") for e in entries)

    path_arg = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    serve("fs", {
        "read_file": Tool("read_file", "Read a text file in the project (path relative to repo root).", path_arg, read_file),
        "write_file": Tool("write_file", "Write a text file in the project (path relative to repo root).",
                           {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                            "required": ["path", "content"]}, write_file),
        "list_dir": Tool("list_dir", "List a directory in the project (path relative to repo root).",
                         {"type": "object", "properties": {"path": {"type": "string"}}}, list_dir),
    })


if __name__ == "__main__":
    main()
