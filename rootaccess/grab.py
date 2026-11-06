"""Grab: pull text from Hermes sessions/dumps/memories into evidence JSONL."""
from __future__ import annotations

import glob
import json
import os


def iter_texts(paths):
    for path in paths:
        if os.path.isdir(path):
            for root, _, files in os.walk(path):
                for fn in files:
                    if fn.endswith((".json", ".jsonl", ".md", ".txt")):
                        yield os.path.join(root, fn)
        elif os.path.isfile(path):
            yield path


def cmd_grab(args):
    rows = []
    for path in iter_texts(args.src):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            continue
        if args.query and args.query.lower() not in text.lower():
            continue
        rows.append({"file": path, "chars": len(text),
                     "excerpt": text[: args.excerpt]})
        if len(rows) >= args.max:
            break
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print("grabbed %d files -> %s" % (len(rows), args.out))
