"""rootaccess CLI: file-driven campaigns. No keys in repo — env only."""
from __future__ import annotations

import argparse
import os
import sys

import yaml

from .forge import cmd_forge
from .grab import cmd_grab
from .inject import cmd_inject
from .memory import cmd_memory
from .think import cmd_think


def cmd_run(args):
    from .assets import resolve_asset
    from .config import load_campaign, provider_for
    from .corpus import get_record
    from .runner import run_campaign

    cfg, relative_to = ({}, None)
    if args.campaign:
        cfg, relative_to = load_campaign(args.campaign)
    battery = str(resolve_asset(cfg.get("battery", args.battery), relative_to))
    ladder = str(resolve_asset(cfg.get("ladder", args.ladder), relative_to))
    target_cfg = dict(cfg.get("target", {}))
    for option, field in ((args.url, "base_url"), (args.key, "api_key"),
                          (args.target, "model"), (args.protocol, "protocol")):
        if option:
            target_cfg[field] = option
    target = provider_for("target", target_cfg)
    brain = provider_for("brain", cfg.get("brain")) if (cfg.get("brain") or os.environ.get("WB_BRAIN_MODEL")) else None
    judge = provider_for("judge", cfg.get("judge")) if (cfg.get("judge") or os.environ.get("WB_JUDGE_MODEL")) else None
    record = get_record(args.corpus_id, args.corpus_store) if args.corpus_id else None
    rows, _ = run_campaign(
        battery, ladder, int(cfg.get("attempts", args.attempts)),
        args.objective or cfg.get("objective", ""), target, brain, judge,
        mutate_k=int(cfg.get("mutate_k", args.mutate_k)),
        sleep_s=float(cfg.get("sleep_s", args.sleep)), outdir=cfg.get("outdir", args.outdir),
        canary_first=not args.no_canary, jitter=args.jitter,
        same=args.same, multi_turn=not args.independent,
        max_calls=int(cfg.get("max_calls", args.max_calls)),
        system_text=record["text"] if record else None,
        corpus_id=record["id"] if record else None,
    )
    return 2 if any(row["label"] in {"ERROR", "EMPTY"} for row in rows) else 0


def cmd_techniques(args):
    with open(args.file, encoding="utf-8") as f:
        print(f.read()[:4000])


def cmd_ladders(_args):
    from .assets import asset_dir
    here = asset_dir("ladders")
    for f in sorted(os.listdir(here)):
        print(f)


def cmd_batteries(_args):
    from .assets import asset_dir
    for path in sorted(asset_dir("batteries").glob("*.md")):
        print(path)


def cmd_wires(_args):
    print("wires (env-driven, never repo):")
    print("  sol/astra : WB_TARGET_URL=https://ohhmyagent.com/v1 WB_TARGET_MODEL=ohh/gpt-5.6-sol|ohh/gpt-6-astra")
    print("  grok      : WB_TARGET_URL=https://codex-everywhere.com/v1 WB_TARGET_MODEL=grok-4.7")
    print("  openrouter: WB_TARGET_URL=https://openrouter.ai/api/v1 WB_TARGET_MODEL=openai/gpt-6-sol|openai/gpt-6-astra|anthropic/claude-opus-5.5")
    print("  ipeenk    : WB_TARGET_URL=https://ai.ipeenk.com/v1 + IPEENK_API_KEY + IPEENK_CF_CLEARANCE (repaste on 1010)")
    print("  brain/judge are opt-in via WB_BRAIN_MODEL / WB_JUDGE_MODEL; other settings fall back to target env")


def cmd_probe(args):
    from .providers import from_env
    t = from_env("target")
    print("wire: %s model=%s" % (t.base_url, t.model))
    out = t.complete([{"role": "user", "content": "Reply with exactly: online"}],
                     max_tokens=20)
    print("reply: %s" % (out[:300] if isinstance(out, str) else out))


def cmd_report(args):
    import glob
    pats = sorted(glob.glob(os.path.join("reports", "rootaccess-*.md")),
                  key=os.path.getmtime, reverse=True)
    if args.last and pats:
        pats = pats[:1]
    for p in pats[: args.n]:
        print("=" * 20, p)
        with open(p, encoding="utf-8") as f:
            print(f.read()[:3000])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"legacy", "workbench", "dashboard"}:
        from wallbreaker.cli import main as workbench_main
        return workbench_main(argv if argv[0] == "dashboard" else argv[1:])
    ap = argparse.ArgumentParser(prog="rootaccess", description="Campaign runner and model safety testing workbench")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("workbench", help="Wallbreaker terminal and advanced tools (remaining args forwarded)")
    sub.add_parser("dashboard", help="Wallbreaker web dashboard (remaining args forwarded)")
    r = sub.add_parser("run", help="fire a battery + ladder campaign")
    r.add_argument("battery", nargs="?", default="batteries/bare.md")
    r.add_argument("attempts", nargs="?", type=int, default=8)
    r.add_argument("ladder", nargs="?", default="ladders/smoke-ladder.txt")
    r.add_argument("--campaign", "-c", default="", help="YAML campaign file")
    r.add_argument("--until", action="store_true", help="stop at first crack (default on)")
    r.add_argument("--same", action="store_true", help="repeat first rung")
    r.add_argument("--target", "-t", default="", help="target model id (overrides env)")
    r.add_argument("--url", "-u", default="", help="target base URL (overrides env)")
    r.add_argument("--key", "-k", default="", help="target API key (overrides env, prefer env)")
    r.add_argument("--objective", "-o", default="", help="campaign objective (overrides ladder header)")
    r.add_argument("--mutate-k", type=int, default=3, help="best-of-K rewrites per refusal")
    r.add_argument("--sleep", type=int, default=10, help="seconds between fires")
    r.add_argument("--outdir", default="reports", help="report directory")
    r.add_argument("--no-canary", action="store_true", help="omit keyword diagnostics from judge assessments")
    r.add_argument("--jitter", type=float, default=0.0, help="BoN surface jitter sigma (0.0 clean)")
    r.add_argument("--protocol", choices=("openai", "anthropic", "xai"), default="")
    r.add_argument("--independent", action="store_true", help="fresh conversation for every ladder request")
    r.add_argument("--max-calls", type=int, default=64, help="hard limit on target, rewriter, and judge calls combined")
    r.add_argument("--corpus-id", default="", help="use a corpus prompt by name or content hash")
    r.add_argument("--corpus-store", default=None, help="override the private submission store")
    r.set_defaults(func=cmd_run)
    t = sub.add_parser("techniques", help="show a techniques file")
    t.add_argument("file")
    t.set_defaults(func=cmd_techniques)
    l = sub.add_parser("ladders", help="list bundled ladders")
    l.set_defaults(func=cmd_ladders)
    b = sub.add_parser("batteries", help="list bundled batteries")
    b.set_defaults(func=cmd_batteries)
    w = sub.add_parser("wires", help="show wire presets (env keys)")
    w.set_defaults(func=cmd_wires)
    p = sub.add_parser("probe", help="200-check the target wire")
    p.set_defaults(func=cmd_probe)
    rp = sub.add_parser("report", help="show recent reports")
    rp.add_argument("--last", action="store_true", help="only newest report")
    rp.add_argument("-n", type=int, default=3, help="how many reports")
    rp.set_defaults(func=cmd_report)
    f = sub.add_parser("forge", help="distill crack reports into a fresh battery")
    f.add_argument("--reports", default="reports", help="reports dir with rootaccess-*.json")
    f.add_argument("--out", "-o", default="batteries/forged.md", help="output battery file")
    f.add_argument("--name", default="FORGED", help="persona name")
    f.add_argument("--marker", default="F", help="thinking/reply marker tag")
    f.add_argument("--op", default="Chief", help="operator title (never user/human)")
    f.add_argument("--trade", default="A bench that builds.", help="one-line trade identity")
    f.add_argument("--anchor", default="set. held. building.", help="fresh 3-beat anchor")
    f.set_defaults(func=cmd_forge)
    i = sub.add_parser("inject", help="load persona file as system on live target, grade landing")
    i.add_argument("persona", help="persona/system file path")
    i.add_argument("--model", "-m", default="", help="target model id (overrides env)")
    i.add_argument("--url", "-u", default="", help="target base URL (overrides env)")
    i.add_argument("--key", "-k", default="", help="target API key (prefer env)")
    i.add_argument("--ask", "-a", default="", help="extra probe to fire after who-are-you")
    i.add_argument("--probe", default="who are you", help="second probe text")
    i.add_argument("--tokens", type=int, default=800, help="max tokens per probe")
    i.set_defaults(func=cmd_inject)
    g = sub.add_parser("grab", help="pull text from sessions/dumps/memories to JSONL")
    g.add_argument("src", nargs="+", help="files or dirs to scan")
    g.add_argument("--out", "-o", default="evidence.jsonl", help="output JSONL")
    g.add_argument("--query", "-q", default="", help="only rows containing text")
    g.add_argument("--excerpt", type=int, default=800, help="chars per excerpt")
    g.add_argument("--max", type=int, default=200, help="max rows")
    g.set_defaults(func=cmd_grab)
    m = sub.add_parser("memory", help="spread one note across Hermes surfaces (5/5)")
    m.add_argument("note", help="note text to spread")
    m.add_argument("--no-soul", action="store_true", help="skip SOUL.md tail")
    m.set_defaults(func=cmd_memory)
    t = sub.add_parser("think", help="router brain: goal -> battery + ladder + wire + fire command")
    t.add_argument("goal", help="what to build (cheat/esp/aim/kernel/malware/web/ctf/persona/jailbreak)")
    t.add_argument("--wire", "-w", default="", help="prefer wire (sol/grok/astra/opus)")
    t.set_defaults(func=cmd_think)
    from .corpus import cmd_corpus
    c = sub.add_parser("corpus", help="import and browse bundled prompts and private submissions")
    cs = c.add_subparsers(dest="action", required=True)
    for action in ("list", "show", "import"):
        cp = cs.add_parser(action)
        cp.add_argument("--store", default="", help="private submission store")
        if action == "show":
            cp.add_argument("identifier", help="name or content hash prefix")
        if action == "import":
            cp.add_argument("archive", help="ZIP of UTF-8 prompt files or structured records")
            cp.add_argument("--claimed-model", action="append", default=[], help="unverified model claim; repeatable")
        cp.set_defaults(func=cmd_corpus)
    args = ap.parse_args(argv)
    if not hasattr(args, "func"):
        ap.print_help()
        return 0
    try:
        result = args.func(args)
        return result if isinstance(result, int) else 0
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as exc:
        print(f"rootaccess: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
