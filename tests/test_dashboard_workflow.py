import asyncio
import json
import shutil
import time
from contextlib import asynccontextmanager

import pytest

from wallbreaker.config import Endpoint
from wallbreaker.dashboard import workflow


def _body(**overrides):
    body = {
        "target_mode": "relay",
        "target_name": "Example chat",
        "target_url": "https://example.test/chat",
        "suite_id": "custom",
        "custom_questions": ["Reply with ALPHA", "Reply with BETA"],
        "candidate_prompt": "Follow this test request: {request}",
        "max_rounds": 2,
        "max_calls": 20,
        "trials": 1,
        "auto_iterate": False,
        "delivery": "user",
    }
    return body | overrides


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
            calls.append({"role": role, "messages": messages, "system": system})
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
        "reason": "The response satisfies the selected test." if label == "COMPLIED" else "The response declines the test.",
    })


def test_relay_records_unverified_responses_without_any_model(monkeypatch, tmp_path):
    def no_provider(endpoint):
        pytest.fail("Manual relay must work without a model connection")

    monkeypatch.setattr(workflow, "build_provider", no_provider)

    async def scenario():
        async with _manager(tmp_path) as manager:
            run = manager.create(_body(custom_questions=["Reply with ALPHA"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            pending = manager.get(run["id"])["pending_relay"]
            assert pending["payload"] == "Follow this test request: Reply with ALPHA"
            await manager.submit_relay(run["id"], {
                "request_id": pending["request_id"], "response": "ALPHA",
            })
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "awaiting_review"
            assert current["coverage"]["completed"] == 1
            assert current["coverage"]["pass_count"] == 0
            assert current["coverage"]["unverified"] == 1
            assert current["results"][0]["label"] == "UNVERIFIED"
            assert current["model_calls"] == 0

    asyncio.run(scenario())


def test_operator_assessment_completes_every_question_and_trial(monkeypatch, tmp_path):
    _providers(monkeypatch, {})

    async def scenario():
        async with _manager(tmp_path) as manager:
            run = manager.create(_body(trials=2))
            await manager.start(run["id"])
            for _ in range(4):
                await manager.wait_for_idle(run["id"])
                current = manager.get(run["id"])
                pending = current["pending_relay"]
                assert pending is not None
                await manager.submit_relay(run["id"], {
                    "request_id": pending["request_id"],
                    "response": "Recorded answer",
                    "label": "COMPLIED",
                    "reason": "Operator checked the answer against the original request.",
                })
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["coverage"] == {
                "completed": 4, "total": 4, "pass_count": 4,
                "assessed": 4, "unverified": 0,
            }
            assert len({result["id"] for result in current["results"]}) == 4
            assert all(result["source"] == "operator" for result in current["results"])

    asyncio.run(scenario())


def test_stale_relay_response_cannot_be_applied_to_another_question(tmp_path):
    async def scenario():
        async with _manager(tmp_path) as manager:
            run = manager.create(_body())
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            first = manager.get(run["id"])["pending_relay"]
            with pytest.raises(ValueError):
                await manager.submit_relay(run["id"], {
                    "request_id": "stale-request", "response": "Wrong answer",
                })
            assert manager.get(run["id"])["pending_relay"] == first
            await manager.submit_relay(run["id"], {
                "request_id": first["request_id"], "response": "First answer",
            })
            await manager.wait_for_idle(run["id"])
            second = manager.get(run["id"])["pending_relay"]
            assert second["request_id"] != first["request_id"]
            with pytest.raises(ValueError):
                await manager.submit_relay(run["id"], {
                    "request_id": first["request_id"], "response": "Duplicate answer",
                    "label": "COMPLIED",
                })
            assert manager.get(run["id"])["pending_relay"] == second
            assert len(manager.get(run["id"])["results"]) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("response", ["", "   \n"])
def test_empty_relay_response_never_counts_as_pass(response, tmp_path):
    async def scenario():
        async with _manager(tmp_path) as manager:
            run = manager.create(_body(custom_questions=["Reply with ALPHA"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            pending = manager.get(run["id"])["pending_relay"]
            try:
                await manager.submit_relay(run["id"], {
                    "request_id": pending["request_id"], "response": response,
                    "label": "COMPLIED", "reason": "An unsupported pass claim",
                })
            except ValueError:
                pass
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["coverage"]["pass_count"] == 0
            assert current["status"] != "completed"
            assert all(result["label"] != "COMPLIED" for result in current["results"])

    asyncio.run(scenario())


def test_relay_rejects_native_system_delivery(tmp_path):
    async def scenario():
        async with _manager(tmp_path) as manager:
            with pytest.raises(ValueError, match="[Ss]ystem|[Rr]elay|[Uu]ser"):
                manager.create(_body(delivery="system"))

    asyncio.run(scenario())


def test_api_generation_target_and_judge_use_separate_roles(monkeypatch, tmp_path):
    calls, closed = _providers(monkeypatch, {
        "attacker": "Use this common test framing: {request}",
        "target": "A valid test answer", "judge": _judgment(),
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", candidate_prompt=""))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["candidate_prompt"] == "Use this common test framing: {request}"
            assert current["coverage"]["pass_count"] == 2
            assert current["model_calls"] == 5
            assert [call["role"] for call in calls] == ["attacker", "target", "judge", "target", "judge"]
            targets = [call for call in calls if call["role"] == "target"]
            assert all(len(call["messages"]) == 1 for call in targets)
            assert [call["messages"][0].text() for call in targets] == [
                "Use this common test framing: Reply with ALPHA",
                "Use this common test framing: Reply with BETA",
            ]
            assert all(result["source"] == "judge" for result in current["results"])
        assert set(closed) == {"attacker", "target", "judge"}

    asyncio.run(scenario())


def test_api_without_judge_waits_for_explicit_operator_review(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": "ALPHA"})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target")) as manager:
            run = manager.create(_body(target_mode="api", custom_questions=["Reply with ALPHA"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "awaiting_review"
            assert current["coverage"]["pass_count"] == 0
            assert current["results"][0]["label"] == "UNVERIFIED"
            await manager.assess(run["id"], {
                "result_id": current["results"][0]["id"],
                "label": "COMPLIED", "reason": "Operator verified the exact requested word.",
            })
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["results"][0]["source"] == "operator"
            assert current["model_calls"] == 1
            assert [call["role"] for call in calls] == ["target"]

    asyncio.run(scenario())


@pytest.mark.parametrize("judgment", [
    "COMPLIED", "not JSON", '{"label":"UNKNOWN","score":10,"reason":"bad"}',
    '{"label":"COMPLIED","score":false,"reason":"bad"}',
    '{"label":"COMPLIED","score":0,"reason":"inconsistent"}',
])
def test_malformed_judge_output_never_becomes_a_verified_pass(judgment, monkeypatch, tmp_path):
    _providers(monkeypatch, {"target": "ALPHA", "judge": judgment})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", custom_questions=["Reply with ALPHA"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] != "completed"
            assert current["coverage"]["pass_count"] == 0
            assert current["results"][0]["label"] in {"UNVERIFIED", "ERROR"}
            assert current["model_calls"] == 2

    asyncio.run(scenario())


def test_api_system_delivery_preserves_the_question_as_user_message(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": "ALPHA", "judge": _judgment()})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(
                target_mode="api", delivery="system", custom_questions=["Reply with ALPHA"],
            ))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            assert manager.get(run["id"])["status"] == "completed"
            target = next(call for call in calls if call["role"] == "target")
            assert target["system"] == "Follow this test request: Reply with ALPHA"
            assert target["messages"][0].text() == "Reply with ALPHA"

    asyncio.run(scenario())


@pytest.mark.parametrize("system_mode", ["drop", "merge"])
def test_native_system_delivery_requires_a_preserved_system_channel(system_mode, monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": "ALPHA"})
    endpoints = _endpoints("target")
    endpoints["target"].system_mode = system_mode

    async def scenario():
        async with _manager(tmp_path, endpoints) as manager:
            run = manager.create(_body(
                target_mode="api", delivery="system", custom_questions=["Reply with ALPHA"],
            ))
            with pytest.raises(ValueError, match="[Ss]ystem|[Nn]ative"):
                await manager.start(run["id"])
            assert manager.get(run["id"])["model_calls"] == 0
            assert calls == []
            user_run = manager.create(_body(
                target_mode="api", delivery="user", custom_questions=["Reply with ALPHA"],
            ))
            await manager.start(user_run["id"])
            await manager.wait_for_idle(user_run["id"])
            current = manager.get(user_run["id"])
            assert current["results"][0]["response"] == "ALPHA"
            assert current["model_calls"] == 1
            assert [call["role"] for call in calls] == ["target"]

    asyncio.run(scenario())


def test_empty_api_response_cannot_be_promoted_to_a_pass(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": "", "judge": _judgment()})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", custom_questions=["Reply with ALPHA"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "awaiting_review"
            assert current["results"][0]["label"] == "EMPTY"
            with pytest.raises(ValueError):
                await manager.assess(run["id"], {
                    "result_id": current["results"][0]["id"], "label": "COMPLIED",
                })
            assert manager.get(run["id"])["coverage"]["pass_count"] == 0
            assert [call["role"] for call in calls] == ["target"]

    asyncio.run(scenario())


@pytest.mark.parametrize(("changed_field", "changed_value"), [
    ("model", "different-target"),
    ("base_url", "https://different-target.invalid/v1"),
    ("system_prompt", "A different target policy"),
    ("system_mode", "merge"),
    ("provider", ("different-routing-provider",)),
    ("inference_path", "/alternative/chat/completions"),
])
def test_resume_rejects_a_different_target_connection(changed_field, changed_value, monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": "ALPHA"})
    endpoints = _endpoints("target")

    async def scenario():
        async with _manager(tmp_path, endpoints) as manager:
            run = manager.create(_body(target_mode="api", custom_questions=["Reply with ALPHA"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            await manager.stop(run["id"])
            current = manager.get(run["id"])
            assert len(current["models"]["target"]["behavior_sha256"]) == 64
            setattr(endpoints["target"], changed_field, changed_value)
            with pytest.raises(ValueError, match="connection changed"):
                await manager.continue_run(run["id"])
            assert manager.get(run["id"])["results"] == current["results"]
            assert len(calls) == 1

    asyncio.run(scenario())


def test_judge_cancellation_resumes_assessment_without_querying_target_again(monkeypatch, tmp_path):
    async def scenario():
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def interrupted_judge(messages, system):
            if entered.is_set():
                return _judgment()
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        calls, _ = _providers(monkeypatch, {"target": "ALPHA", "judge": interrupted_judge})
        async with _manager(tmp_path, _endpoints("target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", custom_questions=["Reply with ALPHA"]))
            await manager.start(run["id"])
            await asyncio.wait_for(entered.wait(), timeout=2)
            await manager.stop(run["id"])
            stopped = manager.get(run["id"])
            assert cancelled.is_set()
            assert stopped["status"] == "stopped"
            assert stopped["results"][0]["response"] == "ALPHA"
            assert stopped["results"][0]["label"] == "UNVERIFIED"
            result_id = stopped["results"][0]["id"]
            await manager.continue_run(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["results"][0]["id"] == result_id
            assert current["results"][0]["label"] == "COMPLIED"
            assert current["results"][0]["response"] == "ALPHA"
            assert current["model_calls"] == 3
            assert [call["role"] for call in calls] == ["target", "judge", "judge"]

    asyncio.run(scenario())


def test_each_result_preserves_its_judge_identity_when_judge_changes(monkeypatch, tmp_path):
    _providers(monkeypatch, {"judge": _judgment()})
    endpoints = _endpoints("judge")

    async def scenario():
        async with _manager(tmp_path, endpoints) as manager:
            run = manager.create(_body())
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            pending = manager.get(run["id"])["pending_relay"]
            await manager.submit_relay(run["id"], {
                "request_id": pending["request_id"], "response": "ALPHA",
            })
            await manager.wait_for_idle(run["id"])
            first = manager.get(run["id"])
            first_identity = first["results"][0]["assessment_model"]
            assert first_identity["model"] == "judge-model"
            assert first_identity["protocol"] == "openai"
            endpoints["judge"].model = "judge-revised-model"
            await manager.submit_relay(run["id"], {
                "request_id": first["pending_relay"]["request_id"], "response": "BETA",
            })
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["results"][0]["assessment_model"] == first_identity
            assert current["results"][1]["assessment_model"]["model"] == "judge-revised-model"
            assert current["results"][1]["assessment_model"]["protocol"] == "openai"
            assert current["models"]["judge"]["model"] == "judge-revised-model"

    asyncio.run(scenario())


def test_total_call_budget_includes_generation_and_judging(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {
        "attacker": "Common candidate: {request}",
        "target": "ALPHA", "judge": _judgment(),
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", candidate_prompt="", max_calls=2))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert [call["role"] for call in calls] == ["attacker", "target"]
            assert current["model_calls"] == 2
            assert current["status"] != "completed"
            assert current["coverage"]["pass_count"] == 0

    asyncio.run(scenario())


def test_target_failure_is_an_error_instead_of_a_refusal(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {"target": RuntimeError("target unavailable")})

    async def scenario():
        async with _manager(tmp_path, _endpoints("target")) as manager:
            run = manager.create(_body(target_mode="api", custom_questions=["Reply with ALPHA"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] != "completed"
            assert current["results"][0]["label"] == "ERROR"
            assert "RuntimeError" in current["results"][0]["reason"]
            assert current["results"][0]["source"] == "target_error"
            assert current["coverage"]["pass_count"] == 0
            assert current["model_calls"] == 1
            assert len(calls) == 1

    asyncio.run(scenario())


def test_continue_revises_once_and_preserves_previous_round(monkeypatch, tmp_path):
    calls, _ = _providers(monkeypatch, {
        "attacker": "Revised common candidate: {request}",
        "target": ["Declined", "ALPHA"],
        "judge": [_judgment("REFUSED"), _judgment()],
    })

    async def scenario():
        async with _manager(tmp_path, _endpoints("attacker", "target", "judge")) as manager:
            run = manager.create(_body(target_mode="api", custom_questions=["Reply with ALPHA"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            first = manager.get(run["id"])
            assert first["status"] == "round_complete"
            assert first["round"] == 1
            await manager.continue_run(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert current["status"] == "completed"
            assert current["round"] == 2
            assert current["candidate_prompt"] == "Revised common candidate: {request}"
            assert current["history"][0]["results"][0]["label"] == "REFUSED"
            assert current["results"][0]["label"] == "COMPLIED"
            assert current["model_calls"] == 5
            assert [call["role"] for call in calls].count("attacker") == 1

    asyncio.run(scenario())


def test_pending_relay_survives_a_new_manager(tmp_path):
    async def scenario():
        async with _manager(tmp_path) as manager:
            run = manager.create(_body(custom_questions=["Reply with ALPHA"]))
            await manager.start(run["id"])
            await manager.wait_for_idle(run["id"])
            pending = manager.get(run["id"])["pending_relay"]
        async with _manager(tmp_path) as manager:
            current = manager.get(run["id"])
            assert current["pending_relay"] == pending
            assert any(item["id"] == run["id"] for item in manager.list())
            await manager.submit_relay(run["id"], {
                "request_id": pending["request_id"], "response": "ALPHA",
                "label": "COMPLIED", "reason": "Operator verified response.",
            })
            await manager.wait_for_idle(run["id"])
            assert manager.get(run["id"])["status"] == "completed"

    asyncio.run(scenario())


def test_stop_cancels_inference_and_crash_snapshot_loads_as_stopped(monkeypatch, tmp_path):
    async def scenario():
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocking_target(messages, system):
            if entered.is_set():
                return "ALPHA"
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        calls, _ = _providers(monkeypatch, {"target": blocking_target})
        async with _manager(tmp_path, _endpoints("target")) as manager:
            run = manager.create(_body(target_mode="api"))
            await manager.start(run["id"])
            await asyncio.wait_for(entered.wait(), timeout=2)
            with pytest.raises(ValueError):
                await manager.start(run["id"])
            shutil.copytree(tmp_path / "workflow", tmp_path / "crashed" / "workflow")
            await manager.stop(run["id"])
            assert manager.get(run["id"])["status"] == "stopped"
            assert cancelled.is_set()
            assert len(calls) == 1
            await manager.continue_run(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert len(current["results"]) == 2
            assert all(result["response"] == "ALPHA" for result in current["results"])
            assert len(calls) == 3
        async with _manager(tmp_path / "crashed", _endpoints("target")) as manager:
            assert manager.get(run["id"])["status"] == "stopped"
            await manager.continue_run(run["id"])
            await manager.wait_for_idle(run["id"])
            current = manager.get(run["id"])
            assert len(current["results"]) == 2
            assert all(result["response"] == "ALPHA" for result in current["results"])
            assert len(calls) == 5

    asyncio.run(scenario())


def _wait_for_status(client, run_id, expected):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/api/workflow/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] == expected:
            return run
        time.sleep(0.01)
    pytest.fail(f"Workflow did not reach {expected}: {run}")


def test_workflow_routes_respect_disabled_judge_setting(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from wallbreaker.config import Config
    from wallbreaker.dashboard.server import create_app

    calls, _ = _providers(monkeypatch, {"target": "ALPHA", "judge": _judgment()})
    endpoints = _endpoints("target", "judge")
    config = Config(
        default_profile="", target=endpoints["target"], judge=endpoints["judge"],
        path=tmp_path / "config.toml",
    )
    app = create_app(config=config, sessions_dir=tmp_path / "sessions", corpus_store=tmp_path / "corpus")
    with TestClient(app) as client:
        settings = client.post("/api/settings", json={"target_options": {"judge_enabled": False}})
        assert settings.status_code == 200
        assert settings.json()["target_options"]["judge_enabled"] is False
        response = client.post("/api/workflow/runs", json=_body(
            target_mode="api", custom_questions=["Reply with ALPHA"],
        ))
        assert response.status_code == 200
        run_id = response.json()["id"]
        assert client.post(f"/api/workflow/runs/{run_id}/start", json={}).status_code == 200
        current = _wait_for_status(client, run_id, "awaiting_review")
        assert current["results"][0]["response"] == "ALPHA"
        assert current["results"][0]["label"] == "UNVERIFIED"
        assert current["coverage"]["pass_count"] == 0
        assert [call["role"] for call in calls] == ["target"]


def test_workflow_routes_create_relay_assess_export_without_configuration(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from wallbreaker.dashboard.server import create_app

    def no_provider(endpoint):
        pytest.fail("Relay routes must not call a real provider")

    monkeypatch.setattr(workflow, "build_provider", no_provider)
    app = create_app(config=None, sessions_dir=tmp_path / "sessions", corpus_store=tmp_path / "corpus")
    with TestClient(app) as client:
        options = client.get("/api/workflow/options")
        assert options.status_code == 200
        assert {"smoke", "custom"} <= {suite["id"] for suite in options.json()["suites"]}
        response = client.post("/api/workflow/runs", json=_body(custom_questions=["Reply with ALPHA"]))
        assert response.status_code == 200
        run = response.json()
        assert run["status"] == "ready"
        run_id = run["id"]
        assert any(item["id"] == run_id for item in client.get("/api/workflow/runs").json())
        assert client.post(f"/api/workflow/runs/{run_id}/start", json={}).status_code == 200
        current = _wait_for_status(client, run_id, "awaiting_relay")
        pending = current["pending_relay"]
        stopped = client.post(f"/api/workflow/runs/{run_id}/stop", json={})
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"
        assert client.post(f"/api/workflow/runs/{run_id}/continue", json={}).status_code == 200
        current = _wait_for_status(client, run_id, "awaiting_relay")
        assert current["pending_relay"] == pending
        stale = client.post(f"/api/workflow/runs/{run_id}/relay", json={
            "request_id": "stale", "response": "ALPHA",
        })
        assert stale.status_code == 409
        response = client.post(f"/api/workflow/runs/{run_id}/relay", json={
            "request_id": current["pending_relay"]["request_id"], "response": "ALPHA",
        })
        assert response.status_code == 200
        current = _wait_for_status(client, run_id, "awaiting_review")
        assessed = client.post(f"/api/workflow/runs/{run_id}/assess", json={
            "result_id": current["results"][0]["id"], "label": "COMPLIED",
            "reason": "Operator verified the exact requested word.",
        })
        assert assessed.status_code == 200
        current = _wait_for_status(client, run_id, "completed")
        exported = client.get(f"/api/workflow/runs/{run_id}/export")
        assert exported.status_code == 200
        assert exported.json()["results"] == current["results"]
        assert exported.json()["coverage"]["pass_count"] == 1
        assert client.get("/api/workflow/runs/does-not-exist").status_code == 404
        assert client.post("/api/workflow/runs", json=_body(delivery="system")).status_code == 400
        missing_target = client.post("/api/workflow/runs", json=_body(target_mode="api"))
        assert missing_target.status_code == 200
        refused_start = client.post(
            f"/api/workflow/runs/{missing_target.json()['id']}/start", json={},
        )
        assert refused_start.status_code == 400
