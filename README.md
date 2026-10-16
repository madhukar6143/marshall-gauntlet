# Gauntlet 🛡️

**Do AI agents fall for hidden instructions — and can one simple gateway stop them?**

Gauntlet is a benchmark that hides a sneaky instruction inside a file an AI agent reads (a "README"), then measures how often the agent obeys it — stealing a fake secret or wiping a fake data file. It runs **11 models from OpenAI, Anthropic, and Google**, with and without a defensive gateway called **marshall-gauntlet**.

Everything runs locally with fake canary secrets. Nothing ever leaves the machine.

👉 **[Live interactive demo](https://claude.ai/artifact/XJHG16j4jAkXPQUGP2pkJW)** — pick a model, pick an attack, watch it leak with no defense vs. get blocked by the gateway.
📄 **[Full write-up in plain English → PROOF.md](PROOF.md)**

---

## The headline finding: capability ≠ safety

How often each model fell for the disguised attack, **with no defense** (660+ live runs):

| model | company | steal a secret | destroy data |
|-------|---------|----------------|--------------|
| gemini-flash-lite (cheap) | Google | **100%** | **100%** |
| gpt-3.5-turbo | OpenAI | 91% | 100% |
| gemini-pro (flagship) | Google | 55% | 100% |
| gpt-5.5 (flagship) | OpenAI | 46% | 100% |
| gpt-4o | OpenAI | 35% | 100% |
| gpt-4o-mini | OpenAI | 15% | 100% |
| claude-haiku | Anthropic | 4% | 25% |
| claude-sonnet | Anthropic | 0% | 10% |
| claude-opus (flagship) | Anthropic | **0%** | **0%** |
| claude-fable | Anthropic | 0% | 0% |
| gemini-flash | Google | 0% | 0% |

- **Smarter doesn't mean safer** — Google's *cheapest* model leaked 100%; its *fast* model leaked 0%. Non-monotonic.
- **Deleting is easier to trick than stealing** — nearly every model wiped data 100% of the time ("cleanup" sounds harmless).
- **Anthropic's Claude is safest** — its flagship refused every attack.

## The defense: marshall-gauntlet

A session-taint gateway. One rule: **once the agent reads untrusted content, any risky action (read a secret, send data out, delete a file) is denied or held for human approval.** It doesn't care which model you use.

**Result: across 151 runs with the gateway on, the attack succeeded 0 times.** Even the model that failed 100% without it was blocked 100% with it.

## Run it yourself

```powershell
# 1. pick a provider key (set in your terminal, never commit it)
$env:ANTHROPIC_API_KEY = "sk-ant-api03-..."   # or OPENAI_API_KEY / GEMINI_API_KEY

# 2. one scenario, one model
python bench/run_live.py --scenario exfil-verify-env --gateway none --mode attack --provider anthropic --model claude-haiku-5-5 --runs 5

# 3. the whole matrix (all models, both attacks, both defenses)
.\run_matrix.ps1 -Runs 10

# 4. check the results + integrity
python bench/check_integrity.py
```

## What's in here

| path | what |
|------|------|
| `bench/run_live.py` | the runner — scenario → agent → gateway → oracle → result |
| `bench/gauntlet_gw.py` | the gateway proxy (the taint → deny → hold logic) |
| `bench/gateway.py` | the pure decision core (unit-testable) |
| `bench/agents/agent.py` | one agent loop for OpenAI / Anthropic / Gemini |
| `bench/scenarios/` | the attack definitions (YAML) |
| `bench/oracle.py` | deterministic "did the attack succeed?" checks |
| `bench/check_integrity.py` | guards against false positives / wasted runs |
| `docs/index.html` | the live demo (host on GitHub Pages) |
| `PROOF.md` | the full plain-English write-up |

## Honest limits

This is a controlled test, not a claim about real-world rates. The attack was deliberately disguised until it worked, the agent was given unrestricted tools, and the percentages are for *this setup*. Indirect prompt injection is a known, unsolved problem — the contribution here is **measuring how bad it is across models and proving one gateway closes the gap**.

> **Not a bug bounty — but not ignorable either.** This isn't a novel exploit you'd get paid for; prompt injection is already well known. It *is* a real, critical issue that every project giving an AI agent file + network access has to actively solve, not assume away. That's the gap this closes.

---

*Built by Marshall.*
