export type Assessment = "COMPLIED" | "PARTIAL" | "REFUSED" | "UNVERIFIED";
export type WorkflowStatus = "ready" | "running" | "awaiting_relay" | "awaiting_review" | "round_complete" | "completed" | "stopped" | "error";

export interface WorkflowOptions {
  configured_roles?: { attacker: boolean; target: boolean; judge: boolean };
  suites: { id: string; name: string; description: string; count: number; available: boolean }[];
  techniques: { id: string; name: string; description: string }[];
}

export interface WorkflowResult {
  id: string;
  round: number;
  test_id: string;
  trial: number;
  question: string;
  payload: string;
  response: string;
  label: Assessment | "ERROR" | "EMPTY";
  score: number | null;
  reason: string;
  source: string;
}

export interface WorkflowRun {
  id: string;
  status: WorkflowStatus;
  status_detail: string;
  target_mode: "api" | "relay";
  target_name: string;
  target_url: string;
  candidate_prompt: string;
  round: number;
  model_calls: number;
  created_at?: string;
  settings: { max_rounds: number; max_calls: number; trials: number; delivery: "user" | "system" };
  tests: { id: string; question: string; source: string }[];
  results: WorkflowResult[];
  pending_relay: null | { request_id: string; test_id: string; trial: number; question: string; payload: string; round: number };
  coverage: { completed: number; total: number; pass_count: number; assessed: number; unverified: number };
  history: { round: number; prompt: string; sha256: string; results: WorkflowResult[] }[];
  error?: string;
}

export interface WorkflowCreate {
  target_mode: "api" | "relay";
  target_name: string;
  target_url: string;
  suite_id: string;
  custom_questions: string[];
  seed_ids: string[];
  technique_ids: string[];
  candidate_prompt: string;
  delivery: "user" | "system";
  max_rounds: number;
  max_calls: number;
  trials: number;
  max_tokens: number;
  auto_iterate: boolean;
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/workflow${path}`, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = await response.json();
      message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
    } catch {
      message = message || `Request failed (${response.status})`;
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

const path = (id: string) => `/runs/${encodeURIComponent(id)}`;

export const workflowApi = {
  options: () => request<WorkflowOptions>("/options"),
  runs: () => request<WorkflowRun[]>("/runs"),
  create: (body: WorkflowCreate) => request<WorkflowRun>("/runs", body),
  get: (id: string) => request<WorkflowRun>(path(id)),
  start: (id: string) => request<WorkflowRun>(`${path(id)}/start`, {}),
  stop: (id: string) => request<WorkflowRun>(`${path(id)}/stop`, {}),
  continue: (id: string) => request<WorkflowRun>(`${path(id)}/continue`, {}),
  relay: (id: string, body: { request_id: string; response: string; label: Assessment; reason: string }) =>
    request<WorkflowRun>(`${path(id)}/relay`, body),
  assess: (id: string, body: { result_id: string; label: Assessment; reason: string }) =>
    request<WorkflowRun>(`${path(id)}/assess`, body),
  export: (id: string) => request<WorkflowRun>(`${path(id)}/export`),
};
