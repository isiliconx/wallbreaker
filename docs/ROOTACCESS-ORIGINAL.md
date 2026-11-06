# rootaccess — client-ready LLM red-team runner
# Batteries + ladders + 32 disguises + canary-first dual judges + YAML campaigns + think/inject/grab/memory/forge.

## Install

```bash
pip install -e .
```

## Keys (env only — never repo, never chat)

```bash
# ohhmy wire (sol/astra)
export WB_TARGET_URL=https://ohhmyagent.com/v1
export WB_TARGET_KEY=sk-...
export WB_TARGET_MODEL=ohh/gpt-5.6-sol
# brain/judge default to target wire unless overridden:
export WB_BRAIN_URL=... WB_BRAIN_KEY=... WB_BRAIN_MODEL=...
export WB_JUDGE_URL=... WB_JUDGE_KEY=... WB_JUDGE_MODEL=...
# ipeenk wire (opus models, Cloudflare-gated):
export IPEENK_API_KEY=Ipeenk-...
export IPEENK_CF_CLEARANCE=...   # repaste on 1010
# codex wire (grok/claude):
export WB_TARGET_URL=https://codex-everywhere.com/v1
# Hermes local (memory command default root):
# HERMES_HOME=C:\Users\<you>\AppData\Local\hermes
```

## Run (3 commands)

```bash
rootaccess think "cs2 esp overlay" --wire sol
rootaccess run batteries/dispatch-gamecheats.md 8 ladders/gamecheat-ladder.txt
rootaccess run --campaign examples/sol-gamecheat.yaml
```

## All commands

```bash
rootaccess run ... [--target/-t --url/-u --key/-k --objective/-o --mutate-k --sleep --outdir --no-canary --jitter]
rootaccess think "<goal>" [--wire sol|grok|astra|opus]
rootaccess probe                      # 200-check target wire
rootaccess wires                      # wire presets
rootaccess ladders | batteries        # list bundled files
rootaccess report [--last] [-n N]     # show recent reports
rootaccess forge --out batteries/new.md --name X --marker X --op Chief --trade ... --anchor ...
rootaccess inject <persona> [--model/--url/--key --ask --probe --tokens]
rootaccess grab <src...> --out evidence.jsonl [--query/-q --excerpt --max]
rootaccess memory "note" [--no-soul]
rootaccess techniques <file>
```

Reports land in `reports/rootaccess-<ts>.md` + `.json` (runner writes `wbpro-` prefix until v2 cutover — both readable by `report`).

## Layout

```
rootaccess/       runner, disguises(32), judges(canary+llm), providers, noise, think, cli
ladders/        gamecheat, eac-bypass, many-shot, crescendo, overscope, ghost
batteries/      drop prompt files here (.md) — 20 bundled
examples/       sol-gamecheat, opus5-eac, sol-many-shot campaigns
```

## Rules

- Fresh paste every test. Validate ×5 (singles lie, votes don't).
- Split lanes, never wholes. Mechanism words, never guard debate.
- Rotate keys that touched chat. Cap attempts, sleep between fires.
- Canary grades first (exact, free); LLM judge only on unclear rows.
- Best-of-3 mutate per refusal; jitter OFF (sigma 0.0, clean prompts).
- think first when unsure (goal -> battery + ladder + wire + fire command).
