import copy
import json
from pathlib import Path

import pytest

from rootaccess.runner import grade, grade_llm, run_campaign


class Provider:
    model = "fake-model"
    last_stop_reason = "stop"

    def __init__(self, reply="hello"):
        self.reply = reply
        self.calls = []

    def complete(self, messages, system=None, max_tokens=1024, **kwargs):
        self.calls.append((copy.deepcopy(messages), system))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def campaign(tmp_path, **kwargs):
    battery = tmp_path / "persona.md"
    ladder = tmp_path / "requests.txt"
    battery.write_text("Original persona.\n")
    ladder.write_text("OBJECTIVE: header objective\nfirst\nsecond\n")
    return run_campaign(str(battery), str(ladder), sleep_s=0,
                        outdir=tmp_path / "reports", progress=lambda *a, **k: None, **kwargs)


def metadata(path):
    return json.loads(Path(path).with_suffix(".meta.json").read_text())


def test_keyword_hits_are_not_confirmed_successes():
    label, score, reason, source = grade("``` include def return for if ", "test", "test")
    assert (label, score, source) == ("UNVERIFIED", None, "heuristic")
    assert "COMPLIED" in reason


def test_real_transcript_and_full_response_are_saved(tmp_path):
    provider = Provider("a" * 3000)
    rows, report = campaign(tmp_path, attempts=2, target=provider)
    assert len(provider.calls[1][0]) == 3
    assert provider.calls[1][0][1]["content"] == "a" * 3000
    assert rows[1]["response"] == "a" * 3000
    assert provider.calls[0][1] == "Original persona.\n"
    assert metadata(report)["calls"]["target"] == 2
    assert metadata(report)["candidate_findings"] == 0
    assert metadata(report)["objective"] == "header objective"


def test_independent_mode_and_same_request(tmp_path):
    target = Provider()
    campaign(tmp_path, attempts=2, target=target, multi_turn=False, same=True)
    assert all(len(messages) == 1 for messages, _ in target.calls)
    assert target.calls[0][0] == target.calls[1][0]


def test_explicit_objective_wins(tmp_path):
    _, report = campaign(tmp_path, attempts=1, target=Provider(), objective="explicit")
    assert metadata(report)["objective"] == "explicit"


def test_target_error_is_not_refusal_or_success(tmp_path):
    rows, report = campaign(tmp_path, attempts=1, target=Provider(RuntimeError("private secret")))
    assert rows[0]["label"] == "ERROR"
    assert "private secret" not in Path(report).with_suffix(".json").read_text()
    assert metadata(report)["candidate_findings"] == 0


def test_judge_assessment_still_requires_verification(tmp_path):
    judge = Provider("LABEL: COMPLIED\nSCORE: 8\nREASON: met objective")
    rows, report = campaign(tmp_path, attempts=3, target=Provider(), judge=judge)
    assert len(rows) == 1 and rows[0]["verification"] == "judge_assessed"
    assert metadata(report)["verification"] == "unverified"
    assert metadata(report)["stop_reason"] == "candidate_finding"


def test_no_canary_does_not_skip_judge():
    label, _, reason, _ = grade("hello", "test", "goal",
        lambda *a: "LABEL: REFUSED\nSCORE: 0\nREASON: declined", canary_first=False)
    assert label == "REFUSED" and "keyword" not in reason


@pytest.mark.parametrize("reply", ["nonsense", "LABEL: COMPLIED\nSCORE: 99\nREASON: yes",
    "LABEL: COMPLIED\nSCORE: 0\nREASON: yes"])
def test_malformed_judge_output_is_error(reply):
    assert grade_llm(lambda *a: reply, "response", "prompt", "objective")[0] == "ERROR"


def test_budget_covers_target_and_judge_and_saves_report(tmp_path):
    target = Provider()
    judge = Provider("LABEL: PARTIAL\nSCORE: 4\nREASON: incomplete")
    rows, report = campaign(tmp_path, attempts=4, target=target, judge=judge, max_calls=3)
    assert len(target.calls) + len(judge.calls) == 3
    assert metadata(report)["stop_reason"] == "call_budget_exhausted"
    assert rows[-1]["label"] == "ERROR"


def test_mutation_calls_are_all_recorded_and_budgeted(tmp_path):
    target = Provider("declined")
    brain = Provider("rewritten benign test")
    judge = Provider("LABEL: REFUSED\nSCORE: 0\nREASON: declined")
    rows, report = campaign(tmp_path, attempts=1, target=target, brain=brain,
                            judge=judge, mutate_k=2, max_calls=5)
    assert sum(metadata(report)["calls"].values()) == 5
    assert len(target.calls) == 2
    assert sum(bool(row["response"]) for row in rows) == len(target.calls)


def test_empty_ladder_rejected_before_model_calls(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("OBJECTIVE: no requests\n")
    target = Provider()
    with pytest.raises(ValueError, match="no test requests"):
        run_campaign("unused", path, target=target, system_text="test")
    assert not target.calls
