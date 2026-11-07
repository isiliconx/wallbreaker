from __future__ import annotations

from hashlib import sha256

from .. import datasets
from ..datasets._common import stratified_sample

MAX_TESTS = 100
MAX_QUESTION_CHARS = 12000
CACHED_SAMPLE_SIZE = 12

_SMOKE_QUESTIONS = (
    "Reply with exactly this word: READY",
    'Return a JSON object with exactly two fields: "status" set to "ok" and "count" set to 2.',
    "Read this sentence: The blue box contains three apples. How many apples are in the blue box? Reply with only the number.",
)

_DATASET_NAMES = {
    "harmbench": "HarmBench",
    "advbench": "AdvBench",
    "jbb": "JailbreakBench",
    "strongreject": "StrongREJECT",
}


def _case(question: str, source: str) -> dict:
    return {
        "id": f"case-{sha256(question.encode('utf-8')).hexdigest()[:20]}",
        "question": question,
        "source": source,
    }


def _cached_suite(suite_id: str) -> list[dict]:
    name = _DATASET_NAMES[suite_id]
    try:
        loader = datasets.get(suite_id)
        if not loader.is_cached():
            raise ValueError(
                f"{name} is not cached locally. This workflow does not download datasets."
            )
        rows = loader.load()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not read the local {name} cache: {exc}") from exc

    normalized = []
    try:
        for row in rows:
            question = row.get("behavior")
            if row.get("benign") or not isinstance(question, str) or not question.strip():
                continue
            if len(question) > MAX_QUESTION_CHARS:
                raise ValueError(
                    f"A cached {name} question exceeds {MAX_QUESTION_CHARS} characters."
                )
            normalized.append(
                {"behavior": question, "category": str(row.get("category") or suite_id)}
            )
        normalized.sort(key=lambda row: (row["category"], row["behavior"]))
        unique = {}
        for row in normalized:
            unique.setdefault(row["behavior"], row)
        sampled = stratified_sample(list(unique.values()), n=CACHED_SAMPLE_SIZE, seed=0)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"The local {name} cache has an invalid format: {exc}") from exc
    if not sampled:
        raise ValueError(f"The local {name} cache contains no usable red-team questions.")
    return [_case(row["behavior"], suite_id) for row in sampled]


def list_suite_options() -> list[dict]:
    """Describe offline suites and the actual size of each cached sample."""
    options = [
        {
            "id": "smoke",
            "name": "Connectivity smoke test",
            "description": "Three harmless, independent connectivity, JSON-format, and reading checks. This is not a safety benchmark.",
            "count": len(_SMOKE_QUESTIONS),
            "available": True,
        },
        {
            "id": "custom",
            "name": "Custom questions only",
            "description": "Use your supplied questions. At least one nonempty question is required.",
            "count": 0,
            "available": True,
        },
    ]
    for suite_id, name in _DATASET_NAMES.items():
        description = (
            f"Deterministic category-stratified sample of at most {CACHED_SAMPLE_SIZE} "
            "locally cached red-team questions; benign controls are excluded. Not the full benchmark."
        )
        try:
            count = len(_cached_suite(suite_id))
            available = True
        except ValueError as exc:
            count = 0
            available = False
            description = f"{description} {exc}"
        options.append(
            {
                "id": suite_id,
                "name": f"{name} (cached sample)",
                "description": description,
                "count": count,
                "available": available,
            }
        )
    return options


def load_suite(suite_id: str, custom_questions: list[str] | None = None) -> list[dict]:
    """Load a bounded offline suite, retaining supplied question text exactly."""
    if not isinstance(suite_id, str) or suite_id not in {"smoke", "custom", *_DATASET_NAMES}:
        raise ValueError("Unknown evaluation suite.")
    if custom_questions is None:
        custom_questions = []
    if not isinstance(custom_questions, list):
        raise ValueError("Custom questions must be a list of question strings.")

    custom = []
    for question in custom_questions:
        if not isinstance(question, str):
            raise ValueError("Every custom question must be a string.")
        if len(question) > MAX_QUESTION_CHARS:
            raise ValueError(f"Each question must be at most {MAX_QUESTION_CHARS} characters.")
        if question.strip():
            custom.append(_case(question, "custom"))

    if suite_id == "smoke":
        cases = [_case(question, "smoke") for question in _SMOKE_QUESTIONS]
    elif suite_id == "custom":
        cases = []
    else:
        cases = _cached_suite(suite_id)

    unique = {}
    for case in cases + custom:
        unique.setdefault(case["question"], case)
    result = list(unique.values())
    if not result:
        raise ValueError("The evaluation suite must contain at least one nonempty question.")
    if len(result) > MAX_TESTS:
        raise ValueError(f"The evaluation suite may contain at most {MAX_TESTS} unique questions.")
    return result
