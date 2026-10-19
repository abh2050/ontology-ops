import {
  staticActor,
  staticGraph,
  staticProposals,
  staticQueue,
  snapshots,
  sellers,
} from "./staticData";
import type { AppData, AppMode, Job, Proposal, Selection } from "./types";

export const selection: Selection = { batch: "", as_of: "", scenario_id: "" };
export function setSelection(next: Selection) {
  Object.assign(selection, next);
  jobCache.clear();
}
const mode = (import.meta.env.VITE_APP_MODE || "live") as AppMode;
const jobCache = new Map<string, { etag: string; job: Job }>();
export const token = () =>
  sessionStorage.getItem("ops_access_token") ||
  sessionStorage.getItem("ops_local_token") ||
  "";
const headers = () => ({
  "Content-Type": "application/json",
  Authorization: `Bearer ${token()}`,
});
const path = (route: string, extra: Record<string, string> = {}) => {
  const params = new URLSearchParams({
    ...Object.fromEntries(
      Object.entries(selection).filter(([k, v]) => k !== "scenario_id" && v),
    ),
    ...extra,
  });
  return `/api/${route}?${params}`;
};
async function api<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { ...headers(), ...init.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      response.status === 401
        ? "Your session is missing or expired. Sign in to continue."
        : body.code || body.detail || `Request failed (${response.status}).`,
    );
  }
  return response.json() as Promise<T>;
}
const live: AppData = {
  mode: "live",
  meta: () => api("/api/meta"),
  me: () => api(path("me")),
  queue: (filters = {}) => api(path("queue", { limit: "25", ...filters })),
  graph: (id) =>
    api(
      path("graph", {
        root_type: "Order",
        root_id: id,
        ...(selection.scenario_id
          ? { scenario_id: selection.scenario_id }
          : {}),
      }),
    ),
  snapshot: (id) => api(path(`orders/${id}`)),
  seller: (id) => api(path(`sellers/${id}/scope`)),
  submit: (id, key) =>
    api(path("jobs"), {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({
        target_type: "Order",
        target_id: id,
        as_of: selection.as_of,
        scenario_id: selection.scenario_id || null,
        model_key: "default",
        comparator: "candidate",
      }),
    }),
  job: async (id) => {
    const old = jobCache.get(id);
    const response = await fetch(`/api/jobs/${id}`, {
      headers: { ...headers(), ...(old ? { "If-None-Match": old.etag } : {}) },
      cache: "no-store",
    });
    if (response.status === 304 && old) return old.job;
    if (!response.ok) throw new Error(`Job read failed (${response.status}).`);
    const job = (await response.json()) as Job;
    jobCache.set(id, { job, etag: response.headers.get("ETag") || "" });
    return job;
  },
  propose: (id) => api(path(`jobs/${id}/proposal`), { method: "POST" }),
  proposals: async () =>
    (await api<{ items: Proposal[] }>(path("proposals"))).items,
  decide: async (p, decision, reason) => {
    await api(path(`proposals/${p.proposal_id}/decision`), {
      method: "POST",
      body: JSON.stringify({ decision, expected_revision: p.revision, reason }),
    });
    return api(path(`proposals/${p.proposal_id}`));
  },
};
function simulation(selected: AppMode): AppData {
  let proposals = structuredClone(staticProposals);
  let lastOrder = staticQueue.items[0].order_id;
  return {
    mode: selected,
    meta: async () => ({
      batches: [
        {
          batch_id: "fixtures-v1",
          provenance: "authored",
          demo_as_of: staticQueue.as_of,
        },
      ],
      scenarios: [
        { scenario_id: "base-v1", description: "Seeded fictional context" },
      ],
    }),
    me: async () => ({
      ...staticActor,
      role: selected === "sandbox" ? "reviewer" : "operator",
    }),
    queue: async () => structuredClone(staticQueue),
    graph: async (id) => staticGraph(id, selection.scenario_id),
    snapshot: async (id) => structuredClone(snapshots[id]),
    seller: async (id) => structuredClone(sellers[id]),
    submit: async (id) => {
      lastOrder = id;
      return { job_id: "simulation-job" };
    },
    job: async () => ({
      job_id: "simulation-job",
      state: "ready",
      revision: 1,
      result: {
        analysis: {
          findings: [
            {
              text: "Hand-authored simulation: inspect this authorized late order.",
            },
          ],
          unresolved_questions: ["Cause remains unknown."],
        },
        validation: { proposal_state: "pending" },
      },
    }),
    propose: async () => {
      const p: Proposal = {
        proposal_id: crypto.randomUUID(),
        job_id: "simulation-job",
        created_by: "simulated_operator",
        kind: "CreateInvestigation",
        target_type: "Order",
        target_id: lastOrder,
        evidence_hash: snapshots[lastOrder].evidence_hash,
        state: "pending",
        revision: 1,
        reviewed_by: null,
        review_reason: null,
        created_at: new Date().toISOString(),
        payload: {
          batch_id: "fixtures-v1",
          as_of: staticQueue.as_of,
          scenario_id: selection.scenario_id || null,
          uses_synthetic_evidence: Boolean(selection.scenario_id),
          selected_order_ids: [lastOrder],
          unresolved_questions: ["Cause remains unknown."],
          findings: [
            { text: "Hand-authored action simulation; no model ran." },
          ],
        },
      };
      proposals = [p, ...proposals];
      return p;
    },
    proposals: async () => structuredClone(proposals),
    decide: async (p, decision, reason) => {
      const next = {
        ...p,
        state: decision === "approve" ? "executed" : "rejected",
        revision: p.revision + 1,
        review_reason: reason,
        reviewed_by: "simulated_reviewer",
      };
      proposals = proposals.map((old) =>
        old.proposal_id === p.proposal_id ? next : old,
      );
      return next;
    },
  };
}
export const data: AppData = mode === "live" ? live : simulation(mode);
