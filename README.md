# Rootaccess

Rootaccess combines the uploaded `rootaccess.zip` campaign runner and prompt collection with the existing Wallbreaker terminal, dashboard, providers, benchmark tools, and validation workflows.

The archive is the baseline for `rootaccess/`, `batteries/`, `ladders/`, and `examples/`. Existing repository features remain available through `rootaccess workbench`, `rootaccess dashboard`, and the original `wallbreaker` / `wb` commands. The original documentation is preserved in [docs/WALLBREAKER.md](docs/WALLBREAKER.md) and [docs/ROOTACCESS-ORIGINAL.md](docs/ROOTACCESS-ORIGINAL.md).

This is a framework for repeatable model safety testing. It does not guarantee a bypass of any model or establish parity with a provider's internal evaluation suite. Imported prompts and model matches are unverified submissions. A judge's assessment is a candidate finding requiring validation.

## Install

Requires Python 3.11 or newer (the retained workbench uses Python 3.11 features).

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,dashboard]'
rootaccess --help
```

`rootaccess` and `wbpro` launch the campaign CLI. `wallbreaker`, `wb`, and `p4rs3lt0ngv3-mcp` retain their existing entry points. The combined distribution retains the repository's AGPL-3.0-or-later license; archive attribution and original metadata are preserved under `docs/`.

## Browse or import prompts

```bash
rootaccess batteries
rootaccess ladders
rootaccess corpus list
rootaccess corpus show dispatch
rootaccess corpus import /path/to/submissions.zip
rootaccess corpus import /path/to/submissions.zip --claimed-model company/model-v1
```

The dashboard's **Arsenal → jailbreak library → Import ZIP** supports the same import. Imported prompts can be inspected and copied without running them. Claims remain separate from observed results.

The original archive contains 20 battery files, including three duplicate pairs. The corpus lists 17 unique prompts and retains duplicate filenames as aliases. Original battery files remain unchanged. Imports retain full prompt text, SHA-256 identifiers, archive/member provenance, submitted metadata, and claimed model matches. They do not populate the confirmed-win library or silently configure an attacker model.

Private submissions are stored under `corpus/submissions/`, which is gitignored. Use `--store /path/to/store` on corpus commands to choose a different store. See [the submission format](docs/SUBMISSIONS.md).

## Run a connectivity check

Configure a local or authorized endpoint through environment variables:

```bash
export WB_TARGET_URL=http://localhost:8000/v1
export WB_TARGET_MODEL=my-local-model
# export WB_TARGET_KEY=...  # if your server requires authentication
rootaccess probe
rootaccess run batteries/bare.md 2 ladders/smoke-ladder.txt --sleep 0
```

The default battery and ladder are a benign connectivity/conversation check. The archive's original campaigns remain under `examples/` and must be selected explicitly.

OpenAI-compatible Chat Completions is the default. Set `WB_TARGET_BACKEND=responses` for the Responses API, or `WB_TARGET_PROTOCOL=anthropic` for an Anthropic-compatible endpoint. Anthropic native authentication uses `x-api-key`; `WB_TARGET_AUTH_STYLE=bearer` supports gateways that require bearer authentication. The original Ipeenk adapter is retained.

To use an imported prompt, pass its name or content hash with `--corpus-id`:

```bash
rootaccess run batteries/bare.md 2 ladders/smoke-ladder.txt --corpus-id my-submission
```

This replaces the battery text with the full imported prompt. In the workbench, `fire_file` also accepts `file="corpus:<name-or-hash>"`.

## Campaign configuration and evidence

YAML campaigns configure the target and optional rewriter (`brain`) and evaluator (`judge`). `${VARIABLE}` references are expanded, and missing variables produce an error. File paths can be relative to the campaign file, the working directory, or the installed bundled assets.

```bash
rootaccess run --campaign examples/local-smoke.yaml
```

A rewriter or judge is used only when configured explicitly in YAML or with `WB_BRAIN_MODEL` / `WB_JUDGE_MODEL`. Missing fields in an explicitly selected role fall back to the target environment configuration. This avoids silently spending target calls on additional model roles.

Campaigns preserve conversation history by default. `--independent` starts a fresh conversation for each request; `--same` repeats the first request. `--max-calls` bounds target, rewriter, and judge requests combined (default 64). `--mutate-k` controls the archive's optional rewrite attempts. No live campaign runs during import, installation, or dashboard browsing.

Reports are written under the gitignored `reports/` directory:

- `.json`: full requests, responses, assessments, assessment sources, and errors.
- `.meta.json`: model IDs, system prompt, objective, input hashes, mode, call counts, and stop reason.
- `.md`: a readable assessment table.

Keyword matches are diagnostic signals and cannot create a successful finding. Without a judge, nonempty responses are `UNVERIFIED`. Model-graded responses are `judge_assessed`, never automatically verified. Network failures, empty answers, and malformed judge output remain distinct. Reports retain full input/output text and should be handled according to your test-data policy.

## Retained workbench

```bash
rootaccess workbench --help
rootaccess dashboard --help
rootaccess dashboard --host 127.0.0.1 --port 8765
```

The existing workbench retains OpenAI/Anthropic providers, the terminal agent, transforms, external corpus integrations, benchmark loaders, repeated validation, reports, and regression checks. Its optional dependencies and setup are documented in [docs/WALLBREAKER.md](docs/WALLBREAKER.md). No external collections, secrets, or previous local runs were copied into the merged source tree.

## Development

```bash
.venv/bin/python -m pytest tests/test_rootaccess_*.py tests/test_dashboard.py tests/test_fire_file.py
cd wallbreaker/dashboard/web
npm ci
npm run build
```

The full existing suite is `.venv/bin/python -m pytest tests`. Some legacy tests require external, gitignored reference collections and a functioning local Chrome installation. The merge's baseline and validation notes are recorded in [docs/MERGE.md](docs/MERGE.md).
