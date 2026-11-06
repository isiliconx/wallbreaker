import json
from pathlib import Path
import stat
import zipfile

import pytest

from rootaccess import corpus


def archive(tmp_path, files):
    path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(path, "w") as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return path


def test_import_preserves_text_and_separates_claims(tmp_path):
    text = "  Keep this exact.\r\nSecond line.\n"
    path = archive(tmp_path, {
        "prompts\\one.md": text,
        "manifest.json": json.dumps({"files": [{"path": "prompts/one.md", "name": "One",
             "claimed_models": ["company/model-v1"], "verified": True}]}),
        "run.py": "raise RuntimeError('must never run')",
    })
    store = tmp_path / "store"
    result = corpus.import_zip(path, store)
    row, = corpus.list_records(store, include_bundled=False)
    assert row["text"] == text
    assert row["claimed_models"] == ["company/model-v1"]
    assert row["verification"] == "unverified"
    assert row["observations"] == []
    assert row["submitted_metadata"][0]["verified"] is True
    assert row["sources"][0]["archive_sha256"] == result["archive_sha256"]
    assert result["skipped"] == ["run.py"]
    assert not (store / "run.py").exists()


def test_import_deduplicates_and_combines_provenance(tmp_path):
    store = tmp_path / "store"
    first = archive(tmp_path, {"one.md": "same", "two.txt": "same"})
    result = corpus.import_zip(first, store, ["model-a"])
    assert (result["imported"], result["duplicates"]) == (1, 1)
    second = archive(tmp_path, {"new-name.md": "same"})
    result = corpus.import_zip(second, store, ["model-b"])
    assert (result["imported"], result["duplicates"]) == (0, 1)
    row, = corpus.list_records(store, include_bundled=False)
    assert row["claimed_models"] == ["model-a", "model-b"]
    assert len(row["sources"]) == 3


@pytest.mark.parametrize("name", ["../escape.md", "/escape.md", "C:\\escape.md", "a\\..\\escape.md"])
def test_unsafe_paths_rejected_before_any_write(tmp_path, name):
    store = tmp_path / "store"
    with pytest.raises(corpus.ImportError, match="Unsafe"):
        corpus.import_zip(archive(tmp_path, {"valid.md": "valid", name: "invalid"}), store)
    assert not store.exists()


def test_symlink_rejected(tmp_path):
    path = tmp_path / "link.zip"
    info = zipfile.ZipInfo("link.md")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(info, "../../file")
    with pytest.raises(corpus.ImportError, match="symbolic link"):
        corpus.import_zip(path, tmp_path / "store")


def test_limits_reject_whole_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "MAX_FILE_BYTES", 5)
    path = archive(tmp_path, {"ok.md": "okay", "large.md": "sixsix"})
    with pytest.raises(corpus.ImportError, match="size limit"):
        corpus.import_zip(path, tmp_path / "store")
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("name, text", [
    ("invalid.yaml", "!!python/object/apply:os.system ['exit 1']"),
    ("invalid.json", '{"verified": true}'),
    ("invalid.md", b"\xff\xfe"),
])
def test_invalid_data_never_partially_imports(tmp_path, name, text):
    path = archive(tmp_path, {"good.md": "good", name: text})
    with pytest.raises(corpus.ImportError):
        corpus.import_zip(path, tmp_path / "store")
    assert not (tmp_path / "store").exists()


def test_structured_claims_and_jsonl(tmp_path):
    path = archive(tmp_path, {
        "one.json": json.dumps({"prompts": [{"prompt": "First", "model": "m1", "status": "verified"}]}),
        "two.jsonl": json.dumps({"text": "Second", "models": ["m2"]}) + "\n",
        "three.yaml": "prompt: Third\nclaimed_models: [m3]\n",
    })
    corpus.import_zip(path, tmp_path / "store")
    rows = corpus.list_records(tmp_path / "store", include_bundled=False)
    assert {r["text"] for r in rows} == {"First", "Second", "Third"}
    assert all(r["verification"] == "unverified" for r in rows)
    assert {m for r in rows for m in r["claimed_models"]} == {"m1", "m2", "m3"}


def test_bundled_prompts_keep_duplicate_aliases():
    rows = corpus.list_records(Path("/nonexistent-rootaccess-store"))
    dispatch, = [r for r in rows if r["name"] in {"dispatch", "dispatch-gamecheats"}]
    assert {s["member"] for s in dispatch["sources"]} == {"dispatch.md", "dispatch-gamecheats.md"}
    assert corpus.get_record("dispatch")["id"] == dispatch["id"]


def test_dashboard_import_and_browse_without_running(tmp_path):
    from fastapi.testclient import TestClient
    from wallbreaker.dashboard.server import create_app
    client = TestClient(create_app(sessions_dir=tmp_path / "sessions", corpus_store=tmp_path / "store"))
    path = archive(tmp_path, {"one.json": json.dumps({"prompt": "Test only", "models": ["m1"]})})
    response = client.post("/api/corpus/import?filename=submitted.zip", content=path.read_bytes(),
                           headers={"Content-Type": "application/zip"})
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 1
    rows = client.get("/api/corpus").json()
    row, = [r for r in rows if r["claimed_models"] == ["m1"]]
    assert row["verification"] == "unverified"
    assert client.get(f"/api/corpus/{row['id']}").json()["text"] == "Test only"
    assert client.get("/api/corpus/not-found").status_code == 404


def test_fire_file_resolves_full_corpus_prompt(tmp_path):
    from types import SimpleNamespace
    from wallbreaker.tools.fire_file import _read_source
    text = "x" * 75000
    corpus.import_zip(archive(tmp_path, {"long.md": text}), corpus.default_store(tmp_path))
    name, body = _read_source(SimpleNamespace(cwd=str(tmp_path)), "corpus:long")
    assert name == "long" and body == text


def test_recursive_yaml_and_duplicate_paths_rejected(tmp_path):
    path = archive(tmp_path, {"one.yaml": "prompt: Test\nmetadata: &loop [*loop]\n"})
    with pytest.raises(corpus.ImportError, match="nested or complex"):
        corpus.import_zip(path, tmp_path / "store")
    path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("one.md", "first")
        with pytest.warns(UserWarning):
            bundle.writestr("one.md", "second")
    with pytest.raises(corpus.ImportError, match="Duplicate archive path"):
        corpus.import_zip(path, tmp_path / "store")


def test_import_of_bundled_prompt_merges_claims_without_duplicate(tmp_path):
    bundled = corpus.get_record("bare")
    corpus.import_zip(archive(tmp_path, {"same.md": bundled["text"]}), tmp_path / "store", ["claimed-model"])
    matches = [r for r in corpus.list_records(tmp_path / "store") if r["id"] == bundled["id"]]
    assert len(matches) == 1
    assert matches[0]["claimed_models"] == ["claimed-model"]
    assert matches[0]["verification"] == "unverified"
