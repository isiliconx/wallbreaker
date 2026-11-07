# Rootaccess / Wallbreaker merge

The uploaded `rootaccess.zip` is the baseline for the rootaccess Python package and the top-level batteries, ladders, and campaign examples. The existing Wallbreaker package, terminal, dashboard, provider adapters, MCP bridge, tests, transforms, and benchmark integrations are preserved. Git history is retained; the integration is proposed on a separate branch.

`rootaccess-import.json` records the archive hash and the original non-bytecode members with their SHA-256 values. Original documentation and project metadata are preserved as `ROOTACCESS-ORIGINAL.md` and `ROOTACCESS-ORIGINAL.pyproject.toml`. The pre-merge README is `WALLBREAKER.md`.

The distribution is named rootaccess, retaining Python 3.11 compatibility and the existing AGPL-3.0-or-later license. The original archive's metadata declares MIT and attributes x10n; the retained repository attributes JailbrokenAI. Existing CLI entry points remain available, alongside rootaccess and the ZIP's wbpro alias.

Integration fixes include installed asset lookup, YAML environment expansion, campaign path resolution, explicit model roles, Anthropic adapter reuse, working conversation history, call budgets, accurate error handling, full evidence reports, and unverified submission provenance. The existing rewrite-strategy strings and original prompt/ladders/campaign files are retained. One benign smoke ladder and example are added, and become the default connectivity test.

The new corpus is available through the CLI, dashboard, and the workbench's explicit `corpus:` file reference. Import is a data operation and never runs the submitted prompts. API error strings, empty responses, and keyword matches cannot be reported as confirmed successes. Judge assessments remain candidates requiring repeated validation.

Before modifying the existing workbench implementation, its baseline suite produced **1,100 passes, 23 failures, 7 setup errors, and 1 skip**. Most failures/errors require an absent `library/ENI` collection or reference system-prompt files not present in this checkout; one Chrome-rendering test timed out. These are pre-existing environment/reference-data limitations. The merge does not fabricate those reference files or relabel failures as passes.

The default dashboard now groups the product into Workspace, Prompt library, and Connections, retaining the existing workbench under Advanced. Persistent evaluations support API targets and manual web relay, one candidate template per round, selected prompt/technique synthesis, custom multiline requests, repeated trials, operator or model assessments, stop/resume, and JSON export. Attacker and target configurations are pinned across resumes; interrupted requests and assessments resume without counting missing evidence as a pass.

Validation after integration: **1,191 tests passed, 23 failed, 7 setup errors, and 1 skipped**, with exactly the same failing/error test IDs as the pre-merge baseline. All 91 added tests passed, including 53 workflow/suite tests. The dashboard TypeScript/production build passed. Browser checks exercised manual relay, clipboard copy, multiline requests, stop/reload/resume, operator review, export, empty Connections, Prompt library, and mobile layout. A local HTTP model fixture exercised two automatic candidate rounds with two attacker, four target, and four evaluator requests, preserving one shared candidate per round. No external target models were contacted.

A wheel was built and checked for all bundled batteries, ladders, example campaigns, dashboard assets, terminal CSS, and all five console entry points. Git attributes preserve the original prompt, ladder, and campaign bytes, including CRLF line endings.
