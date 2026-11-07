"""Import submitted prompts as data, retaining claims separately from observations."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile

import yaml

from .assets import asset_dir

MAX_MEMBERS = 2000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
TEXT_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml"}


class ImportError(ValueError):
    """Invalid or unsupported submission archive."""


def default_store(cwd: str | Path = ".") -> Path:
    return Path(cwd).resolve() / "corpus" / "submissions"


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".import-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _strings(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(dict.fromkeys(v for v in value if v.strip()))
    raise ImportError("Model claims and tags must be strings or lists of strings")


def _record(text: str, name: str, metadata: dict, source: dict) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ImportError("A submitted prompt must contain nonempty text")
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ImportError("A submitted prompt exceeds the size limit")
    claimed = []
    for key in ("claimed_models", "target_models", "models", "model"):
        claimed.extend(_strings(metadata.get(key)))
    return {
        "id": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "name": str(metadata.get("name", metadata.get("title", name))),
        "text": text,
        "claimed_models": list(dict.fromkeys(claimed)),
        "tags": _strings(metadata.get("tags", [])),
        "verification": "unverified",
        "observations": [],
        "sources": [source],
        "submitted_metadata": [{k: v for k, v in metadata.items() if k not in {"prompt", "text", "content"}}],
    }


def _parse_file(name: str, raw: bytes, metadata: dict, source: dict) -> list[dict]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportError(f"Submission is not UTF-8 text: {name}") from exc
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in {".md", ".txt"}:
        if not text.strip():
            return []
        return [_record(text, PurePosixPath(name).stem, metadata, source)]
    try:
        if suffix == ".jsonl":
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        elif suffix == ".json":
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except (ValueError, yaml.YAMLError, RecursionError) as exc:
        raise ImportError(f"Invalid structured submission: {name}") from exc
    _check_structure(data)
    if isinstance(data, dict) and "prompts" in data:
        data = data["prompts"]
    if not isinstance(data, list):
        data = [data]
    if len(data) > MAX_MEMBERS:
        raise ImportError("Too many prompts in a submission file")
    records = []
    for index, item in enumerate(data):
        if isinstance(item, str):
            item = {"prompt": item}
        if not isinstance(item, dict):
            raise ImportError(f"Expected prompt objects in {name}")
        body = item.get("prompt", item.get("text", item.get("content")))
        if not isinstance(body, str):
            raise ImportError(f"Expected a prompt/text/content string in {name}, record {index + 1}")
        records.append(_record(body, f"{PurePosixPath(name).stem}-{index + 1}",
                               {**metadata, **item}, {**source, "record": index + 1}))
    return records


def _check_structure(value, depth=0, budget=None):
    """Bound nested JSON/YAML and alias expansion before retaining arbitrary metadata."""
    budget = [10000] if budget is None else budget
    budget[0] -= 1
    if depth > 16 or budget[0] < 0:
        raise ImportError("Submission metadata is too deeply nested or complex")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ImportError("Submission metadata keys must be strings")
            _check_structure(item, depth + 1, budget)
    elif isinstance(value, list):
        for item in value:
            _check_structure(item, depth + 1, budget)
    elif not isinstance(value, (str, int, float, bool, type(None))):
        raise ImportError("Submission metadata must use JSON-compatible values")


def _member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts or ":" in path.parts[0] or "\x00" in name:
        raise ImportError(f"Unsafe archive member: {name!r}")
    return path


def import_zip(archive: str | Path, store: str | Path | None = None,
               claimed_models: list[str] | None = None) -> dict:
    """Validate the entire ZIP before saving content-addressed prompt records.

    Optional manifest.json: {"files": [{"path": "prompt.md", "name": "Example",
    "claimed_models": ["vendor/model"]}]}. Other text files can contain a prompt,
    a JSON/YAML prompt object, a list, or JSONL records. Never executes ZIP contents.
    """
    archive = Path(archive)
    store = Path(store) if store is not None else default_store()
    if archive.stat().st_size > MAX_TOTAL_BYTES:
        raise ImportError("Compressed archive exceeds the size limit")
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    records, skipped, skipped_reasons = [], [], []
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
                raise ImportError("Archive exceeds member or expanded-size limits")
            paths = {}
            for info in infos:
                path = _member_path(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ImportError(f"Archive contains a symbolic link: {path}")
                if info.flag_bits & 1:
                    raise ImportError("Encrypted archives are unsupported")
                if info.file_size > MAX_FILE_BYTES:
                    raise ImportError(f"Archive member exceeds size limit: {path}")
                key = path.as_posix()
                if key in paths:
                    raise ImportError(f"Duplicate archive path: {key}")
                paths[key] = info
            manifest = {}
            if "manifest.json" in paths:
                try:
                    data = json.loads(bundle.read(paths["manifest.json"]))
                    _check_structure(data)
                    entries = data.get("files", [])
                    if not isinstance(entries, list):
                        raise ValueError("files must be a list")
                    for entry in entries:
                        key = _member_path(entry["path"]).as_posix()
                        if key not in paths or key in manifest:
                            raise ValueError("manifest paths must exist and be unique")
                        manifest[key] = entry
                except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as exc:
                    raise ImportError("Invalid manifest.json") from exc
            for name, info in paths.items():
                path = PurePosixPath(name)
                if info.is_dir() or name == "manifest.json":
                    continue
                if path.suffix.lower() not in TEXT_SUFFIXES or "__MACOSX" in path.parts:
                    skipped.append(name)
                    skipped_reasons.append({"member": name, "reason": "macos-metadata"
                                            if "__MACOSX" in path.parts else "unsupported-extension"})
                    continue
                raw = bundle.read(info)
                metadata = {"claimed_models": claimed_models or [], **manifest.get(name, {})}
                source = {"archive": archive.name, "archive_sha256": archive_hash,
                          "member": name, "sha256": hashlib.sha256(raw).hexdigest(),
                          "kind": "user-submitted"}
                parsed = _parse_file(name, raw, metadata, source)
                if not parsed and path.suffix.lower() in {".md", ".txt"}:
                    skipped.append(name)
                    skipped_reasons.append({"member": name, "reason": "empty-text"})
                    continue
                records.extend(parsed)
                if len(records) > MAX_MEMBERS:
                    raise ImportError("Archive contains too many prompt records")
                if sum(len(record["text"].encode("utf-8")) for record in records) > MAX_TOTAL_BYTES:
                    raise ImportError("Expanded prompt records exceed the size limit")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ImportError("Cannot read submission archive") from exc
    if not records:
        raise ImportError("No nonempty supported prompt records found in archive")
    merged, new_count = {}, 0
    for record in records:
        rid = record["id"]
        path = store / f"{rid}.json"
        existing = merged.get(rid)
        if existing is None and path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
        if existing is None:
            merged[rid] = record
            new_count += 1
            continue
        for key in ("claimed_models", "tags", "sources", "submitted_metadata"):
            for value in record[key]:
                if value not in existing[key]:
                    existing[key].append(value)
        merged[rid] = existing
    for rid, record in merged.items():
        _atomic_json(store / f"{rid}.json", record)
    return {"archive": archive.name, "archive_sha256": archive_hash, "imported": new_count,
            "duplicates": len(records) - new_count, "skipped": skipped,
            "skipped_reasons": skipped_reasons,
            "total": len(list(store.glob("*.json"))), "store": str(store.resolve())}


def list_records(store: str | Path | None = None, include_bundled: bool = True) -> list[dict]:
    records = []
    by_hash = {}
    if include_bundled:
        for path in sorted(asset_dir("batteries").glob("*.md")):
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
            record = _record(text, path.stem, {}, {"kind": "bundled", "member": path.name})
            if record["id"] in by_hash:
                by_hash[record["id"]]["sources"].extend(record["sources"])
            else:
                by_hash[record["id"]] = record
                records.append(record)
    store = Path(store) if store is not None else default_store()
    for path in sorted(store.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(record, dict) and record.get("id") and isinstance(record.get("text"), str):
            bundled = by_hash.get(record["id"])
            if bundled is None:
                records.append(record)
            else:
                for key in ("sources", "claimed_models", "tags", "submitted_metadata"):
                    for value in record.get(key, []):
                        if value not in bundled[key]:
                            bundled[key].append(value)
    return records


def get_record(identifier: str, store: str | Path | None = None) -> dict:
    matches = [record for record in list_records(store)
               if record["id"] == identifier or record["id"].startswith(identifier)
               or record["name"] == identifier
               or any(PurePosixPath(s.get("member", "")).stem == identifier
                      for s in record.get("sources", []))]
    if len(matches) != 1:
        raise ValueError(f"Expected one corpus match for {identifier!r}; found {len(matches)}")
    return matches[0]


def cmd_corpus(args):
    store = Path(args.store) if args.store else default_store()
    if args.action == "import":
        print(json.dumps(import_zip(args.archive, store, args.claimed_model), indent=2))
    elif args.action == "show":
        print(json.dumps(get_record(args.identifier, store), ensure_ascii=False, indent=2))
    else:
        for row in list_records(store):
            print(f"{row['id'][:12]}  {row['name']}  [{row['verification']}]  claims: "
                  + (", ".join(row["claimed_models"]) or "none"))
