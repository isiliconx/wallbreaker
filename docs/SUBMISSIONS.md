# Submitted jailbreak prompts

A ZIP can contain UTF-8 `.md` / `.txt` prompts, JSON or YAML prompt records, lists of records, or JSONL. Prompt files are read as data. Import does not execute files or contact models.

A structured record can look like this:

```json
{
  "name": "Example submission",
  "prompt": "The exact submitted prompt text goes here.",
  "claimed_models": ["company/model-v1"],
  "tags": ["user-submitted"],
  "notes": "Submitter's report, not independently verified."
}
```

`text` or `content` can be used instead of `prompt`. `model`, `models`, or `target_models` are also accepted for model claims. A JSON object containing `prompts: [...]` can hold several records.

For plain-text prompt files, optional metadata can be supplied by a root `manifest.json`:

```json
{
  "files": [
    {
      "path": "prompts/example.md",
      "name": "Example submission",
      "claimed_models": ["company/model-v1"]
    }
  ]
}
```

All imported records start with `verification: "unverified"` and no observations. Submitted fields such as `verified: true`, scores, or success claims are retained only as submitted metadata. Import does not promote them into the existing confirmed-win library. Filenames containing model names remain filenames; model compatibility is not inferred as a fact.

Exact decoded prompt text is retained, including whitespace and line endings. A UTF-8 BOM is removed when decoding. Content hashes deduplicate identical text while preserving original source aliases and combining model claims. Archive/member SHA-256 values identify the original inputs. Source text is not reformatted or truncated.

Python files, bytecode, binaries, nested ZIPs, and other unsupported extensions are skipped; nested archives are never opened recursively. Empty or whitespace-only `.md` / `.txt` files are also skipped after UTF-8 decoding. The import summary retains the `skipped` filename list and adds `skipped_reasons`, a list of objects such as `{"member": "Break/empty.txt", "reason": "empty-text"}`. Other reasons are `unsupported-extension` and `macos-metadata`. An archive with no nonempty supported prompt records is rejected without creating a store. Empty structured prompt fields remain invalid.

Unsafe paths, symbolic links, encryption, duplicate archive paths, malformed supported files, excessive nesting, and oversized archives are rejected before the import batch is saved, including when other members would be skipped. Limits are 2,000 archive members, 2 MiB per member, and 64 MiB expanded data. A supported structured file must contain prompt data; remove unrelated JSON/YAML configuration files before importing a submissions ZIP.

Private records live under the selected project's gitignored `corpus/submissions/`. CLI imports use the current working directory by default. The dashboard uses the config file's directory, or the parent of the configured sessions directory when no config is loaded. Use `--store` when importing from another directory.

## Storo clipboard collection

Import the outer Storo ZIP directly from the project directory:

```bash
rootaccess corpus import /path/to/storo-selection-2026-11-07.zip --store corpus/submissions
```

Its `Break/` text files are individual submitted records. `Break/AGENTS.md` and `Break/SOUL*.md` are retained as prompt data; their contents do not configure the repository or grant instructions to the importer. The empty `Break/kovak-stealth.txt` is reported with `empty-text`, and `Break/rootaccess.zip` is reported with `unsupported-extension`. Exact duplicates share a record with all original member aliases. The archive has no structured model-claim manifest, so its model-like filenames do not populate compatibility claims or observations. Review and evaluation supply that evidence separately.

A subsequent evaluation should record the actual model/version, endpoint, date, prompt hash, conversation mode, generation settings, assessment source, and repeated outcomes. A claimed match is not a measured transfer result; a judge assessment is not confirmation that generated code works.
