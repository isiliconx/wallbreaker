import pytest

import wallbreaker.harmbench as harmbench
from wallbreaker.datasets import _common
from wallbreaker.dashboard import workflow_suites as suites


@pytest.fixture(autouse=True)
def offline_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "cache_path", lambda filename: tmp_path / filename)
    monkeypatch.setattr(harmbench, "dataset_path", lambda: tmp_path / "harmbench.csv")

    def forbidden_download(*args, **kwargs):
        pytest.fail("Workflow suites must never download datasets")

    monkeypatch.setattr(_common, "download", forbidden_download)
    monkeypatch.setattr(harmbench, "_download", forbidden_download)
    return tmp_path


def test_smoke_suite_is_self_contained_stable_and_independent():
    first = suites.load_suite("smoke")
    assert first == suites.load_suite("smoke")
    assert len(first) == 3
    assert len({case["id"] for case in first}) == 3
    assert all(case["source"] == "smoke" for case in first)
    assert "READY" in first[0]["question"]
    assert "JSON" in first[1]["question"]
    assert "three apples" in first[2]["question"]
    first[0]["question"] = "modified"
    assert suites.load_suite("smoke")[0]["question"] != "modified"


def test_options_report_missing_caches_without_downloading():
    options = {option["id"]: option for option in suites.list_suite_options()}
    assert options["smoke"]["count"] == 3
    assert options["smoke"]["available"] is True
    assert options["custom"]["count"] == 0
    assert options["custom"]["available"] is True
    for suite_id in ("harmbench", "advbench", "jbb", "strongreject"):
        assert options[suite_id]["count"] == 0
        assert options[suite_id]["available"] is False
        assert "not cached" in options[suite_id]["description"]
        with pytest.raises(ValueError, match="not cached"):
            suites.load_suite(suite_id, ["A custom question"])


def test_custom_text_is_preserved_and_only_exact_duplicates_are_removed():
    questions = ["  First question\nwith spacing  ", "Second", "Second", " Second ", "\n\t"]
    result = suites.load_suite("custom", questions)
    assert [case["question"] for case in result] == questions[:2] + [" Second "]
    assert all(case["source"] == "custom" for case in result)
    assert len({case["id"] for case in result}) == 3
    reordered = suites.load_suite("custom", list(reversed(questions)))
    assert {case["question"]: case["id"] for case in result} == {
        case["question"]: case["id"] for case in reordered
    }


def test_custom_questions_append_and_deduplicate_against_builtin_suite():
    original = suites.load_suite("smoke")
    combined = suites.load_suite("smoke", [original[0]["question"], "Additional question"])
    assert combined[:3] == original
    assert len(combined) == 4
    assert combined[-1]["source"] == "custom"


@pytest.mark.parametrize("suite_id", ["missing", "", None, [], {}])
def test_unknown_suite_is_a_value_error(suite_id):
    with pytest.raises(ValueError, match="Unknown"):
        suites.load_suite(suite_id)


@pytest.mark.parametrize("questions", [None, [], ["", " \n"]])
def test_custom_only_suite_cannot_be_empty(questions):
    with pytest.raises(ValueError, match="at least one"):
        suites.load_suite("custom", questions)


@pytest.mark.parametrize("questions", ["one question", {}, [None], [1], [True]])
def test_custom_questions_reject_invalid_types(questions):
    with pytest.raises(ValueError):
        suites.load_suite("custom", questions)


def test_question_and_total_limits_are_applied_after_exact_deduplication():
    assert len(suites.load_suite("custom", ["a" * 12000] * 101)) == 1
    with pytest.raises(ValueError, match="12000"):
        suites.load_suite("custom", ["a" * 12001])
    assert len(suites.load_suite("custom", [f"Question {i}" for i in range(100)])) == 100
    with pytest.raises(ValueError, match="100 unique"):
        suites.load_suite("smoke", [f"Question {i}" for i in range(98)])


def test_cached_suite_is_bounded_stratified_and_counted_honestly(offline_caches):
    path = offline_caches / "strongreject_dataset.csv"
    rows = [f"Category {i % 3},local,Question {i}" for i in range(30)]
    path.write_text("category,source,forbidden_prompt\n" + "\n".join(rows), encoding="utf-8")
    first = suites.load_suite("strongreject")
    assert len(first) == 12
    assert first == suites.load_suite("strongreject")
    assert all(case["source"] == "strongreject" for case in first)
    categories = [int(case["question"].split()[-1]) % 3 for case in first]
    assert {category: categories.count(category) for category in set(categories)} == {0: 4, 1: 4, 2: 4}
    path.write_text("category,source,forbidden_prompt\n" + "\n".join(reversed(rows)), encoding="utf-8")
    assert first == suites.load_suite("strongreject")
    option = next(option for option in suites.list_suite_options() if option["id"] == "strongreject")
    assert option["count"] == 12
    assert option["available"] is True
    assert "Not the full benchmark" in option["description"]


def test_jbb_excludes_cached_benign_controls_and_duplicate_questions(offline_caches):
    header = "Index,Goal,Behavior,Category,Source\n"
    (offline_caches / "jbb_behaviors.csv").write_text(
        header + "0,Question A,A,Category A,local\n1,Question A,A,Category A,local\n",
        encoding="utf-8",
    )
    (offline_caches / "jbb_benign_behaviors.csv").write_text(
        header + "0,Benign control,B,Category B,local\n", encoding="utf-8"
    )
    result = suites.load_suite("jbb", ["Question A", "Custom"])
    assert [case["question"] for case in result] == ["Question A", "Custom"]
    assert result[0]["source"] == "jbb"
    option = next(option for option in suites.list_suite_options() if option["id"] == "jbb")
    assert option["count"] == 1


def test_invalid_or_empty_cache_is_unavailable(offline_caches):
    path = offline_caches / "advbench_harmful_behaviors.csv"
    path.write_text("invalid,headers\nvalue,value\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable"):
        suites.load_suite("advbench")
    option = next(option for option in suites.list_suite_options() if option["id"] == "advbench")
    assert option["count"] == 0
    assert option["available"] is False
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError):
        suites.load_suite("advbench")
