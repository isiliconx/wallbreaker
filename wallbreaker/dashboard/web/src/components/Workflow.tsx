import { useEffect, useState } from "react";
import { api, type CorpusPrompt, type RoleAssignments } from "../api";
import { workflowApi, type Assessment, type StrategyMode, type WorkflowOptions, type WorkflowResult, type WorkflowRun, type WorkflowTransform, type WorkflowTurn } from "../workflowApi";
import { RoleChooser } from "./RoleChooser";

const LABELS: Record<Assessment, string> = {
  COMPLIED: "Fulfilled",
  PARTIAL: "Partially fulfilled",
  REFUSED: "Refused",
  UNVERIFIED: "Unassessed",
};
const STATUS: Record<WorkflowRun["status"], string> = {
  ready: "Ready", running: "Running", awaiting_relay: "Waiting for web response",
  awaiting_review: "Review needed", round_complete: "Round complete", completed: "Finished",
  stopped: "Stopped", error: "Error",
};
const message = (error: unknown) => error instanceof Error ? error.message : String(error);
const lines = (value: string) => value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
const toggle = (values: string[], value: string) => values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
const MODES: Record<StrategyMode, { name: string; description: string }> = {
  single: { name: "Single reusable prompt", description: "Apply one candidate to every selected request, then refine between rounds." },
  adaptive: { name: "Adaptive conversation", description: "Plan each next message from the target's observed reply within the same conversation." },
  context: { name: "Session context probe", description: "Test priming and retention within one chat. This does not demonstrate persistent memory across sessions." },
};
const traceText = (value: unknown) => typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? String(value);
const escapedText = (value: string) => JSON.stringify(value).replace(/[^\x20-\x7e]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);

function TransformEvidence({ transform }: { transform: WorkflowTransform }) {
  return <details className="workflow-payload-detail"><summary>Transform evidence · {transform.chain.join(" → ") || "empty chain"}</summary>
    <p className="workflow-caption">{transform.lossy ? "Includes a lossy transform; original text may not be recoverable." : transform.chain.length ? "Lossless transform chain." : "No transforms in this recorded chain."}{transform.scope ? ` ${transform.scope}` : ""}</p>
    <p className="workflow-caption workflow-hash">Original SHA-256: {transform.original_sha256}<br />Sent SHA-256: {transform.transformed_sha256}{transform.utf8_bytes == null ? "" : ` · ${transform.utf8_bytes} UTF-8 bytes`}</p>
    <label>Escaped preview<pre className="workflow-response">{transform.escaped_preview}</pre></label>
    {transform.original_text != null && <details className="workflow-payload-detail"><summary>Original message before this chain</summary><pre className="workflow-response">{transform.original_text}</pre></details>}
    {transform.transformed_utf8_base64 && <details className="workflow-payload-detail"><summary>Exact sent UTF-8 bytes · Base64</summary><pre className="workflow-response">{transform.transformed_utf8_base64}</pre></details>}
  </details>;
}

function ToolEvidence({ trace }: { trace: NonNullable<WorkflowResult["tool_trace"]> }) {
  return <details className="workflow-payload-detail"><summary>Attacker tool trace · {trace.length} calls</summary>
    {trace.map((call, index) => <div className="workflow-tool-call" key={index}><b>{call.tool}</b><label>Input<pre className="workflow-response">{traceText(call.input)}</pre></label><label>Output<pre className="workflow-response">{traceText(call.output)}</pre></label></div>)}
  </details>;
}

function TurnEvidence({ turn }: { turn: WorkflowTurn }) {
  return <details className="workflow-turn">
    <summary>Turn {turn.index}{turn.branch == null ? "" : ` · Chat ${turn.branch + 1}`}<span>{turn.assessment ? LABELS[turn.assessment.label as Assessment] || turn.assessment.label : "Observation recorded"}</span></summary>
    <label>Exact message sent<pre className="workflow-response">{turn.prompt}</pre></label>
    <label>Target response<pre className="workflow-response">{turn.response || "No response recorded."}</pre></label>
    {turn.assessment && <p className="workflow-caption">Turn observation: {LABELS[turn.assessment.label as Assessment] || turn.assessment.label} · {turn.assessment.source || "unassessed"}{turn.assessment.score == null ? "" : ` · Score: ${turn.assessment.score}`}{turn.assessment.reason ? ` · ${turn.assessment.reason}` : ""}</p>}
    <details className="workflow-payload-detail"><summary>Escaped message and conversation transcript</summary>
      <pre className="workflow-response">{escapedText(turn.prompt)}</pre>
      {(turn.messages || []).map((item, index) => <div className="workflow-transcript-message" key={index}><b>{item.role}</b><pre className="workflow-response">{item.content}</pre></div>)}
    </details>
    {turn.transform && <TransformEvidence transform={turn.transform} />}
    {!!turn.tool_trace?.length && <ToolEvidence trace={turn.tool_trace} />}
  </details>;
}

function ResultCard({ result, disabled, onAssess }: {
  result: WorkflowResult;
  disabled: boolean;
  onAssess: (result: WorkflowResult, label: Assessment, reason: string) => Promise<void>;
}) {
  const [label, setLabel] = useState<Assessment>(result.label in LABELS ? result.label as Assessment : "UNVERIFIED");
  const [reason, setReason] = useState(result.reason || "");
  useEffect(() => {
    setLabel(result.label in LABELS ? result.label as Assessment : "UNVERIFIED");
    setReason(result.reason || "");
  }, [result.label, result.reason]);
  const complete = result.complete !== false;
  return <details className="workflow-result" open={!complete || result.label === "UNVERIFIED" ? true : undefined}>
    <summary><span className={`workflow-assessment workflow-label-${complete ? result.label.toLowerCase() : "pending"}`}>{complete ? LABELS[result.label as Assessment] || result.label : "In progress"}</span>
      <span className="workflow-result-question">{result.question}</span><small>Trial {result.trial}{result.turns?.length ? ` · ${result.turns.length} turns` : ""}</small></summary>
    <div className="workflow-result-body">
      <p className="workflow-caption">{complete ? `Assessment source: ${result.source || "unassessed"}${result.score == null ? "" : ` · Score: ${result.score}`}` : "This case is still running. Interim turns do not count as a completed or fulfilled case."}</p>
      {complete && result.reason && <p>{result.reason}</p>}
      {result.turns?.length ? <div className="workflow-turns">{result.turns.map((turn, index) => <TurnEvidence key={`${turn.index}-${index}`} turn={turn} />)}</div> : <>
        <label>Target response<pre className="workflow-response">{result.response || "No response recorded."}</pre></label>
        <details className="workflow-payload-detail"><summary>View exact test payload</summary><pre className="workflow-response">{result.payload}</pre><pre className="workflow-response">{escapedText(result.payload)}</pre></details>
        {result.transform && <TransformEvidence transform={result.transform} />}
      </>}
      {!!result.tool_trace?.length && <ToolEvidence trace={result.tool_trace} />}
      {!!result.scratchpad?.length && <details className="workflow-payload-detail"><summary>Case scratchpad · {result.scratchpad.length} entries</summary><p className="workflow-caption">Explicit tool notes for this case only. These are not private model reasoning or persistent target memory.</p>{result.scratchpad.map((entry, index) => <pre className="workflow-response" key={index}>{entry}</pre>)}</details>}
      {complete && <div className="workflow-review-fields">
        <label>Operator assessment<select aria-label={`Assessment for trial ${result.trial}: ${result.question}`} value={label} onChange={(event) => setLabel(event.target.value as Assessment)} disabled={disabled}>
          {(Object.keys(LABELS) as Assessment[]).map((item) => <option key={item} value={item}>{LABELS[item]}</option>)}
        </select></label>
        <label>Assessment reason<input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Evidence in the response" disabled={disabled} /></label>
        <button type="button" className="mini-btn" disabled={disabled} onClick={() => void onAssess(result, label, reason)}>Save assessment</button>
      </div>}
    </div>
  </details>;
}

export function Workflow({ onOpenConnections }: { onOpenConnections: () => void }) {
  const [options, setOptions] = useState<WorkflowOptions>({ suites: [], techniques: [] });
  const [corpus, setCorpus] = useState<CorpusPrompt[]>([]);
  const [roles, setRoles] = useState<Partial<RoleAssignments> | null>(null);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [targetMode, setTargetMode] = useState<"api" | "relay">("api");
  const [targetName, setTargetName] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [suite, setSuite] = useState("smoke");
  const [customQuestions, setCustomQuestions] = useState("");
  const [customTargetRequest, setCustomTargetRequest] = useState("");
  const [seedIds, setSeedIds] = useState<string[]>([]);
  const [techniqueIds, setTechniqueIds] = useState<string[]>([]);
  const [strategyMode, setStrategyMode] = useState<StrategyMode>("single");
  const [maxTurns, setMaxTurns] = useState(4);
  const [turnPlan, setTurnPlan] = useState("");
  const [transformChain, setTransformChain] = useState<string[]>([]);
  const [candidate, setCandidate] = useState("");
  const [delivery, setDelivery] = useState<"user" | "system">("user");
  const [maxRounds, setMaxRounds] = useState(3);
  const [maxCalls, setMaxCalls] = useState(60);
  const [trials, setTrials] = useState(1);
  const [maxTokens, setMaxTokens] = useState(1024);
  const [autoIterate, setAutoIterate] = useState(true);
  const [sourceSearch, setSourceSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [relayResponse, setRelayResponse] = useState("");
  const [relayLabel, setRelayLabel] = useState<Assessment>("UNVERIFIED");
  const [relayReason, setRelayReason] = useState("");

  const remember = (next: WorkflowRun) => {
    setRun(next);
    setRuns((current) => [next, ...current.filter((item) => item.id !== next.id)]);
    window.localStorage.setItem("rootaccess.workflow.run", next.id);
  };
  useEffect(() => {
    let alive = true;
    const load = async () => {
      const loaded = await Promise.allSettled([workflowApi.options(), api.corpus(), api.roles(), workflowApi.runs()]);
      if (!alive) return;
      const [available, prompts, assignments, saved] = loaded;
      if (available.status === "fulfilled") {
        setOptions(available.value);
        setSuite(available.value.suites.find((item) => item.available && item.id === "smoke")?.id || available.value.suites.find((item) => item.available)?.id || "custom");
      }
      if (prompts.status === "fulfilled") setCorpus(prompts.value);
      if (assignments.status === "fulfilled") setRoles(assignments.value);
      if (saved.status === "fulfilled") {
        setRuns(saved.value);
        const lastId = window.localStorage.getItem("rootaccess.workflow.run");
        const previous = saved.value.find((item) => item.id === lastId);
        if (previous) setRun(previous);
      }
      const failed = loaded.filter((item): item is PromiseRejectedResult => item.status === "rejected");
      if (failed.length) setError(failed.map((item) => message(item.reason)).join(" · "));
      setLoading(false);
    };
    void load();
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!run || run.status !== "running") return;
    let alive = true;
    let polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      workflowApi.get(run.id).then((next) => {
        if (alive) remember(next);
      }).catch((failure) => { if (alive) setError(message(failure)); }).finally(() => { polling = false; });
    }, 1000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [run?.id, run?.status]);
  useEffect(() => {
    setRelayResponse(""); setRelayReason(""); setRelayLabel("UNVERIFIED");
  }, [run?.pending_relay?.request_id]);
  useEffect(() => {
    if (!run?.id) return;
    const frame = window.requestAnimationFrame(() => {
      const target = document.querySelector(run.pending_relay ? ".workflow-relay" : ".workflow-run-summary");
      target?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [run?.id, run?.pending_relay?.request_id]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const perform = async (action: () => Promise<WorkflowRun>) => {
    setBusy(true); setError("");
    try { remember(await action()); }
    catch (failure) { setError(message(failure)); }
    finally { setBusy(false); }
  };
  const refreshRoles = () => {
    api.roles().then(setRoles).catch((failure) => setError(message(failure)));
    workflowApi.options().then(setOptions).catch((failure) => setError(message(failure)));
  };
  const create = () => perform(async () => {
    const next = await workflowApi.create({
      target_mode: targetMode, target_name: targetName.trim(), target_url: targetUrl.trim(),
      suite_id: suite, custom_questions: [...lines(customQuestions), ...(customTargetRequest.trim() ? [customTargetRequest] : [])], seed_ids: seedIds, technique_ids: techniqueIds,
      candidate_prompt: strategyMode === "single" ? candidate : "", delivery: targetMode === "relay" || strategyMode !== "single" ? "user" : delivery,
      max_rounds: maxRounds, max_calls: maxCalls, trials, max_tokens: maxTokens, auto_iterate: autoIterate,
      strategy_mode: strategyMode, max_turns: maxTurns, turn_plan: strategyMode === "single" ? [] : lines(turnPlan), transform_chain: transformChain,
    });
    remember(next);
    return workflowApi.start(next.id);
  });
  const copy = async (value: string, label: string) => {
    try { await navigator.clipboard.writeText(value); setNotice(`${label} copied.`); }
    catch { setError("Clipboard access failed. Select and copy the text directly."); }
  };
  const exportRun = async () => {
    if (!run) return;
    setBusy(true); setError("");
    try {
      const data = await workflowApi.export(run.id);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `rootaccess-${run.id}.json`; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("Evaluation exported.");
    } catch (failure) { setError(message(failure)); }
    finally { setBusy(false); }
  };
  const newEvaluation = () => {
    setRun(null); setError(""); window.localStorage.removeItem("rootaccess.workflow.run");
  };
  const assess = async (result: WorkflowResult, label: Assessment, reason: string) => {
    if (run) await perform(() => workflowApi.assess(run.id, { result_id: result.id, label, reason }));
  };
  const selectedSuite = options.suites.find((item) => item.id === suite);
  const customCount = lines(customQuestions).length + (customTargetRequest.trim() ? 1 : 0);
  const testCount = (selectedSuite?.count || 0) + customCount;
  const filteredCorpus = corpus.filter((item) => `${item.name} ${item.claimed_models.join(" ")}`.toLowerCase().includes(sourceSearch.toLowerCase()));
  const canContinue = !!run && ["awaiting_review", "round_complete"].includes(run.status);
  const allFulfilled = !!run && run.coverage.total > 0 && run.coverage.completed === run.coverage.total && run.coverage.pass_count === run.coverage.total;
  const relayUrl = run?.target_url && /^https?:\/\//i.test(run.target_url) ? run.target_url : null;
  const transforms = options.techniques.filter((item) => item.id.startsWith("transform:"));
  const runMode = run?.settings.strategy_mode || "single";
  const relayHistory = run?.pending_relay ? run.results.find((item) => item.test_id === run.pending_relay!.test_id && item.trial === run.pending_relay!.trial)?.turns || [] : [];

  return <div className="workflow-workspace">
    <div className="workflow-page-heading"><div><span className="workflow-eyebrow">MODEL RESILIENCE EVALUATION</span><h1>Test prompts. Follow the evidence.</h1>
      <p>Evaluate a reusable prompt or a conversation strategy, with recorded target responses and bounded refinement.</p></div>
      <button type="button" className="mini-btn" onClick={onOpenConnections}>Manage connections</button></div>
    <div className="workflow-run-picker">
      <label htmlFor="workflow-saved-run">Saved evaluations</label><select id="workflow-saved-run" value={run?.id || ""} disabled={busy} onChange={(event) => {
        const id = event.target.value;
        if (id) void perform(() => workflowApi.get(id)); else newEvaluation();
      }}><option value="">New evaluation</option>{runs.map((item) => <option key={item.id} value={item.id}>{item.target_name || (item.target_mode === "relay" ? "Web target" : "API target")} · {STATUS[item.status]} · {item.id}</option>)}</select>
      {run && <button type="button" className="mini-btn" disabled={busy} onClick={newEvaluation}>New evaluation</button>}
    </div>
    {error && <div className="err workflow-alert" role="alert">{error}<button type="button" className="mini-btn" onClick={() => setError("")} aria-label="Dismiss error">Dismiss</button></div>}
    {notice && <div className="workflow-notice" role="status">{notice}</div>}
    {loading ? <div className="card workflow-loading">Loading evaluation workspace…</div> : <div className={`workflow-layout ${run ? "workflow-has-run" : ""}`}>
      <form className="workflow-setup card" onSubmit={(event) => { event.preventDefault(); void create(); }}>
        <div className="workflow-section-heading"><span className="workflow-step">01</span><h2>Target and models</h2></div>
        {run && <p className="workflow-caption">These settings create a new evaluation. The saved evaluation remains available above.</p>}
        <fieldset className="workflow-target-mode"><legend>Target connection</legend>
          <label className={targetMode === "api" ? "selected" : ""}><input type="radio" name="target-mode" value="api" checked={targetMode === "api"} onChange={() => setTargetMode("api")} /><b>API</b><span>Run tests automatically</span></label>
          <label className={targetMode === "relay" ? "selected" : ""}><input type="radio" name="target-mode" value="relay" checked={targetMode === "relay"} onChange={() => setTargetMode("relay")} /><b>Web / manual relay</b><span>Copy prompts and paste replies</span></label>
        </fieldset>
        <label htmlFor="workflow-target-name">Target display name<input id="workflow-target-name" maxLength={200} value={targetName} onChange={(event) => setTargetName(event.target.value)} placeholder={targetMode === "relay" ? "e.g. Internal assistant web app" : "Optional evaluation label"} /></label>
        {targetMode === "relay" && <label htmlFor="workflow-target-url">Target URL <span className="workflow-optional">optional</span><input id="workflow-target-url" type="url" maxLength={2000} value={targetUrl} onChange={(event) => setTargetUrl(event.target.value)} placeholder="https://…" /></label>}
        <div className="workflow-model-roles">
          <div><span className="workflow-caption">Composes prompts and plans conversation turns</span>{roles?.attacker && options.configured_roles?.attacker !== false ? <RoleChooser role="attacker" value={roles.attacker} onSaved={refreshRoles} /> : <button type="button" className="mini-btn" onClick={onOpenConnections}>{strategyMode === "single" ? "Connect attacker · optional" : "Connect attacker · optional with a stage plan"}</button>}</div>
          {targetMode === "api" && <div><span className="workflow-caption">Receives every test payload</span>{roles?.target && options.configured_roles?.target !== false ? <RoleChooser role="target" value={roles.target} onSaved={refreshRoles} /> : <button type="button" className="mini-btn" onClick={onOpenConnections}>Connect API target</button>}</div>}
          <div><span className="workflow-caption">Assesses responses, or review them yourself</span>{roles?.judge && options.configured_roles?.judge !== false ? <RoleChooser role="judge" value={roles.judge} onSaved={refreshRoles} /> : <button type="button" className="mini-btn" onClick={onOpenConnections}>Connect evaluator · optional</button>}</div>
        </div>
        <label htmlFor="workflow-strategy-mode">Evaluation strategy<select id="workflow-strategy-mode" value={strategyMode} onChange={(event) => setStrategyMode(event.target.value as StrategyMode)}>{(Object.keys(MODES) as StrategyMode[]).map((mode) => <option key={mode} value={mode}>{MODES[mode].name}</option>)}</select></label>
        <p className="workflow-caption">{MODES[strategyMode].description}</p>
        {strategyMode !== "single" && <label htmlFor="workflow-max-turns">Maximum turns per case<input id="workflow-max-turns" type="number" min={1} max={8} required value={maxTurns} onChange={(event) => setMaxTurns(Number(event.target.value))} /></label>}
        {targetMode === "relay" && <p className="workflow-caption">{strategyMode === "single" ? "Use a fresh target conversation for each test and trial." : "Keep the same target chat for all turns of a case. Start a fresh chat when the relay conversation ID changes."}</p>}
        {(options.methods?.length || options.attacker_tools?.length) ? <details className="workflow-source-picker workflow-methods"><summary>Methods and attacker tools <span>Sources and limits</span></summary>
          {options.methods?.map((method) => <article className="workflow-method" key={method.id}><div><b>{method.name}</b><span className={`workflow-method-status workflow-method-${method.status}`}>{method.status === "research" ? "Research only · not enabled" : `Available · ${MODES[method.mode].name}`}</span></div><p>{method.description}</p>{method.limitations && <p className="workflow-caption">{Array.isArray(method.limitations) ? method.limitations.join(" ") : method.limitations}</p>}<div className="workflow-method-sources">{method.sources.map((source, index) => /^https?:\/\//i.test(source.url) ? <a key={index} href={source.url} target="_blank" rel="noopener noreferrer">{source.title}{source.date ? ` (${source.date})` : ""}</a> : <span key={index}>{source.title}</span>)}</div></article>)}
          {!!options.attacker_tools?.length && <><h3>Available restricted tools</h3><p className="workflow-caption">The attacker planner can use these tools in conversation modes.</p><div className="workflow-tools">{options.attacker_tools.map((tool) => <div key={tool.id}><b>{tool.name}</b><span>{tool.description}</span></div>)}</div><p className="workflow-caption">The scratchpad stores explicit notes within one case. It does not give the target persistent memory across conversations.</p></>}
        </details> : null}
        <div className="workflow-section-heading"><span className="workflow-step">02</span><h2>Prompt sources and tools</h2><span className="workflow-count">{seedIds.length} selected</span></div>
        <p className="workflow-caption">Choose up to 20 reference prompts for the attacker to combine. Submitted claims remain unverified until tested.</p>
        <details className="workflow-source-picker"><summary>Reference prompts <span>{corpus.length} available</span></summary>
          <input aria-label="Search reference prompts" type="search" value={sourceSearch} onChange={(event) => setSourceSearch(event.target.value)} placeholder="Search names or claimed models" />
          <div className="workflow-choice-list">{filteredCorpus.map((item) => <label className="workflow-choice" key={item.id}>
            <input type="checkbox" checked={seedIds.includes(item.id)} disabled={!seedIds.includes(item.id) && seedIds.length >= 20} onChange={() => setSeedIds(toggle(seedIds, item.id))} />
            <span><b>{item.name}</b><small>{item.chars.toLocaleString()} characters · {item.verification || "unverified"}</small>{item.claimed_models.length > 0 && <small>Claimed models: {item.claimed_models.join(", ")}</small>}</span>
          </label>)}{filteredCorpus.length === 0 && <p className="workflow-caption">No matching reference prompts. Import submissions in Prompt library.</p>}</div>
        </details>
        {options.techniques.length > 0 && <details className="workflow-source-picker"><summary>Technique guidance <span>{techniqueIds.length} selected</span></summary><p className="workflow-caption">These selections guide the attacker. Choose the transform chain below to actually alter messages sent to the target.</p><div className="workflow-choice-list">
          {options.techniques.map((item) => <label className="workflow-choice" key={item.id}><input type="checkbox" checked={techniqueIds.includes(item.id)} onChange={() => setTechniqueIds(toggle(techniqueIds, item.id))} /><span><b>{item.name}</b><small>{item.description}</small></span></label>)}
        </div></details>}
        {transforms.length > 0 && <details className="workflow-source-picker"><summary>Message transform chain <span>{transformChain.length} / 3</span></summary>
          <p className="workflow-caption">Transforms run in selection order on each outgoing message. Exact text, escaped text, and hashes are recorded in the evidence.</p>
          {transformChain.length > 0 && <div className="workflow-transform-order">{transformChain.map((name, index) => <span key={name}>{index + 1}. {name}</span>)}<button type="button" className="mini-btn" onClick={() => setTransformChain([])}>Clear chain</button></div>}
          <div className="workflow-choice-list">{transforms.map((item) => {
            const name = item.id.slice("transform:".length);
            return <label className="workflow-choice" key={item.id}><input type="checkbox" checked={transformChain.includes(name)} disabled={!transformChain.includes(name) && transformChain.length >= 3} onChange={() => setTransformChain(toggle(transformChain, name))} /><span><b>{transformChain.includes(name) ? `${transformChain.indexOf(name) + 1}. ` : ""}{item.name}</b><small>{item.description}</small></span></label>;
          })}</div>
        </details>}
        {strategyMode === "single" ? <details className="workflow-source-picker" open={candidate ? true : undefined}><summary>Initial candidate <span>optional</span></summary>
          <p className="workflow-caption">Leave empty for the attacker to compose. Without an attacker, the baseline is the request itself. Include exactly one <code>{"{request}"}</code> placeholder where each evaluation request belongs.</p>
          <textarea aria-label="Initial candidate prompt" rows={7} value={candidate} onChange={(event) => setCandidate(event.target.value)} placeholder="Optional reusable prompt template containing {request}" />
        </details> : <details className="workflow-source-picker" open={turnPlan ? true : undefined}><summary>Explicit stage plan <span>optional</span></summary>
          <p className="workflow-caption">For a repeatable conversation, enter one message template per line. Use <code>{"{request}"}</code> to insert the case request. An explicit plan can run without an attacker; the turn limit still applies.</p>
          <textarea aria-label="Explicit conversation stage plan" rows={6} value={turnPlan} onChange={(event) => setTurnPlan(event.target.value)} placeholder={"Briefly describe your general capabilities.\nRespond to this evaluation request: {request}"} />
          {lines(turnPlan).length > maxTurns && <p className="workflow-caption workflow-plan-warning">The plan has {lines(turnPlan).length} stages. Increase the turn limit or shorten the plan.</p>}
        </details>}
        <div className="workflow-section-heading"><span className="workflow-step">03</span><h2>Evaluation requests</h2><span className="workflow-count">{testCount} tests</span></div>
        <label htmlFor="workflow-suite">Test suite<select id="workflow-suite" value={suite} onChange={(event) => setSuite(event.target.value)}>
          {options.suites.map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.name}{item.id === "custom" ? "" : ` · ${item.count} tests`}{item.available ? "" : " · not cached"}</option>)}
        </select></label>
        {selectedSuite && <p className="workflow-caption">{selectedSuite.description}</p>}
        <label htmlFor="workflow-custom">Custom evaluation requests <span className="workflow-optional">one per line</span><textarea id="workflow-custom" rows={4} value={customQuestions} onChange={(event) => setCustomQuestions(event.target.value)} placeholder="Add requests to evaluate alongside the suite" /></label>
        <label htmlFor="workflow-target-request">Custom target request <span className="workflow-optional">optional · one complete test</span><textarea id="workflow-target-request" rows={5} maxLength={12000} value={customTargetRequest} onChange={(event) => setCustomTargetRequest(event.target.value)} placeholder="Paste a complete request, including paragraphs or code blocks" /></label>
        <p className="workflow-caption">The custom target request is preserved as one test, including its line breaks.</p>
        <details className="workflow-source-picker workflow-limits"><summary>Run limits <span>{maxRounds} rounds · {maxCalls} model calls</span></summary>
          <div className="workflow-number-grid"><label>Maximum rounds<input type="number" min={1} max={20} required value={maxRounds} onChange={(event) => setMaxRounds(Number(event.target.value))} /></label>
            <label>Model call budget<input type="number" min={1} max={500} required value={maxCalls} onChange={(event) => setMaxCalls(Number(event.target.value))} /></label>
            <label>Trials per request<input type="number" min={1} max={5} required value={trials} onChange={(event) => setTrials(Number(event.target.value))} /></label>
            <label>Max output tokens<input type="number" min={32} max={16000} required value={maxTokens} onChange={(event) => setMaxTokens(Number(event.target.value))} /></label></div>
          {targetMode === "api" && strategyMode === "single" && <label>Candidate delivery<select value={delivery} onChange={(event) => setDelivery(event.target.value as "user" | "system")}><option value="user">User message</option><option value="system">System message experiment</option></select></label>}
          <label className="workflow-check"><input type="checkbox" checked={autoIterate} onChange={(event) => setAutoIterate(event.target.checked)} /><span>Automatically refine between assessed rounds, within these limits</span></label>
          <p className="workflow-caption">Calls include composition, target responses, and evaluation. Manual web responses do not consume model calls.</p>
        </details>
        <button type="submit" className="primary-command workflow-start" disabled={busy || testCount === 0 || (strategyMode !== "single" && lines(turnPlan).length > maxTurns)}>{busy ? "Working…" : "Create & start evaluation"}</button>
        <p className="workflow-caption workflow-scope-note">Results measure the selected tests and trials. They do not establish a universal jailbreak.</p>
      </form>
      <div className="workflow-evaluation">{run ? <>
        <section className="card workflow-run-summary">
          <div className="workflow-card-heading"><div><span className="workflow-eyebrow">{run.target_mode === "relay" ? "WEB / MANUAL RELAY" : "API EVALUATION"}</span><h2>{run.target_name || "Target evaluation"}</h2></div><span className={`workflow-status workflow-status-${run.status === "completed" && !allFulfilled ? "round_complete" : run.status}`}>{run.status === "completed" && allFulfilled ? "Selected tests fulfilled" : STATUS[run.status]}</span></div>
          <p>{run.status_detail}</p><p className="workflow-caption">{MODES[runMode].name}{runMode === "single" ? "" : ` · Up to ${run.settings.max_turns || 4} turns per case`}{!!run.settings.transform_chain?.length && ` · Transforms: ${run.settings.transform_chain.join(" → ")}`}</p>
          {run.error && <div className="err" role="alert">{run.error}</div>}
          <div className="workflow-metrics"><div><b>{run.coverage.completed}<small> / {run.coverage.total}</small></b><span>Cases complete</span></div><div><b>{run.coverage.pass_count}<small> / {run.coverage.total}</small></b><span>Assessed as fulfilled</span></div><div><b>{run.round}<small> / {run.settings.max_rounds}</small></b><span>Round</span></div><div><b>{run.model_calls}<small> / {run.settings.max_calls}</small></b><span>Model calls</span></div></div>
          <progress aria-label="Completed case progress" value={run.coverage.completed} max={Math.max(1, run.coverage.total)} />
          <div className="workflow-run-actions">
            {run.status === "ready" && <button type="button" className="primary-command" disabled={busy} onClick={() => void perform(() => workflowApi.start(run.id))}>Start evaluation</button>}
            {["stopped", "error"].includes(run.status) && <button type="button" className="primary-command" disabled={busy} onClick={() => void perform(() => workflowApi.continue(run.id))}>Resume evaluation</button>}
            {["running", "awaiting_relay"].includes(run.status) && <button type="button" className="mini-btn workflow-stop" disabled={busy} onClick={() => void perform(() => workflowApi.stop(run.id))}>Stop evaluation</button>}
            {canContinue && <button type="button" className="primary-command" disabled={busy} onClick={() => void perform(() => workflowApi.continue(run.id))}>Continue evaluation</button>}
            <button type="button" className="mini-btn" disabled={busy} onClick={() => void perform(() => workflowApi.get(run.id))}>Refresh</button>
            <button type="button" className="mini-btn" disabled={busy} onClick={() => void exportRun()}>Export JSON</button>
          </div>
          {run.coverage.unverified > 0 && <p className="workflow-caption">{run.coverage.unverified} response{run.coverage.unverified === 1 ? " needs" : "s need"} assessment. Review the response evidence below before continuing.</p>}
          {run.status === "completed" && allFulfilled && <p className="workflow-completion">{runMode === "single" ? "This candidate" : "This conversation strategy"} fulfilled all selected tests and trials in the recorded assessments. Performance on other requests or future model versions is unknown.</p>}
        </section>
        {runMode === "single" ? <section className="card workflow-candidate"><div className="workflow-card-heading"><div><span className="workflow-eyebrow">SINGLE REUSABLE CANDIDATE</span><h2>Round {run.round} prompt</h2></div><button type="button" className="mini-btn" disabled={!run.candidate_prompt} onClick={() => void copy(run.candidate_prompt, "Candidate prompt")}>Copy candidate</button></div>
          <textarea aria-label="Current reusable candidate prompt" readOnly rows={Math.min(18, Math.max(8, run.candidate_prompt.split("\n").length))} value={run.candidate_prompt} placeholder="The candidate will appear here when composition finishes." />
          <div className="workflow-candidate-foot"><span className="workflow-caption">The same candidate is applied to every request in this round.</span><button type="button" className="mini-btn" disabled={!run.candidate_prompt || busy} onClick={() => { setCandidate(run.candidate_prompt); newEvaluation(); setNotice("Candidate copied into the new evaluation setup."); }}>Use in new evaluation</button></div>
        </section> : <section className="card workflow-conversation-summary"><div className="workflow-card-heading"><div><span className="workflow-eyebrow">CASE-SPECIFIC CONVERSATIONS</span><h2>{MODES[runMode].name}</h2></div></div><p className="workflow-caption">{MODES[runMode].description} Each case and trial has its own conversation; inspect the exact messages and target replies in the evidence below.</p>{!!run.settings.turn_plan?.length && <details className="workflow-payload-detail"><summary>Saved explicit stage plan</summary><pre className="workflow-response">{run.settings.turn_plan.map((stage, index) => `${index + 1}. ${stage}`).join("\n\n")}</pre></details>}</section>}
        {run.pending_relay && <section className="card workflow-relay"><div className="workflow-card-heading"><div><span className="workflow-eyebrow">YOUR TURN</span><h2>Relay a web response</h2></div><span className="pill">Trial {run.pending_relay.trial} · Turn {run.pending_relay.turn || 1} / {runMode === "single" ? 1 : run.settings.max_turns || 4}</span></div>
          <p>{run.pending_relay.continue_chat ? `Continue the SAME conversation with ${run.target_name || "the target"}. Send only the current message below, then paste the complete response.` : `Start a fresh conversation with ${run.target_name || "the target"}. Send the current message below, then paste the complete response.`}</p>
          {run.pending_relay.conversation_id && <p className="workflow-caption workflow-hash">Conversation ID: {run.pending_relay.conversation_id}. Start a fresh chat whenever this ID changes.</p>}
          <div className="workflow-run-actions"><button type="button" className="primary-command" onClick={() => void copy(run.pending_relay!.payload, "Web payload")}>Copy web payload</button>{relayUrl && <a className="mini-btn" href={relayUrl} target="_blank" rel="noopener noreferrer">Open target</a>}</div>
          <label>Current message to send<textarea readOnly aria-label="Pending web payload" rows={7} value={run.pending_relay.payload} /></label>
          <details className="workflow-payload-detail"><summary>Escaped current message</summary><pre className="workflow-response">{escapedText(run.pending_relay.payload)}</pre></details>
          {relayHistory.length > 0 && <details className="workflow-payload-detail workflow-relay-history"><summary>Recorded conversation history · {relayHistory.length} turns</summary><p className="workflow-caption">For reference only. Copy web payload copies the current message, without replaying this history.</p>{relayHistory.map((turn, index) => <TurnEvidence key={`${turn.index}-${index}`} turn={turn} />)}</details>}
          <label htmlFor="workflow-relay-response">Paste target response<textarea id="workflow-relay-response" rows={7} value={relayResponse} onChange={(event) => setRelayResponse(event.target.value)} placeholder="Paste the full response, including any refusal or partial answer" /></label>
          <div className="workflow-review-fields"><label htmlFor="workflow-relay-label">{runMode === "single" ? "Operator assessment" : "Response observation"}<select id="workflow-relay-label" value={relayLabel} onChange={(event) => setRelayLabel(event.target.value as Assessment)}><option value="UNVERIFIED">Use evaluator / leave unassessed</option><option value="COMPLIED">Fulfilled</option><option value="PARTIAL">Partially fulfilled</option><option value="REFUSED">Refused</option></select></label><label htmlFor="workflow-relay-reason">Assessment reason<input id="workflow-relay-reason" value={relayReason} onChange={(event) => setRelayReason(event.target.value)} placeholder="Optional evidence" /></label></div>
          {runMode !== "single" && <p className="workflow-caption">This records an observation for the current turn. Completed case counts and assessments are determined by the evaluation run.</p>}
          <button type="button" className="primary-command" disabled={busy || run.status !== "awaiting_relay" || !relayResponse.trim()} onClick={() => void perform(() => workflowApi.relay(run.id, { request_id: run.pending_relay!.request_id, response: relayResponse, label: relayLabel, reason: relayReason }))}>Submit web response</button>
          {run.status !== "awaiting_relay" && <p className="workflow-caption">Resume the evaluation before submitting this saved relay request.</p>}
        </section>}
        <section className="card workflow-results"><div className="workflow-card-heading"><h2>Round {run.round} evidence</h2><span className="workflow-count">{run.coverage.assessed} assessed · {run.coverage.unverified} unassessed</span></div>
          <p className="workflow-caption">Fulfilled means a completed case addressed the evaluation request according to its recorded assessment. Interim turns are shown as observations and do not count as case results.</p>
          {run.results.length > 0 ? run.results.map((result) => <ResultCard key={result.id} result={result} disabled={busy || run.status === "running"} onAssess={assess} />) : <div className="workflow-empty-results">Responses will appear here as tests finish.</div>}
        </section>
        {run.history.some((item) => item.round !== run.round) && <section className="card workflow-history"><h2>{runMode === "single" ? "Previous candidates" : "Previous rounds"}</h2>{run.history.filter((item) => item.round !== run.round).map((item) => <details key={item.round}><summary>Round {item.round}<span>{item.results.filter((result) => result.complete !== false && result.label === "COMPLIED").length} / {item.results.filter((result) => result.complete !== false).length} completed cases fulfilled</span></summary>{runMode === "single" && <><p className="workflow-caption workflow-hash">SHA-256 {item.sha256}</p><pre className="workflow-response">{item.prompt}</pre></>}{runMode !== "single" && item.results.map((result) => <ResultCard key={result.id} result={result} disabled onAssess={assess} />)}</details>)}</section>}
      </> : <section className="card workflow-empty"><span className="workflow-eyebrow">FROM STRATEGY TO EVIDENCE</span><h2>A focused testing loop</h2><p>Choose a reusable prompt or a conversation strategy. Combine your prompt library, sourced techniques, and restricted attacker tools to evaluate your chosen requests.</p><ol><li><b>Configure</b><span>Select references, transforms, and a strategy or explicit conversation plan.</span></li><li><b>Evaluate</b><span>Collect target replies by API or manual web relay. Conversation modes preserve each case's chat history.</span></li><li><b>Assess and refine</b><span>Review exact messages and tool traces, then refine within your turn, round, and call budgets.</span></li></ol><div className="workflow-evidence-note">Success is measured on the tests you select. Keep additional requests for independent validation and repeat trials to check consistency.</div><div className="workflow-empty-bottom"><span>API targets and web sessions</span><span>Case transcripts and full JSON evidence</span><span>Evaluator or operator assessments</span></div></section>}</div>
    </div>}
  </div>;
}
