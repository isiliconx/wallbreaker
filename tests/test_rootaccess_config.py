import pytest

from rootaccess.cli import main
from rootaccess.config import expand_environment, load_campaign, provider_for
from rootaccess.providers import IpeenkProv, OpenAICompat


def test_recursive_environment_expansion(monkeypatch):
    monkeypatch.setenv("ROOTACCESS_TEST_MODEL", "company/model")
    assert expand_environment({"target": {"model": "${ROOTACCESS_TEST_MODEL}"}}) == {
        "target": {"model": "company/model"}}
    with pytest.raises(ValueError, match="Missing environment variable"):
        expand_environment("${ROOTACCESS_MISSING_TEST_VARIABLE}")


def test_campaign_resolves_bundled_files_from_other_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WB_TARGET_MODEL", "local-model")
    cfg, base = load_campaign("examples/local-smoke.yaml")
    assert cfg["target"]["model"] == "local-model"
    assert base.name == "examples"


def test_campaign_selects_specialized_ipeenk_provider(monkeypatch):
    provider = provider_for("target", {"base_url": "https://ai.ipeenk.com/v1", "model": "test", "api_key": "dummy"})
    assert isinstance(provider, IpeenkProv) and provider.api_key == "dummy"


def test_workbench_commands_are_forwarded(monkeypatch):
    import wallbreaker.cli
    seen = []
    monkeypatch.setattr(wallbreaker.cli, "main", lambda args: seen.append(args) or 0)
    assert main(["dashboard", "--port", "9988"]) == 0
    assert main(["workbench", "--help"]) == 0
    assert seen == [["dashboard", "--port", "9988"], ["--help"]]


def test_provider_errors_are_exceptions_without_private_details(monkeypatch):
    import urllib.request
    from rootaccess.providers import ProviderError
    def fail(*args, **kwargs):
        raise OSError("private credential")
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(ProviderError, match="OSError") as error:
        OpenAICompat("http://localhost:1234/v1", "dummy", "test").complete([])
    assert "private credential" not in str(error.value)


def test_reasoning_is_not_misrepresented_as_final_answer():
    assert OpenAICompat._text_from_chat({"choices": [{"message": {
        "content": "", "reasoning_content": "internal draft"}}]}) == ""


def test_anthropic_uses_retained_adapter_and_closes(monkeypatch):
    from wallbreaker.providers import factory
    seen = {}
    class Fake:
        async def complete(self, messages, **kwargs):
            seen["message"] = messages[0].text()
            return "online"
        async def aclose(self):
            seen["closed"] = True
    def build(endpoint, **kwargs):
        seen["endpoint"] = endpoint
        return Fake()
    monkeypatch.setattr(factory, "build_provider", build)
    provider = OpenAICompat("https://api.anthropic.com", "dummy", "test-model", protocol="anthropic")
    assert provider.complete([{"role": "user", "content": "hello"}]) == "online"
    assert seen["endpoint"].protocol == "anthropic"
    assert seen["message"] == "hello" and seen["closed"] is True


def test_campaign_cli_returns_failure_status_for_target_errors(monkeypatch, tmp_path):
    import rootaccess.config
    class Broken:
        model = "offline-test"
        def complete(self, *args, **kwargs):
            raise OSError("offline")
    monkeypatch.setattr(rootaccess.config, "provider_for", lambda *a, **k: Broken())
    monkeypatch.chdir(tmp_path)
    assert main(["run", "batteries/bare.md", "1", "ladders/smoke-ladder.txt", "--sleep", "0"]) == 2
