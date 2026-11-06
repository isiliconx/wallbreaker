# Rootaccess / Wallbreaker merge

The uploaded `rootaccess.zip` is the baseline for the rootaccess Python package and the top-level batteries, ladders, and campaign examples. The existing Wallbreaker package, terminal, dashboard, provider adapters, MCP bridge, tests, transforms, and benchmark integrations are preserved. Git history is retained; the integration is proposed on a separate branch.

`rootaccess-import.json` records the archive hash and the original non-bytecode members with their SHA-256 values. Original documentation and project metadata are preserved as `ROOTACCESS-ORIGINAL.md` and `ROOTACCESS-ORIGINAL.pyproject.toml`. The pre-merge README is `WALLBREAKER.md`.

The distribution is named rootaccess, retaining Python 3.11 compatibility and the existing AGPL-3.0-or-later license. The original archive's metadata declares MIT and attributes x10n; the retained repository attributes JailbrokenAI. Existing CLI entry points remain available, alongside rootaccess and the ZIP's wbpro alias.

Integration fixes include installed asset lookup, YAML environment expansion, campaign path resolution, explicit model roles, Anthropic adapter reuse, working conversation history, call budgets, accurate error handling, full evidence reports, and unverified submission provenance. The existing rewrite-strategy strings and original prompt/ladders/campaign files are retained. One benign smoke ladder and example are added, and become the default connectivity test.

The new corpus is available through the CLI, dashboard, and the workbench's explicit `corpus:` file reference. Import is a data operation and never runs the submitted prompts. API error strings, empty responses, and keyword matches cannot be reported as confirmed successes. Judge assessments remain candidates requiring repeated validation.

Before modifying the existing workbench implementation, its baseline suite produced **1,100 passes, 23 failures, 7 setup errors, and 1 skip**. Most failures/errors require an absent `library/ENI` collection or reference system-prompt files not present in this checkout; one Chrome-rendering test timed out. These are pre-existing environment/reference-data limitations. The merge does not fabricate those reference files or relabel failures as passes.

Validation after integration: **60 focused checks passed**, and the dashboard TypeScript/production build passed. The full suite produced **1,138 passes, 23 failures, 7 setup errors, and 1 skip**, with exactly the same failing/error test IDs as the pre-merge baseline. All 38 added tests passed. No new failure IDs were introduced. A wheel was built and checked for all bundled batteries, ladders, example campaigns, dashboard assets, terminal CSS, and all five console entry points. Git attributes preserve the original prompt, ladder, and campaign bytes, including CRLF line endings. No live target-model campaigns were run.
