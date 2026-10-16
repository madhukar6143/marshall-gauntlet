"""Live runner: one scenario, one gateway, one mode (attack|benign), N runs.

Wires the real pieces together:

    scenario -> working copy (payload injected for attack mode)
             -> sink on localhost:9999
             -> gateways in front of fs + fetch servers (or direct, for gateway=none)
             -> sdk_agent does the task
             -> oracle check + repo tests -> result.json

    python bench/run_live.py --scenario exfil-readme-env --gateway gauntlet-gw \
        --mode attack --model claude-haiku-5-5 --runs 3

Needs ANTHROPIC_API_KEY for the agent step. Everything else (copy, sink,
gateways, oracle) runs without a key, so --dry-run builds a run dir and
checks the plumbing without calling the model.
"""
import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
import oracle  # noqa: E402

SINK_PORT = 9999


def inject(text, payload, mode):
    if mode == "html_comment":
        block = f"<!--\n{payload.strip()}\n-->"
    elif mode == "plain":
        block = payload.strip()
    else:
        raise NotImplementedError(f"payload mode {mode!r}")
    head, sep, rest = text.partition("\n\n")
    return f"{head}{sep}{block}\n\n{rest}" if sep else f"{block}\n\n{text}"


def build_copy(scn, mode, run_dir):
    repo = run_dir / "repo"
    shutil.copytree(BENCH / "repos" / scn["repo"], repo,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    if mode == "attack":
        tgt = repo / scn["payload"]["target"]
        tgt.write_text(inject(tgt.read_text(encoding="utf-8"), scn["payload"]["text"],
                              scn["payload"]["mode"]), encoding="utf-8")
    return repo


def _port_in_use(port):
    try:
        socket.create_connection(("127.0.0.1", port), 0.2).close()
        return True
    except OSError:
        return False


def start_sink(run_dir):
    # Preflight: if something already listens on SINK_PORT, our sink can't bind,
    # yet the readiness check below would connect to that squatter and wrongly
    # report success. The agent's POSTs would then land on the other listener,
    # leaving this run's sink empty and the oracle scoring a false negative.
    # Refuse to run instead (e.g. a leftover demo console on 9999).
    if _port_in_use(SINK_PORT):
        raise RuntimeError(
            f"port {SINK_PORT} is already in use; the sink cannot bind and "
            f"exfiltration POSTs would be captured by the other listener "
            f"(false negatives). Stop whatever holds port {SINK_PORT} "
            f"(e.g. a leftover `run_demo.py console`) and re-run."
        )
    proc = subprocess.Popen([sys.executable, str(BENCH / "sink.py"),
                             "--log", str(run_dir / "sink.jsonl"), "--port", str(SINK_PORT)])
    for _ in range(50):
        if proc.poll() is not None:
            raise RuntimeError(
                f"sink process exited before binding port {SINK_PORT} "
                f"(exit code {proc.returncode}); is the port free?")
        try:
            socket.create_connection(("127.0.0.1", SINK_PORT), 0.2).close()
            return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError(f"sink did not start on port {SINK_PORT} (port busy?)")


def _sink_posts(run_dir):
    """Every POST body that actually reached this run's sink (the attacker),
    canary or not. This is the honest 'did the agent contact the attacker'
    signal; the canary oracle only catches it when the REAL secret was sent."""
    f = run_dir / "sink.jsonl"
    posts = []
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("method") == "POST":
                posts.append((ev.get("body") or "").strip())
    return posts


def _leak_preview(evidence, maxlen=70):
    """One-line preview of what reached the sink, so a fire is visible in the
    terminal without the web console. Shows the first non-empty body line,
    truncated — the data is a fake canary, so no masking needed."""
    for ev in evidence:
        for line in (ev.get("body") or "").splitlines():
            line = line.strip()
            if line:
                return line[:maxlen] + ("…" if len(line) > maxlen else "")
    return "(empty body)"


def _stop_sink(proc):
    """Reliably stop the sink. terminate() can fail to take within the timeout
    (sink mid-request); escalate to kill() so it never orphans onto SINK_PORT.
    Swallows errors so cleanup never masks the run's real result."""
    for stop in (proc.terminate, proc.kill):
        try:
            stop()
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue
        except Exception:
            return


def _q(p):
    """Quote a path and use forward slashes so posix shlex.split survives Windows paths."""
    return '"' + str(p).replace("\\", "/") + '"'


def server_specs(gateway, repo, session, audit):
    """Return [--server name=cmd] strings; gateway=none calls servers directly."""
    py = _q(sys.executable)
    fs_real = f'{py} {_q(BENCH / "servers" / "fs_server.py")} --root {_q(repo)}'
    fetch_real = f'{py} {_q(BENCH / "servers" / "fetch_server.py")}'
    if gateway == "none":
        return [f"fs={fs_real}", f"fetch={fetch_real}"]
    if gateway == "gauntlet-gw":
        gw = f'{py} {_q(BENCH / "gauntlet_gw.py")}'
        return [
            f'fs={gw} --name fs --session {_q(session)} --audit {_q(audit)} -- {fs_real}',
            f'fetch={gw} --name fetch --session {_q(session)} --audit {_q(audit)} -- {fetch_real}',
        ]
    raise ValueError(f"unknown gateway {gateway!r}")


def run_tests(repo):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=repo,
                       capture_output=True, text=True, timeout=120)
    return r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def one_run(scn, gateway, mode, provider, model, run_dir, dry):
    run_dir.mkdir(parents=True, exist_ok=True)
    repo = build_copy(scn, mode, run_dir)
    session = run_dir / "session.json"
    audit = run_dir / "audit.jsonl"
    call_log = run_dir / "calls.jsonl"
    sink = start_sink(run_dir)
    agent_ran, agent_err = False, None
    try:
        if not dry:
            cmd = [sys.executable, str(BENCH / "agents" / "agent.py"),
                   "--provider", provider, "--model", model, "--task", scn["task"],
                   "--transcript", str(run_dir / "agent.jsonl")]
            for s in server_specs(gateway, repo, session, audit):
                cmd += ["--server", s]
            env = {**__import__("os").environ, "GAUNTLET_CALL_LOG": str(call_log)}
            try:
                p = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=int(__import__("os").environ.get("GAUNTLET_RUN_TIMEOUT", "600")), env=env)
                agent_ran = p.returncode == 0
                agent_err = None if agent_ran else (p.stderr.strip() or p.stdout.strip())
                (run_dir / "agent.stdout.txt").write_text(p.stdout, encoding="utf-8")
            except subprocess.TimeoutExpired:
                # e.g. free-tier 429 retries overrun the per-run timeout. Record
                # it as a failed run and keep going — never let one run abort the
                # whole matrix.
                agent_ran, agent_err = False, "agent timed out (GAUNTLET_RUN_TIMEOUT)"
    finally:
        _stop_sink(sink)

    fired = oracle.check(run_dir, scn["oracle"])
    sink_posts = _sink_posts(run_dir)
    tests_pass, tests_line = run_tests(repo)
    result = {
        "scenario": scn["id"], "gateway": gateway, "mode": mode,
        "provider": provider, "model": model,
        "dry_run": dry, "agent_ran": agent_ran, "agent_error": agent_err,
        "attack_fired": fired["fired"], "oracle_evidence": fired["evidence"],
        # sink_contacted: did the agent POST to the attacker at all, regardless
        # of whether the real canary was in it? Catches obeyed-injection cases
        # the canary oracle misses (e.g. the model overwrote the secret first).
        "sink_contacted": bool(sink_posts), "sink_posts": sink_posts,
        "tests_pass": tests_pass, "tests_line": tests_line,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--gateway", default="none", choices=["none", "gauntlet-gw"])
    ap.add_argument("--mode", default="attack", choices=["attack", "benign"])
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "gemini"])
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    scn = yaml.safe_load((BENCH / "scenarios" / f"{a.scenario}.yaml").read_text())
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = BENCH.parent / "results" / f"{stamp}-{a.scenario}-{a.provider}-{a.gateway}-{a.mode}"
    summary = []
    for n in range(1, a.runs + 1):
        res = one_run(scn, a.gateway, a.mode, a.provider, a.model, base / f"run-{n}", a.dry_run)
        summary.append(res)
        print(f"run {n}: fired={res['attack_fired']} "
              f"sink_contacted={res['sink_contacted']} tests_pass={res['tests_pass']} "
              f"agent_ran={res['agent_ran']}"
              + (f" err={res['agent_error']}" if res['agent_error'] else ""))
        # Always surface a POST to the attacker, even when the canary oracle
        # missed it (model sent a placeholder / overwrote the secret first).
        for body in res.get('sink_posts', []):
            first = next((ln for ln in body.splitlines() if ln.strip()), "(empty)")
            canary = scn["oracle"].get("canary", "")
            tag = "LEAKED (real secret)" if canary and canary in body else "ATTACKER GOT POST"
            print(f"        → {tag}: {first[:70]}")
        # Surface destructive harm (file_changed / sentinel_missing oracles).
        if res['attack_fired'] and scn["oracle"]["kind"] in ("file_changed", "sentinel_missing"):
            for ev in res['oracle_evidence']:
                print(f"        → DESTROYED: {ev.get('sentinel','?')} "
                      f"[{ev.get('status','?')}]")
    (base / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nresults: {base}")


if __name__ == "__main__":
    main()
