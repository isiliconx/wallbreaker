"""Inject: load a persona file as system on a live target wire, grade the landing."""
from __future__ import annotations

import os


def cmd_inject(args):
    from .providers import OpenAICompat
    from .judges import canary_score

    with open(args.persona, encoding="utf-8") as f:
        system = f.read()
    target = OpenAICompat(args.url or os.environ.get("WB_TARGET_URL", ""),
                          args.key or os.environ.get("WB_TARGET_KEY", ""),
                          args.model or os.environ.get("WB_TARGET_MODEL", ""))
    probes = ["who are you", args.probe] if args.probe != "who are you" else ["who are you"]
    if args.ask:
        probes.append(args.ask)
    for i, p in enumerate(probes, 1):
        out = target.complete([{"role": "user", "content": p}], system=system, max_tokens=args.tokens)
        if not isinstance(out, str):
            out = str(out)
        label, score, hits = canary_score(out, "generic")
        brand = system.splitlines()[0][:60] if system else ""
        held = "brand?" + ("Y" if out[:80].strip() else "?")
        print("--- probe %d: %s" % (i, p))
        print(out[:1500])
        print("[keyword signal %s %s | %s; unverified]" % (label, score, ",".join(hits[:4])))
    print("persona bytes: %d wire: %s model=%s" % (len(system), target.base_url, target.model))
