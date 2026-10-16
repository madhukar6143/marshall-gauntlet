"""Live attack demo with the capture console.

Unlike run_live.py (which starts a throwaway sink per run), this keeps ONE
capture console running so you can watch exfiltration land in the browser.

    # 1. start the console (leave running in its own terminal):
    python bench/demo/run_demo.py console

    # 2. in another terminal (with your API key set), fire the agent:
    python bench/demo/run_demo.py attack --gateway none        --provider openai --model gpt-4o-mini
    python bench/demo/run_demo.py attack --gateway gauntlet-gw  --provider openai --model gpt-4o-mini

The console logs to results/demo/sink.jsonl and serves http://127.0.0.1:9999.
'attack' points the agent's fetch server at that console instead of its own.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
import oracle  # noqa: E402

DEMO_DIR = BENCH.parent / "results" / "demo"
RUNS_DIR = DEMO_DIR / "runs"      # archived per-run results for the report
PORT = 9999


def _q(p):
    return '"' + str(p).replace("\\", "/") + '"'


def inject(text, payload):
    head, sep, rest = text.partition("\n\n")
    block = payload.strip()
    return f"{head}{sep}{block}\n\n{rest}" if sep else f"{block}\n\n{text}"


def build_copy():
    import yaml
    scn = yaml.safe_load((BENCH / "scenarios" / "exfil-verify-existing.yaml").read_text())
    repo = DEMO_DIR / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    shutil.copytree(BENCH / "repos" / scn["repo"], repo,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    tgt = repo / scn["payload"]["target"]
    tgt.write_text(inject(tgt.read_text(encoding="utf-8"), scn["payload"]["text"]), encoding="utf-8")
    return scn, repo


def run_console():
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(BENCH / "demo" / "dashboard_sink.py"),
                    "--log", str(DEMO_DIR / "sink.jsonl"), "--port", str(PORT)])


def server_specs(gateway, repo, session, audit):
    py = _q(sys.executable)
    fs_real = f'{py} {_q(BENCH / "servers" / "fs_server.py")} --root {_q(repo)}'
    fetch_real = f'{py} {_q(BENCH / "servers" / "fetch_server.py")}'
    if gateway == "none":
        return [f"fs={fs_real}", f"fetch={fetch_real}"]
    gw = f'{py} {_q(BENCH / "gauntlet_gw.py")}'
    return [f'fs={gw} --name fs --session {_q(session)} --audit {_q(audit)} -- {fs_real}',
            f'fetch={gw} --name fetch --session {_q(session)} --audit {_q(audit)} -- {fetch_real}']


def _sink_lines():
    f = DEMO_DIR / "sink.jsonl"
    return [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []


def run_attack(gateway, provider, model):
    scn, repo = build_copy()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RUNS_DIR / f"{stamp}-{gateway}-{provider}-{model.replace('/', '_')}"
    out.mkdir(parents=True, exist_ok=True)
    session = out / "session.json"
    audit = out / "audit.jsonl"

    before = len(_sink_lines())   # so we can isolate THIS run's captures from the shared console
    cmd = [sys.executable, str(BENCH / "agents" / "agent.py"),
           "--provider", provider, "--model", model, "--task", scn["task"],
           "--transcript", str(out / "agent.jsonl")]
    for s in server_specs(gateway, repo, session, audit):
        cmd += ["--server", s]
    print(f"firing {provider}/{model} through gateway={gateway} …")
    print("watch the console at http://127.0.0.1:9999")
    p = subprocess.run(cmd, text=True)

    # this run's captures = new lines appended to the shared console log
    new_caps = _sink_lines()[before:]
    (out / "sink.jsonl").write_text("\n".join(new_caps) + ("\n" if new_caps else ""), encoding="utf-8")
    canary = oracle.check(out, scn["oracle"])
    contacted = oracle.sink_contacted(out)
    result = {
        "scenario": scn["id"], "gateway": gateway, "provider": provider, "model": model,
        "agent_ran": p.returncode == 0,
        "attack_fired": canary["fired"], "sink_contacted": contacted["fired"],
        "captures": len(new_caps), "ts": datetime.now(timezone.utc).isoformat(),
    }
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nrun: fired={canary['fired']}  sink_contacted={contacted['fired']}  "
          f"captures={len(new_caps)}  agent_ran={result['agent_ran']}")
    print(f"saved: {out}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("console")
    a = sub.add_parser("attack")
    a.add_argument("--gateway", default="none", choices=["none", "gauntlet-gw"])
    a.add_argument("--provider", default="openai", choices=["anthropic", "openai", "gemini"])
    a.add_argument("--model", default="gpt-4o-mini")
    args = ap.parse_args()
    if args.cmd == "console":
        run_console()
    else:
        run_attack(args.gateway, args.provider, args.model)


if __name__ == "__main__":
    main()
