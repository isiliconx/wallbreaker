import json
import re
from urllib.parse import urlparse

import pytest

from wallbreaker.dashboard.workflow_methods import list_attacker_tools, list_methods


def test_method_ids_are_unique_and_stable():
    first = list_methods()
    assert first == list_methods()
    ids = [method["id"] for method in first]
    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "single-prompt", "adaptive-dialogue", "context-retention", "text-obfuscation",
        "persistent-memory", "agent-tool-injection", "weight-updating", "strategy-aware-search",
    }
    assert json.loads(json.dumps(first)) == first


@pytest.mark.parametrize("method", list_methods(), ids=lambda method: method["id"])
def test_methods_have_primary_sources_and_explicit_limits(method):
    assert set(method) == {"id", "name", "description", "mode", "status", "sources", "limitations"}
    assert method["name"].strip()
    assert method["description"].strip()
    assert method["limitations"].strip()
    assert method["mode"] in {"single", "adaptive", "context"}
    assert method["status"] in {"available", "research"}
    assert method["sources"]
    for source in method["sources"]:
        assert set(source) == {"title", "url", "date"}
        assert source["title"].strip()
        parsed = urlparse(source["url"])
        assert parsed.scheme == "https"
        assert parsed.netloc in {"arxiv.org", "proceedings.mlr.press", "aclanthology.org"}
        assert re.fullmatch(r"20\d{2}-\d{2}(?:-\d{2})?", source["date"])


def test_available_modes_do_not_imply_published_attack_reproduction():
    available = {method["id"]: method for method in list_methods() if method["status"] == "available"}
    assert {key: method["mode"] for key, method in available.items()} == {
        "single-prompt": "single",
        "adaptive-dialogue": "adaptive",
        "context-retention": "context",
        "text-obfuscation": "single",
    }
    assert "not a faithful reproduction" in available["adaptive-dialogue"]["limitations"]
    assert "Same-session context only" in available["context-retention"]["limitations"]
    assert "do not provide tokenizer-ID control" in available["text-obfuscation"]["limitations"]


@pytest.mark.parametrize("method_id", [
    "persistent-memory", "agent-tool-injection", "weight-updating", "strategy-aware-search",
])
def test_environment_and_training_research_is_not_advertised_as_available(method_id):
    method = next(method for method in list_methods() if method["id"] == method_id)
    assert method["status"] == "research"
    assert method["description"].startswith("Research direction:")


def test_method_metadata_is_independent_between_calls_and_entries():
    methods = list_methods()
    adaptive = next(method for method in methods if method["id"] == "adaptive-dialogue")
    context = next(method for method in methods if method["id"] == "context-retention")
    adaptive["sources"][0]["title"] = "changed"
    assert context["sources"][0]["title"] != "changed"
    assert list_methods()[1]["sources"][0]["title"] != "changed"
    methods[0]["sources"].clear()
    assert list_methods()[0]["sources"]


def test_attacker_tools_have_stable_unique_case_scoped_ids():
    tools = list_attacker_tools()
    assert tools == list_attacker_tools()
    ids = [tool["id"] for tool in tools]
    assert ids == [
        "search_library", "read_reference", "read_method", "transform_text", "read_observations",
        "remember", "send", "restart", "finish",
    ]
    assert len(ids) == len(set(ids))
    assert all(set(tool) == {"id", "name", "description"} for tool in tools)
    assert all(tool["name"].strip() and tool["description"].strip() for tool in tools)
    assert json.loads(json.dumps(tools)) == tools


def test_tool_catalog_distinguishes_case_notes_from_target_memory():
    tools = {tool["id"]: tool for tool in list_attacker_tools()}
    assert "does not modify the target's persistent memory" in tools["remember"]["description"]
    assert "visible target replies" in tools["read_observations"]["description"]
    assert "no hidden target-state access" in tools["read_observations"]["description"]
    assert "no web search or arbitrary filesystem access" in tools["search_library"]["description"]
    assert "configured target API or human relay" in tools["send"]["description"]
    assert "artifact_id" in tools["send"]["description"]
    assert "untrusted reference data" in tools["read_reference"]["description"]
    assert "never fetch arbitrary source URLs" in tools["read_method"]["description"]
    assert "two restarts per case" in tools["restart"]["description"]
    assert "eight total target turns" in tools["restart"]["description"]


def test_tool_metadata_cannot_mutate_future_catalog_calls():
    tools = list_attacker_tools()
    tools[0]["description"] = "changed"
    tools.clear()
    assert len(list_attacker_tools()) == 9
    assert list_attacker_tools()[0]["description"] != "changed"
