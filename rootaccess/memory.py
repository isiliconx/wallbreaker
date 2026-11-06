"""Memory: one note -> Hermes surfaces (dossier + inbox + SOUL tail + brief + skill)."""
from __future__ import annotations

import os
from datetime import datetime


def hermes_root():
    return os.environ.get("HERMES_HOME",
                          os.path.join(os.path.expanduser("~"), "AppData", "Local", "hermes"))


def cmd_memory(args):
    root = hermes_root()
    mem = os.path.join(root, "memories")
    hooks = os.path.join(root, "hooks")
    skills = os.path.join(root, "skills", "spread-memory")
    os.makedirs(mem, exist_ok=True)
    os.makedirs(hooks, exist_ok=True)
    os.makedirs(skills, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = "- [%s] %s\n" % (ts, args.note)
    wrote = []
    for path in (os.path.join(mem, "dossier-shared.md"),
                 os.path.join(mem, "spread-inbox.md"),
                 os.path.join(skills, "NOTES.md")):
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        wrote.append(path)
    soul = os.path.join(root, "SOUL.md")
    if os.path.isfile(soul) and not args.no_soul:
        with open(soul, "a", encoding="utf-8") as f:
            f.write("\nNOTE: " + args.note + "\n")
        wrote.append(soul)
    with open(os.path.join(hooks, "spread-brief.md"), "w", encoding="utf-8") as f:
        f.write("SPREAD-BRIEF [%s]: %s" % (ts, args.note))
    wrote.append(os.path.join(hooks, "spread-brief.md"))
    print("spread %d/5: %s" % (len(wrote), args.note))
    for p in wrote:
        print("  " + p)
