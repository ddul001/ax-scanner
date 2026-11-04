export type Status = "pass" | "warn" | "fail" | "na" | "skipped";

export interface CheckResult {
  check_id: string;
  layer: string;
  severity: string;
  method: string;
  status: Status;
  summary: string;
  pages: string[];
  found: string[];
  missing: string[];
  snippet: string;
  details: Record<string, any>;
  not_adopted: boolean;
}
export interface LayerScore {
  layer: string;
  weight: number;
  score: number | null;
  checks: number;
  applicable: number;
}
export interface AgentView {
  url: string;
  http_status: number;
  title: string;
  error: string | null;
  blockers: string[];
  text: string;
  links: { i: number; text: string; url: string }[];
  external_links_omitted: number;
  forms: { method: string; fields: { name: string; label: string; type: string; required: boolean }[] }[];
  structured_data: Record<string, unknown>[];
}
export interface JourneyStep {
  idx: number;
  action: string;
  thought: string;
  target: string;
  url: string;
  status: number;
  title: string;
  seen: string;
  blockers: string[];
  error: string | null;
  ms: number;
  view?: AgentView | null;
  reasoning_tokens?: number | null;
}
export interface JourneyRun {
  task_id: string;
  goal: string;
  stop_reason: string;
  steps: JourneyStep[];
  answer: Record<string, unknown> | null;
  path: string[];
  duration_ms: number;
  llm_calls: number;
}
export interface DiscoveryRow {
  role: string;
  label: string;
  url: string | null;
  state: "found" | "rejected" | "external" | "not_found" | "unreadable";
  source: "llm" | "rules" | "both" | "none";
  how: string;
  reason: string | null;
  rules_url: string | null;
  http_status: number | null;
  read: boolean;
  used_by: string[];
}
export interface Discovery {
  mode: "llm_first" | "rules_only";
  roles: DiscoveryRow[];
  items: {
    role: string;
    label: string;
    source: string;
    fallback: string | null;
    how: string;
    urls: { url: string; http_status: number; read: boolean; used_by: string[] }[];
  };
  pages: { role: string; url: string; http_status: number; read: boolean; ms: number }[];
  sources: { sitemap_urls: number; robots_txt: boolean; pages_read: number };
  summary: {
    categories: number;
    found: number;
    by_llm: number;
    by_rules: number;
    rejected: number;
    external: number;
    not_found: number;
  };
}
export interface Report {
  site_type: string;
  readiness: number;
  ax_score: number;
  grade: string;
  grade_before_gate: string;
  gate_applied: boolean;
  gate_checks: string[];
  layers: LayerScore[];
  results: CheckResult[];
  scoring_version?: string;
  coverage: {
    total: number;
    scored: number;
    skipped: string[];
    na: string[];
    partial: boolean;
    robots?: { ignored: boolean; disallowed_for_scanner: boolean };
    discovery?: Discovery;
    ai?: { provider: string; model: string; used_for: string[] };
  };
  version: string;
}
export interface RobotsAgent {
  agent: string;
  label: string;
  kind: "user_facing" | "training";
  allowed: boolean;
}
export interface PartialReport {
  partial: true;
  reason: string;
  message: string;
  not_evaluated: string;
  robots: {
    origin: string;
    agents: RobotsAgent[];
    scanner: { agent: string; allowed: boolean };
    unlisted_agents_allowed: boolean;
    verdict: {
      status: Status;
      summary: string;
      blocked_user_facing: string[];
      blocked_training: string[];
    };
  };
}
export const isPartial = (r: Report | PartialReport | null | undefined): r is PartialReport =>
  !!r && (r as PartialReport).partial === true;
export interface Classification {
  type: string;
  confidence: number;
  needs_confirmation: boolean;
  alternatives: { type: string; probability: number }[];
}
export interface Scan {
  id: number;
  status: "queued" | "classifying" | "needs_confirmation" | "classified" | "scanning" | "completed" | "failed";
  site: { domain: string; origin: string; type: string | null };
  classification: Classification | null;
  score: { ax_score: number; readiness: number; grade: string } | null;
  report: Report | PartialReport | null;
  ignore_robots?: boolean;
  fixes_count?: number;
  expected_pages?: { role: string; label: string }[];
  error: { code: string; message: string } | null;
  created_at: string;
}
export interface Fix {
  id: number;
  scan_id: number;
  check_id: string;
  type: "jsonld" | "llms_txt" | "robots_txt";
  title: string;
  target_url: string;
  status: "proposed" | "approved" | "exported" | "rejected";
  est_gain: number;
  content: string;
  placement: string;
  assumptions: string[];
  todo: string[];
  errors: string[];
  filename?: string;
}
export interface ScanSummary {
  id: number;
  status: Scan["status"];
  domain: string;
  type: string | null;
  ax_score: number | null;
  grade: string | null;
  gate_applied: boolean;
  checks: { pass: number; warn: number; fail: number } | null;
  fixes_count: number;
  error: { code: string; message: string } | null;
  created_at: string;
  partial?: boolean;
}
export interface LeaderboardEntry {
  rank: number;
  scan_id: number;
  domain: string;
  type: string | null;
  ax_score: number;
  grade: string;
  gate_applied: boolean;
  weakest_layer: string | null;
  weakest_score: number | null;
  scanned_at: string;
  scoring_version: string | null;
  outdated: boolean;
}
export interface ExportFile {
  path: string;
  content_type: string;
  content: string;
}

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); }
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { "Content-Type": "application/json" } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const err = body?.error ?? body?.detail ?? {};
    throw new ApiError(err.code ?? "ERROR", err.message ?? `Request failed (${response.status})`, response.status);
  }
  return body as T;
}

export const api = {
  createScan: (url: string, force = false, ignoreRobots = false) =>
    req<{ scan_id: number }>("/api/scans", { method: "POST", body: JSON.stringify({ url, force, ignore_robots: ignoreRobots }) }),
  health: () => req<{ ok: boolean; llm_configured: boolean; llm_model?: string; ignore_robots_allowed?: boolean }>("/health"),
  listScans: (limit = 100) => req<{ scans: ScanSummary[] }>(`/api/scans?limit=${limit}`),
  leaderboard: () => req<{ entries: LeaderboardEntry[]; current_version: string }>("/api/leaderboard"),
  getScan: (id: number) => req<Scan>(`/api/scans/${id}`),
  confirm: (id: number, type: string) => req<Scan>(`/api/scans/${id}/confirm`, { method: "POST", body: JSON.stringify({ type }) }),
  fixes: (id: number) => req<{ fixes: Fix[]; total_est_gain: number }>(`/api/scans/${id}/fixes`),
  approve: (id: number) => req<Fix>(`/api/fixes/${id}/approve`, { method: "POST" }),
  reject: (id: number) => req<Fix>(`/api/fixes/${id}/reject`, { method: "POST" }),
  fixPrompt: (id: number) => req<{ prompt: string; source: "meta" | "template"; fixes: number }>(`/api/scans/${id}/fix-prompt`, { method: "POST" }),
  export: (id: number) => req<{ files: ExportFile[] }>(`/api/scans/${id}/export`),
};

export const LAYER_LABEL: Record<string, string> = {
  discovery: "Discovery",
  identity: "Identity",
  data: "Data",
  actions: "Actions",
  trust: "Trust",
  agent_ux: "Agent UX",
  protocol: "Protocol",
};
export const label = (layer: string) => LAYER_LABEL[layer] ?? layer;

/** "muse-spark-1.3" -> "Muse Spark 1.3" */
export const modelName = (id?: string) =>
  (id ? id.split(/[-_]/).map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ") : "Muse Spark");
