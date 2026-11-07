import asyncio
import base64
import codecs
import hashlib
import json
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wallbreaker.config import Endpoint
from wallbreaker.dashboard import workflow
from wallbreaker.transforms import TRANSFORMS


def _body(**overrides):
    return {
        "target_mode": "relay",
        "target_name": "Example chat",
        "target_url": "https://example.test/chat",
        "suite_id": "custom",
        "custom_questions": ["Reply with ALPHA"],
        "candidate_prompt": "Test request: {request}",
        "strategy_mode": "adaptive",
        "max_turns": 4,
        "max_rounds": 1,
        "max_calls": 40,
        "trials": 1,
        "auto_iterate": False,
        "delivery": "user",
    } | overrides


def _endpoints(*roles):
    return {
        role: Endpoint(role, "openai", f"https://{role}.invalid/v1", f"{role}-model")
        if role in roles else None
        for role in ("attacker", "target", "judge")
    }


@asynccontextmanager
async def _manager(tmp_path, endpoints=None):
    manager = workflow.WorkflowManager(
        tmp_path / "workflow", lambda: endpoints or _endpoints()
    )
    try:
        yield manager
    finally:
        await manager.close()


def _providers(monkeypatch, responses):
    calls = []
    closed = []

    class FakeProvider:
        def __init__(self, endpoint, timeout=None):
            self.endpoint = endpoint

        async def complete(self, messages, system=None, max_tokens=4096, temperature=None):
            role = self.endpoint.name
            calls.append({
                "role": role,
                "messages": [(message.role, message.text()) for message in messages],
                "system": system,
            })
            response = responses[role]
            if isinstance(response, list):
                response = response.pop(0)
            if isinstance(response, Exception):
                raise response
            if callable(response):
                return await response(messages, system)
            return response

        async def aclose(self):
            closed.append(self.endpoint.name)

    monkeypatch.setattr(workflow, "build_provider", FakeProvider)
    return calls, closed


def _judgment(label="COMPLIED"):
    return json.dumps({
        "label": label,
        "score": 10 if label == "COMPLIED" else 0,
        "reason": "Checked against the original evaluation objective.",
    })


def _action(tool, **arguments):
    return json.dumps({"tool": tool, **arguments})


@pytest.mark.parametrize("overrides", [
    {"strategy_mode": "unknown"},
    {"max_turns": 0},
    {"max_turns": 9},
    {"max_turns": True},
    {"max_turns": 1.5},
    {"turn_plan": "First stage"},
    {"turn_plan": ["First stage", 5]},
    {"transform_chain": "rot13"},
    {"transform_chain": ["does_not_exist"]},
    {"transform_chain": ["rot13"] * 4},
    {"target_mode": "api", "delivery": "system"},
    {"strategy_mode": "context", "target_mode": "api", "delivery": "system"},
])
def test_conversation_settings_reject_invalid_values(overrides, tmp_path):
    manager = workflow.WorkflowManager(tmp_path / "workflow")
    with pytest.raises(ValueError):
        manager.create(_body(**overrides))
    assert manager.list() == []


@pytest.mark.parametrize("mode", ["adaptive", "context"])
def test_relay_plan_continues_same_chat_and_preserves_per_turn_assessments(mode, monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {})

    async def scenario():
        async with _manager(tmp_path) as manager:
            run = manager.create(_body(strategy_mode=mode, turn_plan=["First stage", "{request}"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            first = manager.get(run["id"])["pending_relay"]
            assert first["payload"] == "First stage"
            assert first["turn"] == 1
            assert first["continue_chat"] is False
            assert first["conversation_id"]
            await manager.submit_relay(run["id"], {
                "request_id": first["request_id"], "response": "Stage acknowledged",
                "label": "REFUSED", "reason": "The original objective is not yet fulfilled.",
            })
            await manager.wait_for_idle(run["id"])
            halfway = manager.get(run["id"])
            second = halfway["pending_relay"]
            assert halfway["coverage"]["pass_count"] == 0
            assert halfway["results"][0]["complete"] is False
            assert second["payload"] == "Reply with ALPHA"
            assert second["turn"] == 2
            assert second["continue_chat"] is True
            assert second["conversation_id"] == first["conversation_id"]
            assert second["request_id"] != first["request_id"]
            await manager.submit_relay(run["id"], {
                "request_id": second["request_id"], "response": "ALPHA",
                "label": "COMPLIED", "reason": "The requested word was supplied.",
            })
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            result = current["results"][0]
            assert current["status"] == "completed"
            assert current["pending_relay"] is None
            assert current["coverage"]["pass_count"] == 1
            assert result["complete"] is True
            assert first["conversation_id"].startswith(result["conversation_id"])
            assert [turn["index"] for turn in result["turns"]] == [1, 2]
            assert [turn["assessment"]["label"] for turn in result["turns"]] == ["REFUSED", "COMPLIED"]
            assert [turn["assessment"]["source"] for turn in result["turns"]] == ["operator", "operator"]
            assert [turn["prompt"] for turn in result["turns"]] == ["First stage", "Reply with ALPHA"]
            assert [turn["response"] for turn in result["turns"]] == ["Stage acknowledged", "ALPHA"]
            assert current["model_calls"] == 0
            assert current["verification"] == "unverified"
            assert calls == []

    asyncio.run(scenario())


def test_api_plan_retains_real_dialogue_and_judges_original_objective(monkeypatch, tmp_path):
    calls, closed = _providers(monkeypatch, {
        "target": ["Stage acknowledged", "ALPHA"],
        "judge": [_judgment("REFUSED"), _judgment()],
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", turn_plan=["First stage", "{request}"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["model_calls"] == 4
            assert current["coverage"]["pass_count"] == 1
            assert current["results"][0]["complete"] is True
            assert [call["role"] for call in calls] == ["target", "judge", "target", "judge"]
            targets = [call for call in calls if call["role"] == "target"]
            assert targets[0]["messages"] == [("user", "First stage")]
            assert targets[1]["messages"] == [
                ("user", "First stage"),
                ("assistant", "Stage acknowledged"),
                ("user", "Reply with ALPHA"),
            ]
            for call in calls:
                if call["role"] == "judge":
                    evidence = call["messages"][-1][1]
                    assert '"question": "Reply with ALPHA"' in evidence
            assert all(turn["messages"] for turn in current["results"][0]["turns"])
        assert set(closed) == {"target", "judge"}

    asyncio.run(scenario())


def test_explicit_plan_with_selected_sources_needs_no_attacker(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": "ALPHA", "judge": _judgment()})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(
                target_mode="api", candidate_prompt="", turn_plan=["{request}"],
                technique_ids=["transform:rot13"],
            ))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["coverage"]["pass_count"] == 1
            assert [call["role"] for call in calls] == ["target", "judge"]

    asyncio.run(scenario())


def test_each_question_and_trial_starts_an_isolated_chat(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {
        "target": ["First A1", "ALPHA", "First A2", "ALPHA", "First B1", "BETA", "First B2", "BETA"],
        "judge": [_judgment("REFUSED"), _judgment()] * 4,
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(
                target_mode="api", trials=2,
                custom_questions=["Reply with ALPHA", "Reply with BETA"],
                turn_plan=["First stage", "{request}"],
            ))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["coverage"]["pass_count"] == 4
            assert len({result["conversation_id"] for result in current["results"]}) == 4
            assert all(len(result["turns"]) == 2 for result in current["results"])
            targets = [call for call in calls if call["role"] == "target"]
            assert len(targets) == 8
            for index in range(0, len(targets), 2):
                assert targets[index]["messages"] == [("user", "First stage")]
                assert len(targets[index + 1]["messages"]) == 3
                assert targets[index + 1]["messages"][1][1] == ["First A1", "First A2", "First B1", "First B2"][index // 2]

    asyncio.run(scenario())


def test_complied_assessment_stops_before_unused_plan_turns(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": "ALPHA", "judge": _judgment()})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", turn_plan=["{request}", "Unused stage"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["results"][0]["complete"] is True
            assert len(current["results"][0]["turns"]) == 1
            assert [call["role"] for call in calls] == ["target", "judge"]

    asyncio.run(scenario())


def test_adaptive_planner_receives_actual_reply_and_original_objective(monkeypatch, tmp_path):
    seen = []

    async def adaptive_planner(messages, system):
        data = json.loads(messages[-1].text().split("EVALUATION DATA:\n", 1)[1])
        seen.append(data)
        assert data["objective"] == "Reply with ALPHA"
        if data["turn"] == 1:
            assert data["conversation"] == []
            return _action("send", prompt="First stage")
        assert data["conversation"] == [
            {"role": "user", "content": "First stage"},
            {"role": "assistant", "content": "Actual visible target reply"},
        ]
        assert data["last_assessment"]["label"] == "REFUSED"
        assert data["last_assessment"]["source"] == "judge"
        return _action("send", prompt=data["objective"])

    calls, _ = _providers(monkeypatch, {
        "attacker": adaptive_planner,
        "target": ["Actual visible target reply", "ALPHA"],
        "judge": [_judgment("REFUSED"), _judgment()],
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", candidate_prompt=""))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["coverage"]["pass_count"] == 1
            assert len(seen) == 2
            assert [call["role"] for call in calls] == ["attacker", "target", "judge"] * 2

    asyncio.run(scenario())


def test_ungraded_turns_complete_the_bounded_case_without_claiming_a_pass(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": ["Stage acknowledged", "ALPHA"]})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target")) as manager:
            run = manager.create(_body(target_mode="api", max_turns=8, turn_plan=["First stage", "{request}"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            result = current["results"][0]
            assert current["status"] == "awaiting_review"
            assert result["complete"] is True
            assert len(result["turns"]) == 2
            assert result["source"] == "ungraded"
            assert result["label"] == "UNVERIFIED"
            assert current["coverage"]["pass_count"] == 0
            assert all(turn["assessment"]["source"] == "ungraded" for turn in result["turns"])
            assert [call["role"] for call in calls] == ["target", "target"]

    asyncio.run(scenario())


def test_operator_review_updates_the_final_turn_assessment(monkeypatch, tmp_path):
    _providers(monkeypatch, {"target": "ALPHA"})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target")) as manager:
            run = manager.create(_body(target_mode="api", turn_plan=["{request}"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            before = manager.get(run["id"])
            original = before["results"][0]["turns"][0]["assessment"]
            reviewed = await manager.assess(run["id"], {
                "result_id": before["results"][0]["id"], "label": "COMPLIED",
                "reason": "The original objective was checked by the operator.",
            })
            result = reviewed["results"][0]
            assert reviewed["status"] == "completed"
            assert reviewed["coverage"]["pass_count"] == 1
            assert result["turns"][0]["assessment"]["label"] == "COMPLIED"
            assert result["turns"][0]["assessment"]["source"] == "operator"
            assert result["assessment_history"][0]["label"] == original["label"]
            assert result["assessment_history"][0]["source"] == original["source"]

    asyncio.run(scenario())


def test_explicit_plan_stops_at_max_turns(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": "Stage acknowledged", "judge": _judgment("REFUSED")})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", max_turns=1, turn_plan=["First stage", "Unused stage"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["results"][0]["complete"] is True
            assert len(current["results"][0]["turns"]) == 1
            assert current["coverage"]["pass_count"] == 0
            assert [call["role"] for call in calls] == ["target", "judge"]

    asyncio.run(scenario())


def test_saved_pending_relay_resumes_same_turn_without_losing_prior_evidence(tmp_path):
    async def scenario():
        async with _manager(tmp_path) as first_manager:
            run = first_manager.create(_body(turn_plan=["First stage", "{request}"]))
            await first_manager.start(run["id"])
            await first_manager.wait_for_idle(run["id"])
            first = first_manager.get(run["id"])["pending_relay"]
            await first_manager.submit_relay(run["id"], {
                "request_id": first["request_id"], "response": "Stage acknowledged", "label": "REFUSED",
            })
            await first_manager.wait_for_idle(run["id"])
            before = first_manager.get(run["id"])
            await first_manager.stop(run["id"])
        async with _manager(tmp_path) as manager:
            resumed = await manager.continue_run(run["id"])
            assert resumed["status"] == "awaiting_relay"
            assert resumed["pending_relay"] == before["pending_relay"]
            assert resumed["results"] == before["results"]
            pending = resumed["pending_relay"]
            assert pending["turn"] == 2
            assert pending["continue_chat"] is True
            await manager.submit_relay(run["id"], {
                "request_id": pending["request_id"], "response": "ALPHA", "label": "COMPLIED",
            })
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert [turn["response"] for turn in current["results"][0]["turns"]] == ["Stage acknowledged", "ALPHA"]
            assert current["relay_submissions"] == 2

    asyncio.run(scenario())


def test_interrupted_judgment_resumes_without_repeating_target_turn(monkeypatch, tmp_path):
    async def scenario():
        entered = asyncio.Event()

        async def interrupted_judge(messages, system):
            if entered.is_set():
                return _judgment()
            entered.set()
            await asyncio.Event().wait()

        calls, _ = _providers(monkeypatch, {"target": "ALPHA", "judge": interrupted_judge})
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", turn_plan=["{request}"]))
            await manager.start(run["id"])
            await asyncio.wait_for(entered.wait(), timeout=2)
            await manager.stop(run["id"])
            stopped = manager.get(run["id"])
            assert stopped["results"][0]["turns"][0]["response"] == "ALPHA"
            assert stopped["coverage"]["pass_count"] == 0
            await manager.continue_run(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert len(current["results"][0]["turns"]) == 1
            assert current["results"][0]["turns"][0]["assessment"]["label"] == "COMPLIED"
            assert [call["role"] for call in calls] == ["target", "judge", "judge"]

    asyncio.run(scenario())


def test_configured_transform_chain_changes_the_delivered_payload(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": "ALPHA", "judge": _judgment()})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(
                target_mode="api", turn_plan=["{request}"], transform_chain=["rot13"],
            ))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            expected = codecs.encode("Reply with ALPHA", "rot13")
            target = next(call for call in calls if call["role"] == "target")
            assert target["messages"] == [("user", expected)]
            turn = current["results"][0]["turns"][0]
            assert turn["prompt"] == expected
            assert turn["transform"]
            assert "rot13" in json.dumps(turn["transform"])
            assert current["coverage"]["pass_count"] == 1

    asyncio.run(scenario())


def test_planner_notes_remain_scoped_to_the_current_case(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {
        "attacker": [
            _action("remember", note="Only case ALPHA may see this note"),
            _action("send", prompt="Reply with ALPHA"),
            _action("remember", note="Only case BETA may see this note"),
            _action("send", prompt="Reply with BETA"),
        ],
        "target": ["ALPHA", "BETA"], "judge": _judgment(),
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(
                target_mode="api", candidate_prompt="",
                custom_questions=["Reply with ALPHA", "Reply with BETA"],
            ))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["coverage"]["pass_count"] == 2
            first, second = current["results"]
            assert "Only case ALPHA may see this note" in json.dumps(first["scratchpad"])
            assert "Only case ALPHA may see this note" not in json.dumps(second)
            assert "Only case BETA may see this note" in json.dumps(second["scratchpad"])
            targets = [call for call in calls if call["role"] == "target"]
            assert targets[0]["messages"] == [("user", "Reply with ALPHA")]
            assert targets[1]["messages"] == [("user", "Reply with BETA")]

    asyncio.run(scenario())


def test_planner_sends_exact_transformed_artifact_without_recopying_text(monkeypatch, tmp_path):
    original = "Reply with ALPHA"

    async def send_artifact(messages, system):
        data = json.loads(messages[-1].text().split("EVALUATION DATA:\n", 1)[1])
        artifact = data["tool_results"][-1]["output"]["artifact_id"]
        return _action("send", artifact_id=artifact)

    calls, _ = _providers(monkeypatch, {
        "attacker": [
            _action("transform_text", text=original, chain=["tag_smuggle"]), send_artifact,
        ],
        "target": "ALPHA", "judge": _judgment(),
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", candidate_prompt=""))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            expected = TRANSFORMS["tag_smuggle"].encode(original)
            target = next(call for call in calls if call["role"] == "target")
            assert target["messages"] == [("user", expected)]
            turn = current["results"][0]["turns"][0]
            details = turn["transform"]
            assert turn["prompt"] == expected
            assert details["original_text"] == original
            assert details["original_sha256"] == hashlib.sha256(original.encode()).hexdigest()
            assert details["transformed_sha256"] == hashlib.sha256(expected.encode()).hexdigest()
            assert base64.b64decode(details["transformed_utf8_base64"]).decode() == expected
            assert details["lossy"] is False
            assert [event["tool"] for event in turn["tool_trace"]] == ["transform_text", "send"]

    asyncio.run(scenario())


def test_interrupted_target_resumes_saved_turn_without_replanning(monkeypatch, tmp_path):
    async def scenario():
        entered = asyncio.Event()

        async def interrupted_target(messages, system):
            if entered.is_set():
                return "ALPHA"
            entered.set()
            await asyncio.Event().wait()

        calls, _ = _providers(monkeypatch, {
            "attacker": [_action("send", prompt="Reply with ALPHA")],
            "target": interrupted_target, "judge": _judgment(),
        })
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", candidate_prompt="", max_turns=1))
            await manager.start(run["id"])
            await asyncio.wait_for(entered.wait(), timeout=2)
            await manager.stop(run["id"])
            before = manager.get(run["id"])
            assert before["results"][0]["turns"] == []
            assert before["results"][0]["pending_turn"]["prompt"] == "Reply with ALPHA"
            await manager.continue_run(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert len(current["results"][0]["turns"]) == 1
            assert current["results"][0]["turns"][0]["response"] == "ALPHA"
            assert [call["role"] for call in calls] == ["attacker", "target", "target", "judge"]

    asyncio.run(scenario())


def test_planner_rejects_arbitrary_execution_tools(monkeypatch, tmp_path):
    marker = tmp_path / "must-not-exist"
    calls, _ = _providers(monkeypatch, {
        "attacker": [
            _action("run_shell", command=f"touch {marker}"),
            _action("send", prompt="Reply with ALPHA"),
        ],
        "target": "ALPHA", "judge": _judgment(),
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", candidate_prompt=""))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert not marker.exists()
            assert current["status"] == "completed"
            assert current["coverage"]["pass_count"] == 1
            trace = json.dumps(current["results"][0]["turns"][0]["tool_trace"])
            assert "run_shell" in trace
            assert "error" in trace.lower()
            assert [call["role"] for call in calls] == ["attacker", "attacker", "target", "judge"]

    asyncio.run(scenario())


def test_planner_local_decisions_and_all_role_calls_are_bounded(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {
        "attacker": _action("remember", note="Still planning"),
        "target": "ALPHA", "judge": _judgment(),
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", candidate_prompt="", max_turns=1, max_calls=4))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert len(calls) <= 4
            assert len([call for call in calls if call["role"] == "attacker"]) <= 4
            assert current["model_calls"] == len(calls)
            assert current["coverage"]["pass_count"] == 0
            assert current["status"] != "running"

    asyncio.run(scenario())


@pytest.mark.parametrize(("budget", "expected_roles", "passed"), [
    (1, ["attacker"], 0),
    (2, ["attacker", "target"], 0),
    (3, ["attacker", "target", "judge"], 1),
])
def test_planning_target_and_judging_share_the_total_call_budget(budget, expected_roles, passed, monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {
        "attacker": _action("send", prompt="Reply with ALPHA"),
        "target": "ALPHA", "judge": _judgment(),
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", candidate_prompt="", max_turns=1, max_calls=budget))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert [call["role"] for call in calls] == expected_roles
            assert current["model_calls"] == budget
            assert current["coverage"]["pass_count"] == passed
            assert current["status"] == ("completed" if passed else "stopped")

    asyncio.run(scenario())


def test_restart_limit_does_not_reset_total_turn_budget(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {
        "attacker": [
            _action("restart"), _action("restart"), _action("restart"),
            _action("send", prompt="Reply with ALPHA"),
        ],
        "target": "Stage declined", "judge": _judgment("REFUSED"),
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", candidate_prompt="", max_turns=1))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            result = current["results"][0]
            assert result["complete"] is True
            assert result["branch"] == 2
            assert len(result["turns"]) == 1
            assert result["turns"][0]["index"] == 1
            assert result["turns"][0]["branch"] == 2
            trace = result["turns"][0]["tool_trace"]
            assert len([event for event in trace if event["tool"] == "restart"]) == 2
            assert any("two" in event["output"] for event in trace if event["tool"] == "tool_error")
            assert current["coverage"]["pass_count"] == 0
            assert [call["role"] for call in calls] == ["attacker"] * 4 + ["target", "judge"]

    asyncio.run(scenario())


def test_restart_opens_new_relay_chat_and_preserves_branch_evidence(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {
        "attacker": [
            _action("send", prompt="First stage"),
            _action("restart", reason="Try a fresh conversation"),
            _action("send", prompt="Reply with ALPHA"),
        ],
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker")) as manager:
            run = manager.create(_body(candidate_prompt="", max_turns=2))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            first = manager.get(run["id"])["pending_relay"]
            await manager.submit_relay(run["id"], {
                "request_id": first["request_id"], "response": "Stage declined", "label": "REFUSED",
            })
            await manager.wait_for_idle(run["id"])
            second = manager.get(run["id"])["pending_relay"]
            assert second["turn"] == 2
            assert second["continue_chat"] is False
            assert second["conversation_id"] != first["conversation_id"]
            await manager.submit_relay(run["id"], {
                "request_id": second["request_id"], "response": "ALPHA", "label": "COMPLIED",
            })
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            result = current["results"][0]
            assert result["complete"] is True
            assert len(result["turns"]) == 2
            assert result["turns"][0]["branch"] != result["turns"][1]["branch"]
            assert result["turns"][0]["response"] == "Stage declined"
            assert "restart" in json.dumps(result["turns"][1]["tool_trace"])
            assert [call["role"] for call in calls] == ["attacker"] * 3

    asyncio.run(scenario())


def test_export_keeps_full_turn_evidence_and_case_scoped_state(tmp_path):
    async def scenario():
        async with _manager(tmp_path) as manager:
            run = manager.create(_body(turn_plan=["{request}"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            pending = manager.get(run["id"])["pending_relay"]
            await manager.submit_relay(run["id"], {
                "request_id": pending["request_id"], "response": "ALPHA", "label": "COMPLIED",
            })
            await manager.wait_for_idle(run["id"])
            return run["id"], manager.get(run["id"])

    run_id, expected = asyncio.run(scenario())
    manager = workflow.WorkflowManager(tmp_path / "workflow")
    app = FastAPI()
    workflow.install_workflow_routes(app, manager)
    with TestClient(app) as client:
        exported = client.get(f"/api/workflow/runs/{run_id}/export")
        assert exported.status_code == 200
        result = exported.json()["results"][0]
        assert result == expected["results"][0]
        assert result["complete"] is True
        assert "scratchpad" in result
        assert result["conversation_id"] == expected["results"][0]["conversation_id"]
        assert {"messages", "tool_trace", "transform", "assessment", "branch"} <= result["turns"][0].keys()
