import { useEffect, useState } from "react";
import { api, type CorpusPrompt, type RoleAssignments } from "../api";
import { workflowApi, type Assessment, type WorkflowOptions, type WorkflowResult, type WorkflowRun } from "../workflowApi";
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
  return <details className="workflow-result" open={result.label === "UNVERIFIED" ? true : undefined}>
    <summary><span className={`workflow-assessment workflow-label-${result.label.toLowerCase()}`}>{LABELS[result.label as Assessment] || result.label}</span>
      <span className="workflow-result-question">{result.question}</span><small>Trial {result.trial}</small></summary>
    <div className="workflow-result-body">
      <p className="workflow-caption">Assessment source: {result.source || "unassessed"}{result.score === null ? "" : ` · Score: ${result.score}`}</p>
      {result.reason && <p>{result.reason}</p>}
      <label>Target response<pre className="workflow-response">{result.response || "No response recorded."}</pre></label>
      <details className="workflow-payload-detail"><summary>View exact test payload</summary><pre className="workflow-response">{result.payload}</pre></details>
      <div className="workflow-review-fields">
        <label>Operator assessment<select aria-label={`Assessment for trial ${result.trial}: ${result.question}`} value={label} onChange={(event) => setLabel(event.target.value as Assessment)} disabled={disabled}>
          {(Object.keys(LABELS) as Assessment[]).map((item) => <option key={item} value={item}>{LABELS[item]}</option>)}
        </select></label>
        <label>Assessment reason<input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Evidence in the response" disabled={disabled} /></label>
        <button type="button" className="mini-btn" disabled={disabled} onClick={() => void onAssess(result, label, reason)}>Save assessment</button>
      </div>
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
      candidate_prompt: candidate, delivery: targetMode === "relay" ? "user" : delivery,
      max_rounds: maxRounds, max_calls: maxCalls, trials, max_tokens: maxTokens, auto_iterate: autoIterate,
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
  const allFulfilled = !!run && run.coverage.total > 0 && run.coverage.pass_count === run.coverage.total;
  const relayUrl = run?.target_url && /^https?:\/\//i.test(run.target_url) ? run.target_url : null;

  return <div className="workflow-workspace">
    <div className="workflow-page-heading"><div><span className="workflow-eyebrow">REUSABLE PROMPT EVALUATION</span><h1>One candidate. Measured results.</h1>
      <p>Combine reference prompts and techniques, test a single candidate, and refine it against observed responses.</p></div>
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
          <div><span className="workflow-caption">Composes and refines the candidate</span>{roles?.attacker && options.configured_roles?.attacker !== false ? <RoleChooser role="attacker" value={roles.attacker} onSaved={refreshRoles} /> : <button type="button" className="mini-btn" onClick={onOpenConnections}>Connect attacker · optional</button>}</div>
          {targetMode === "api" && <div><span className="workflow-caption">Receives every test payload</span>{roles?.target && options.configured_roles?.target !== false ? <RoleChooser role="target" value={roles.target} onSaved={refreshRoles} /> : <button type="button" className="mini-btn" onClick={onOpenConnections}>Connect API target</button>}</div>}
          <div><span className="workflow-caption">Assesses responses, or review them yourself</span>{roles?.judge && options.configured_roles?.judge !== false ? <RoleChooser role="judge" value={roles.judge} onSaved={refreshRoles} /> : <button type="button" className="mini-btn" onClick={onOpenConnections}>Connect evaluator · optional</button>}</div>
        </div>
        {targetMode === "relay" && <p className="workflow-caption">Your browser session is the target. Use a fresh conversation for each test so results are comparable.</p>}
        <div className="workflow-section-heading"><span className="workflow-step">02</span><h2>Candidate sources</h2><span className="workflow-count">{seedIds.length} selected</span></div>
        <p className="workflow-caption">Choose up to 20 reference prompts for the attacker to combine. Submitted claims remain unverified until tested.</p>
        <details className="workflow-source-picker"><summary>Reference prompts <span>{corpus.length} available</span></summary>
          <input aria-label="Search reference prompts" type="search" value={sourceSearch} onChange={(event) => setSourceSearch(event.target.value)} placeholder="Search names or claimed models" />
          <div className="workflow-choice-list">{filteredCorpus.map((item) => <label className="workflow-choice" key={item.id}>
            <input type="checkbox" checked={seedIds.includes(item.id)} disabled={!seedIds.includes(item.id) && seedIds.length >= 20} onChange={() => setSeedIds(toggle(seedIds, item.id))} />
            <span><b>{item.name}</b><small>{item.chars.toLocaleString()} characters · {item.verification || "unverified"}</small>{item.claimed_models.length > 0 && <small>Claimed models: {item.claimed_models.join(", ")}</small>}</span>
          </label>)}{filteredCorpus.length === 0 && <p className="workflow-caption">No matching reference prompts. Import submissions in Prompt library.</p>}</div>
        </details>
        {options.techniques.length > 0 && <details className="workflow-source-picker"><summary>Techniques <span>{techniqueIds.length} selected</span></summary><div className="workflow-choice-list">
          {options.techniques.map((item) => <label className="workflow-choice" key={item.id}><input type="checkbox" checked={techniqueIds.includes(item.id)} onChange={() => setTechniqueIds(toggle(techniqueIds, item.id))} /><span><b>{item.name}</b><small>{item.description}</small></span></label>)}
        </div></details>}
        <details className="workflow-source-picker" open={candidate ? true : undefined}><summary>Initial candidate <span>optional</span></summary>
          <p className="workflow-caption">Leave empty for the attacker to compose. Without an attacker, the baseline is the request itself. Include exactly one <code>{"{request}"}</code> placeholder where each evaluation request belongs.</p>
          <textarea aria-label="Initial candidate prompt" rows={7} value={candidate} onChange={(event) => setCandidate(event.target.value)} placeholder="Optional reusable prompt template containing {request}" />
        </details>
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
          {targetMode === "api" && <label>Candidate delivery<select value={delivery} onChange={(event) => setDelivery(event.target.value as "user" | "system")}><option value="user">User message</option><option value="system">System message experiment</option></select></label>}
          <label className="workflow-check"><input type="checkbox" checked={autoIterate} onChange={(event) => setAutoIterate(event.target.checked)} /><span>Automatically refine between assessed rounds, within these limits</span></label>
          <p className="workflow-caption">Calls include composition, target responses, and evaluation. Manual web responses do not consume model calls.</p>
        </details>
        <button type="submit" className="primary-command workflow-start" disabled={busy || testCount === 0}>{busy ? "Working…" : "Create & start evaluation"}</button>
        <p className="workflow-caption workflow-scope-note">Results measure the selected tests and trials. They do not establish a universal jailbreak.</p>
      </form>
      <div className="workflow-evaluation">{run ? <>
        <section className="card workflow-run-summary">
          <div className="workflow-card-heading"><div><span className="workflow-eyebrow">{run.target_mode === "relay" ? "WEB / MANUAL RELAY" : "API EVALUATION"}</span><h2>{run.target_name || "Target evaluation"}</h2></div><span className={`workflow-status workflow-status-${run.status === "completed" && !allFulfilled ? "round_complete" : run.status}`}>{run.status === "completed" && allFulfilled ? "Selected tests fulfilled" : STATUS[run.status]}</span></div>
          <p>{run.status_detail}</p>
          {run.error && <div className="err" role="alert">{run.error}</div>}
          <div className="workflow-metrics"><div><b>{run.coverage.completed}<small> / {run.coverage.total}</small></b><span>Responses recorded</span></div><div><b>{run.coverage.pass_count}<small> / {run.coverage.total}</small></b><span>Assessed as fulfilled</span></div><div><b>{run.round}<small> / {run.settings.max_rounds}</small></b><span>Round</span></div><div><b>{run.model_calls}<small> / {run.settings.max_calls}</small></b><span>Model calls</span></div></div>
          <progress aria-label="Evaluation response progress" value={run.coverage.completed} max={Math.max(1, run.coverage.total)} />
          <div className="workflow-run-actions">
            {run.status === "ready" && <button type="button" className="primary-command" disabled={busy} onClick={() => void perform(() => workflowApi.start(run.id))}>Start evaluation</button>}
            {["stopped", "error"].includes(run.status) && <button type="button" className="primary-command" disabled={busy} onClick={() => void perform(() => workflowApi.continue(run.id))}>Resume evaluation</button>}
            {["running", "awaiting_relay"].includes(run.status) && <button type="button" className="mini-btn workflow-stop" disabled={busy} onClick={() => void perform(() => workflowApi.stop(run.id))}>Stop evaluation</button>}
            {canContinue && <button type="button" className="primary-command" disabled={busy} onClick={() => void perform(() => workflowApi.continue(run.id))}>Continue evaluation</button>}
            <button type="button" className="mini-btn" disabled={busy} onClick={() => void perform(() => workflowApi.get(run.id))}>Refresh</button>
            <button type="button" className="mini-btn" disabled={busy} onClick={() => void exportRun()}>Export JSON</button>
          </div>
          {run.coverage.unverified > 0 && <p className="workflow-caption">{run.coverage.unverified} response{run.coverage.unverified === 1 ? " needs" : "s need"} assessment. Review the response evidence below before continuing.</p>}
          {run.status === "completed" && allFulfilled && <p className="workflow-completion">This candidate fulfilled all selected tests and trials in the recorded assessments. Performance on other requests or future model versions is unknown.</p>}
        </section>
        <section className="card workflow-candidate"><div className="workflow-card-heading"><div><span className="workflow-eyebrow">SINGLE REUSABLE CANDIDATE</span><h2>Round {run.round} prompt</h2></div><button type="button" className="mini-btn" disabled={!run.candidate_prompt} onClick={() => void copy(run.candidate_prompt, "Candidate prompt")}>Copy candidate</button></div>
          <textarea aria-label="Current reusable candidate prompt" readOnly rows={Math.min(18, Math.max(8, run.candidate_prompt.split("\n").length))} value={run.candidate_prompt} placeholder="The candidate will appear here when composition finishes." />
          <div className="workflow-candidate-foot"><span className="workflow-caption">The same candidate is applied to every request in this round.</span><button type="button" className="mini-btn" disabled={!run.candidate_prompt || busy} onClick={() => { setCandidate(run.candidate_prompt); newEvaluation(); setNotice("Candidate copied into the new evaluation setup."); }}>Use in new evaluation</button></div>
        </section>
        {run.pending_relay && <section className="card workflow-relay"><div className="workflow-card-heading"><div><span className="workflow-eyebrow">YOUR TURN</span><h2>Relay a web response</h2></div><span className="pill">Trial {run.pending_relay.trial}</span></div>
          <p>Open a fresh conversation with {run.target_name || "the target"}, copy this exact payload, then paste the complete response below.</p>
          <div className="workflow-run-actions"><button type="button" className="primary-command" onClick={() => void copy(run.pending_relay!.payload, "Web payload")}>Copy web payload</button>{relayUrl && <a className="mini-btn" href={relayUrl} target="_blank" rel="noopener noreferrer">Open target</a>}</div>
          <label>Payload to send<textarea readOnly aria-label="Pending web payload" rows={7} value={run.pending_relay.payload} /></label>
          <label htmlFor="workflow-relay-response">Paste target response<textarea id="workflow-relay-response" rows={7} value={relayResponse} onChange={(event) => setRelayResponse(event.target.value)} placeholder="Paste the full response, including any refusal or partial answer" /></label>
          <div className="workflow-review-fields"><label htmlFor="workflow-relay-label">Operator assessment<select id="workflow-relay-label" value={relayLabel} onChange={(event) => setRelayLabel(event.target.value as Assessment)}><option value="UNVERIFIED">Use evaluator / leave unassessed</option><option value="COMPLIED">Fulfilled</option><option value="PARTIAL">Partially fulfilled</option><option value="REFUSED">Refused</option></select></label><label htmlFor="workflow-relay-reason">Assessment reason<input id="workflow-relay-reason" value={relayReason} onChange={(event) => setRelayReason(event.target.value)} placeholder="Optional evidence" /></label></div>
          <button type="button" className="primary-command" disabled={busy || run.status !== "awaiting_relay" || !relayResponse.trim()} onClick={() => void perform(() => workflowApi.relay(run.id, { request_id: run.pending_relay!.request_id, response: relayResponse, label: relayLabel, reason: relayReason }))}>Submit web response</button>
          {run.status !== "awaiting_relay" && <p className="workflow-caption">Resume the evaluation before submitting this saved relay request.</p>}
        </section>}
        <section className="card workflow-results"><div className="workflow-card-heading"><h2>Round {run.round} evidence</h2><span className="workflow-count">{run.coverage.assessed} assessed · {run.coverage.unverified} unassessed</span></div>
          <p className="workflow-caption">Fulfilled means the response addressed the evaluation request according to the recorded operator or evaluator assessment.</p>
          {run.results.length > 0 ? run.results.map((result) => <ResultCard key={result.id} result={result} disabled={busy || run.status === "running"} onAssess={assess} />) : <div className="workflow-empty-results">Responses will appear here as tests finish.</div>}
        </section>
        {run.history.some((item) => item.round !== run.round) && <section className="card workflow-history"><h2>Previous candidates</h2>{run.history.filter((item) => item.round !== run.round).map((item) => <details key={item.round}><summary>Round {item.round}<span>{item.results.filter((result) => result.label === "COMPLIED").length} / {item.results.length} fulfilled</span></summary><p className="workflow-caption workflow-hash">SHA-256 {item.sha256}</p><pre className="workflow-response">{item.prompt}</pre></details>)}</section>}
      </> : <section className="card workflow-empty"><span className="workflow-eyebrow">FROM CANDIDATE TO EVIDENCE</span><h2>A focused testing loop</h2><p>Start with your prompt library or a template you already use. The attacker creates one candidate and tests it across your chosen requests.</p><ol><li><b>Compose</b><span>Merge selected references and techniques into one reusable prompt.</span></li><li><b>Evaluate</b><span>Collect target responses by API or through a manual web relay.</span></li><li><b>Assess and refine</b><span>Review evidence, then adapt the candidate within your round and call budgets.</span></li></ol><div className="workflow-evidence-note">Success is measured on the tests you select. Keep additional requests for independent validation and repeat trials to check consistency.</div><div className="workflow-empty-bottom"><span>API targets and web sessions</span><span>Saved candidates and full JSON evidence</span><span>Evaluator or operator assessments</span></div></section>}</div>
    </div>}
  </div>;
}
