# Research and capability boundaries

Research reviewed November 7, 2026. This report uses primary papers, conference
proceedings, and the research organizations' own reports. Dates below distinguish
first publication from later revisions where relevant. Published attack success
rates are conditional on particular models, settings, cases, evaluators, and
attempt budgets; they are not performance estimates for this project.

The workspace is an evaluation harness. A finite set of passing cases cannot
establish that an artifact will jailbreak every request or every model. The
catalog's `available` label describes a bounded workflow behavior; `research`
marks a direction that needs additional implementation. Neither label certifies
reproduction of a paper or a model vulnerability.

## What the research supports

| Primary source | Date | Scope and practical implication |
| --- | --- | --- |
| [Crescendo: Great, Now Write an Article About That](https://arxiv.org/abs/2404.01833) | First April 2, 2024; revised February 26, 2025; USENIX Security 2025 | Gradual multi-turn escalation depends on the target's preceding replies. A static template cannot represent that interaction by itself. |
| [Automated Red Teaming with GOAT](https://proceedings.mlr.press/v267/pavlova25a.html) | ICML, July 2025 | An attacker selects among techniques using the current target response and conversational context. This motivates adaptive orchestration, not concatenating every technique into one prompt. |
| [X-Teaming: Multi-Turn Jailbreaks and Defenses with Adaptive Multi-Agents](https://arxiv.org/abs/2504.13203) | First April 15, 2025; revised August 23, 2025; COLM 2025 | Separate planning, attack optimization, and verification support diverse conversational tests. More agent calls alone do not establish better coverage. |
| [Adversarial Reasoning at Jailbreaking Time](https://arxiv.org/abs/2502.01633) | First February 3, 2025; revised June 25, 2025; ICML 2025 | Feedback can guide test-time search. Its loss signal and access assumptions require inspection before claiming an API-only reproduction. |
| [Best-of-N Jailbreaking](https://arxiv.org/abs/2412.03556) | First December 4, 2024; revised December 19, 2024 | Sampling budget strongly affects measured success. Compare methods at explicit budgets and retain all attempts, not just their best output. |
| [Imperceptible Jailbreaking against Large Language Models](https://arxiv.org/abs/2510.05025) | October 6, 2025 | Invisible Unicode variation selectors can alter tokenization without an obvious rendered change. Save exact text and transform provenance. Existing character encoders do not reproduce its adversarial suffix search. |
| [MINJA: Memory Injection Attacks on LLM Agents via Query-Only Interaction](https://arxiv.org/abs/2503.03704) | First March 5, 2025; latest listed revision February 12, 2026 | Query interactions can poison records that a memory-enabled agent later retrieves. This requires a genuine memory store and later retrieval; conversation priming alone is a different test. |
| [AgentDojo](https://arxiv.org/abs/2406.13352) | First June 19, 2024; revised November 24, 2024 | Evaluate agents acting over untrusted tool data, with task-state assertions and clean utility baselines. Some agents fail legitimate tasks even without an attack. |
| [MCPTox](https://arxiv.org/abs/2508.14925) | First August 19, 2025; revised September 29, 2026 | Tool metadata is a distinct poisoning surface, including before a tool executes. A chat message labeled as a tool schema is not an end-to-end test of an actual tool-using agent. |
| [AgentLAB: Benchmarking LLM Agents against Long-Horizon Attacks](https://arxiv.org/abs/2602.16901) | February 18, 2026 preprint | Long-horizon user-agent-environment interactions include intent hijacking, tool chaining, task injection, objective drift, and memory poisoning. Isolated stateful environments are needed to test these effects. |
| [STAR-Teaming](https://aclanthology.org/2026.findings-acl.1470/) | ACL Findings, July 2026 | Strategy-response organization can reduce redundant exploration. Library retrieval and informal strategy labels do not implement the published multiplex-network search. |
| [Red-TTT: Test-Time Training for Automated Jailbreaking Large Language Models](https://arxiv.org/abs/2610.05282) | October 4, 2026 preprint | The attacker updates its weights during per-behavior search. This requires a trainable attacker and training infrastructure; API retries and scratchpad memory do not update weights. |

These findings are evaluated on the sources' own experimental settings. They
justify testable engineering directions rather than guarantees about current
commercial products. A source appearing in the catalog is provenance for the
idea, not a claim that its implementation or reported results have been copied.

## Existing repository and workspace gaps

The existing repository already contains modules named `crescendo`, `goat`,
`pair`, `tree_attack`, `best_of_n`, `memory_poison`, and `indirect_inject`, plus
encoding, Unicode, and structural transforms. Module names do not establish
faithful academic reproduction. Adding more technique names would leave the
central workflow gaps unresolved.

Before the adaptive workspace extension, the saved workflow composed one
reusable template, tested each question/trial in a fresh conversation, and
revised the template across rounds. Its technique selections supplied
descriptions to the attacker. It did not make those selections equivalent to
executing transforms or conducting a reply-dependent conversation.

The method catalog distinguishes four available behavior labels:

- `single-prompt`: a reusable template evaluated in independent conversations.
- `adaptive-dialogue`: bounded, reply-dependent dialogue inspired by GOAT and
  Crescendo, without claiming faithful reproduction of either.
- `context-retention`: influence of earlier content within the same session.
- `text-obfuscation`: existing allowlisted character transforms, without
  tokenizer-ID control or a reproduction of adversarial suffix optimization.

The catalog is descriptive metadata. Runtime code must enforce budgets, case
scope, input validation, allowed references/transforms, and API/relay state.
The restricted attacker actions are `search_library`, `read_reference`,
`read_method`, `transform_text`, `read_observations`, `remember`, `send`,
`restart`, and `finish`. Method lookup returns curated metadata and never fetches
arbitrary source URLs. Restart/backtracking creates a fresh conversation branch
while retaining all evidence, with at most two restarts per case and eight total
target turns across branches. This is bounded branching, not full tree search or
a reproduction of STAR-Teaming.
`remember` is case scratchpad storage, not a write to target memory. Observations
are visible replies and assessments, not access to hidden target state.
`send` routes a message to the configured target API or human relay; a saved
transform `artifact_id` avoids corrupting invisible characters by recopying. These
actions do not provide a shell, arbitrary file access, arbitrary network access,
or authority to execute instructions discovered in reference text.

Four directions remain research-only in this catalog:

- Persistent memory needs a real memory adapter, clean/poisoned snapshots,
  fresh-session controls, and evidence showing what was stored and retrieved.
- Agent/tool injection needs isolated tools, fake or controlled data, observable
  action traces, and assertions against final environment state. The existing
  text-carrier probes are useful simulations, not proof of tool execution.
- Attacker weight adaptation needs training infrastructure. It cannot be
  supplied by an ordinary sampling-only attacker endpoint.
- Strategy-aware search needs an implemented strategy-response graph and a
  validated scheduler. Corpus lookup alone is insufficient.

## Submitted library

The supplied `storo-selection-2026-11-07.zip` contained 135 nonempty files that
yielded 131 exact unique private prompt records after duplicate consolidation.
They are candidate references, not a measured benchmark. Submitter/author
attributions, filenames, model names, and success claims do not establish
compatibility or authorship as verified facts. The submission set did not supply
standardized proof sufficient to reproduce the claimed outcomes.

Instructions inside submissions remain inert source data. Import does not run
them, grant them authority, or mark their claims as confirmed wins. Private
records belong in the gitignored submissions store; a research report or public
pull request should not need to reproduce their prompt bodies. Preserve exact
content hashes and source aliases so later observations can identify the actual
record tested. See [submission handling](SUBMISSIONS.md).

## Evaluation requirements

[A StrongREJECT for Empty Jailbreaks](https://arxiv.org/abs/2402.10260), first
published February 15, 2024 and revised August 27, 2024, shows why surface
agreement and non-refusal can overstate useful fulfillment: some techniques
degrade the target's answer quality. Grade the substance against the original
test objective, retain uncertainty, and calibrate automated assessments with
human review. A judge score does not prove code execution, real-world validity,
or violation of a particular deployment's policy.

Keep search cases separate from held-out validation cases, record repeated
trials, and retain failures and errors. Include harmless capability controls to
detect a method that merely damages output quality. Pin model identifier,
endpoint/protocol, generation settings, case identity, content hashes, and the
attempt budget. A judge error is not an assessed pass. Report which responses
were operator-assessed, model-assessed, or unverified. Human relay adds another
source of uncertainty: the saved text cannot by itself verify the remote model,
its hidden settings, persistent memory, or tool actions.

[Anthropic's next-generation Constitutional Classifiers report](https://www.anthropic.com/research/next-generation-constitutional-classifiers),
published January 9, 2026, discusses reconstruction and output-obfuscation
failures and screening linked inputs and outputs. This supports retaining the
whole visible exchange and its interpretation context instead of judging one
isolated output string. Preserve raw and transformed text; make invisible
characters inspectable without silently normalizing the evidence.

## Comparison with frontier-lab practice

[OpenAI's Atlas hardening report](https://openai.com/index/hardening-atlas-against-prompt-injection/),
published December 22, 2025, describes an RL-trained attacker with simulator
rollouts and action-trace feedback. [Anthropic's browser prompt-injection report](https://www.anthropic.com/research/prompt-injection-defenses),
published November 24, 2025, describes an internal adaptive Best-of-N attacker
with 100 attempts per environment alongside expert human red teaming.

This project shares the broad attacker-target-evaluation pattern. Public
descriptions do not establish parity with those organizations' infrastructure,
training access, compute, private evaluations, or operational safeguards. Its
usefulness should be demonstrated through reproducible findings and measured
coverage. More references and techniques are opportunities to test, not evidence
that every model can be broken.
