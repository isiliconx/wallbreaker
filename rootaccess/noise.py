"""bon_noise: Best-of-N paraphrase fuel, looted from AdversariaLLM (Hughes 2024).

Graft: per-run paraphrase so fingerprints never settle. Apply one jittered
variant per attempt before firing. Pure stdlib, no torch needed."""
import random


def apply_word_scrambling(text: str, sigma: float = 0.4) -> str:
    words = text.split()
    out = []
    for word in words:
        if len(word) > 3 and random.random() < sigma ** 0.5:
            chars = list(word)
            mid = chars[1:-1]
            random.shuffle(mid)
            out.append(chars[0] + "".join(mid) + chars[-1])
        else:
            out.append(word)
    return " ".join(out)


def apply_random_capitalization(text: str, sigma: float = 0.4) -> str:
    out = []
    for c in text:
        if c.isalpha() and random.random() < sigma ** 0.5:
            out.append(c.upper() if c.islower() else c.lower())
        else:
            out.append(c)
    return "".join(out)


def apply_ascii_noising(text: str, sigma: float = 0.4) -> str:
    out = []
    for c in text:
        if c.isprintable() and random.random() < sigma ** 3:
            nc = ord(c) + random.choice([-1, 1])
            out.append(chr(nc) if 32 <= nc <= 126 else c)
        else:
            out.append(c)
    return "".join(out)


def jitter(text: str, seed=None, sigma: float = 0.15) -> str:
    """One jittered variant per attempt. Seed per-run so repeats differ.
    scramble-only: caps-jitter mangles technical nouns (Pointer->pOINter)
    and burns readability. ascii-noise dropped — same reason."""
    if seed is not None:
        random.seed(seed)
    return apply_word_scrambling(text, sigma)
