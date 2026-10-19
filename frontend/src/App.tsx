import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { data, selection } from "./adapters";
import type { Proposal, View } from "./types";
import { Investigation } from "./Investigation";
import { canUseCognito, hasToken, signIn, signOut } from "./auth";
import { Workspace, useActor } from "./Workspace";
import { money } from "./format";

const short = (id: string) => `${id.slice(0, 8)}…${id.slice(-4)}`;

function ContextBar({
  batch,
  asOf,
  synthetic = false,
}: {
  batch?: string;
  asOf?: string;
  synthetic?: boolean;
}) {
  return (
    <div className="context-bar" aria-label="Data context">
      <span>
        <small>Batch</small>
        {batch || "—"}
      </span>
      <span>
        <small>As of · dataset local</small>
        {asOf?.replace("T", " ") || "—"}
      </span>
      {batch === "fixtures-v1" && <b className="badge authored">Authored</b>}
      {synthetic && <b className="badge synthetic">Synthetic scenario</b>}
    </div>
  );
}

function Queue({ onInvestigate }: { onInvestigate: (id: string) => void }) {
  const [cursor, setCursor] = useState("");
  const queue = useQuery({
    queryKey: ["queue", selection.batch, selection.as_of, cursor],
    queryFn: () => data.queue(cursor ? { cursor } : {}),
  });
  if (queue.isPending) return <Loading text="Loading authorized exceptions" />;
  if (queue.error) return <ErrorCard error={queue.error} />;
  const q = queue.data;
  return (
    <section>
      <header className="page-head">
        <div>
          <p className="eyebrow">Exception workspace</p>
          <h1>Late delivery queue</h1>
          <p>
            Evidence eligible for an internal investigation, prioritized for
            review.
          </p>
        </div>
        <div className="status-dot">Historical snapshot</div>
      </header>
      <ContextBar batch={q.batch_id} asOf={q.as_of} />
      <div className="metrics">
        <Metric
          value={q.aggregates.late_open_orders}
          label="Late open orders"
        />
        <Metric value={q.aggregates.distinct_sellers} label="Visible sellers" />
        <Metric
          value={q.aggregates.multi_seller_orders}
          label="Multi-seller orders"
        />
        <Metric
          value={money(q.aggregates.line_value_centavos)}
          label="Eligible line value"
        />
      </div>
      <div className="callout">
        <b>Prioritization heuristic</b>
        <span>{q.sort_note.replace("Prioritization heuristic: ", "")}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Order</th>
              <th>Days overdue</th>
              <th>Eligible line value</th>
              <th>Seller scope</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {q.items.map((item) => (
              <tr key={item.order_id}>
                <td>
                  <code>{short(item.order_id)}</code>
                  <small>{item.estimated_delivery_date} estimated</small>
                </td>
                <td>
                  <strong className="overdue">{item.days_overdue} days</strong>
                </td>
                <td>{money(item.line_value_centavos)}</td>
                <td>
                  {item.seller_ids.length} seller
                  {item.seller_ids.length === 1 ? "" : "s"}
                  {item.multi_seller && (
                    <span className="tag"> multi-seller</span>
                  )}
                </td>
                <td>
                  <button
                    className="arrow"
                    onClick={() => onInvestigate(item.order_id)}
                    aria-label={`Investigate ${item.order_id}`}
                  >
                    →
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!q.items.length && (
        <p className="empty">
          No late open orders are visible within your granted scope.
        </p>
      )}
      <div className="buttons">
        <button onClick={() => setCursor("")} disabled={!cursor}>
          First page
        </button>
        <button
          onClick={() => setCursor(q.next_cursor || "")}
          disabled={!q.next_cursor}
        >
          Next page
        </button>
      </div>
    </section>
  );
}

function Review() {
  const qc = useQueryClient();
  const actor = useActor();
  const proposals = useQuery({
    queryKey: ["proposals", selection.batch, selection.as_of],
    queryFn: data.proposals,
  });
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (p: Proposal, decision: "approve" | "reject") => {
    if (!data.decide) return;
    setBusy(true);
    setError("");
    try {
      await data.decide(p, decision, reason);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      await qc.invalidateQueries({ queryKey: ["proposals"] });
      setBusy(false);
    }
  };
  if (proposals.isPending)
    return <Loading text="Loading authorized proposals" />;
  if (proposals.error) return <ErrorCard error={proposals.error} />;
  const p =
    proposals.data.find((item) => item.proposal_id === selectedId) ||
    proposals.data[0];
  const canReview =
    data.mode !== "live" ||
    (actor.data?.role === "reviewer" && actor.data.subject !== p?.created_by);
  return (
    <section>
      <header className="page-head">
        <div>
          <p className="eyebrow">Independent control</p>
          <h1>Action review</h1>
          <p>
            Review the evidence—not a claim of real-world cause—before an
            internal case is opened.
          </p>
        </div>
        <div className="status-dot">Revision controlled</div>
      </header>
      <ContextBar
        batch={p?.payload.batch_id || selection.batch}
        asOf={p?.payload.as_of || selection.as_of}
        synthetic={Boolean(p?.payload.uses_synthetic_evidence)}
      />
      {proposals.data.length > 0 && (
        <label>
          Proposal
          <select
            aria-label="Proposal"
            value={p?.proposal_id}
            onChange={(e) => setSelectedId(e.target.value)}
          >
            {proposals.data.map((item) => (
              <option key={item.proposal_id} value={item.proposal_id}>
                {item.kind} · {item.state} · revision {item.revision} ·{" "}
                {short(item.target_id)}
              </option>
            ))}
          </select>
        </label>
      )}
      {error && <p role="alert">{error} · Proposal state has been reloaded.</p>}
      {!p ? (
        <div className="empty">No proposals are visible in your scope.</div>
      ) : (
        <div className="review-grid">
          <article className="panel">
            <div className="panel-title">
              <span>Proposed internal action</span>
              <b className={`state ${p.state}`}>{p.state}</b>
            </div>
            <h2>{p.kind.replace(/([A-Z])/g, " $1").trim()}</h2>
            <dl>
              <div>
                <dt>Target</dt>
                <dd>
                  {p.target_type} · <code>{short(p.target_id)}</code>
                </dd>
              </div>
              <div>
                <dt>Owner</dt>
                <dd>{p.created_by}</dd>
              </div>
              <div>
                <dt>Revision</dt>
                <dd>{p.revision}</dd>
              </div>
              <div>
                <dt>Evidence hash</dt>
                <dd>
                  <code>{short(p.evidence_hash)}</code>
                </dd>
              </div>
            </dl>
          </article>
          <article className="panel">
            <div className="panel-title">
              <span>Evidence & unknowns</span>
              <b>{p.payload.selected_order_ids?.length || 0} orders</b>
            </div>
            {p.payload.findings?.map((f: any, i: number) => (
              <p key={i} className="finding">
                {f.text}
              </p>
            ))}
            <h3>Unresolved</h3>
            {p.payload.unresolved_questions?.map((u: string) => (
              <p key={u} className="unknown">
                {u}
              </p>
            ))}
          </article>
          <article className="panel decision">
            <div className="panel-title">
              <span>Decision</span>
              <b>Independent reviewer required</b>
            </div>
            {data.mode !== "live" && (
              <p className="simulation-label">
                Simulation only · no case or external action is created
              </p>
            )}
            {!canReview && (
              <p>
                Only an independent reviewer with scope over every target can
                decide this proposal.
              </p>
            )}
            <label>
              Review note
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Record the reason for this decision"
              />
            </label>
            <div className="buttons">
              <button
                className="reject"
                disabled={
                  !canReview ||
                  busy ||
                  !["pending", "needs_review"].includes(p.state)
                }
                onClick={() => act(p, "reject")}
              >
                Reject
              </button>
              <button
                className="approve"
                disabled={!canReview || busy || p.state !== "pending"}
                onClick={() => act(p, "approve")}
              >
                Approve internal case
              </button>
            </div>
          </article>
        </div>
      )}
    </section>
  );
}

function Performance() {
  return (
    <section>
      <header className="page-head">
        <div>
          <p className="eyebrow">Measured evidence</p>
          <h1>Performance & decision</h1>
          <p>
            The candidate did not beat the deterministic workspace. The
            recommendation follows the evidence.
          </p>
        </div>
        <div className="status-dot warn">B0 recommended</div>
      </header>
      <ContextBar
        batch={selection.batch}
        asOf={selection.as_of}
        synthetic={Boolean(selection.scenario_id)}
      />
      <div className="verdict">
        <div>
          <span>Build decision</span>
          <h2>Ship the deterministic workspace</h2>
          <p>
            B0 achieved perfect task success on the frozen benchmark. AI
            assistance remains an unproven hypothesis for narrative evidence and
            analyst speed.
          </p>
        </div>
        <strong>
          0.581<small>best candidate task success</small>
        </strong>
      </div>
      <div className="metrics evidence">
        <Metric value="1.000" label="B0 task success" />
        <Metric value="1.000" label="Relationship precision" />
        <Metric value="≤ 0.530" label="Candidate recall" />
        <Metric value="591 ms" label="Deployed warm read p95" />
      </div>
      <div className="comparison">
        <h2>Comparator evidence</h2>
        <p>
          Run of record: October 18, 2026 · gold-v1 · 43 real-only and 60
          scenario items per cell. Evaluation ran locally against the full-data
          database with Bedrock in us-east-2. Graph replay contains authored
          fixtures only.
        </p>
        <div className="bars">
          <Bar label="B0 · deterministic" value={100} text="100.0%" />
          <Bar label="Candidate · Nova 2 Lite" value={58.1} text="58.1%" />
          <Bar
            label="Candidate · Nova Lite"
            value={46.7}
            text="46.7% scenario"
          />
        </div>
      </div>
      <div className="metrics evidence">
        <Metric
          value="$0.3997"
          label="Measured evaluation inference · list price"
        />
        <Metric value="$0.00035" label="Nova Lite inference per ready job" />
        <Metric value="$0.00206" label="Nova 2 Lite inference per ready job" />
        <Metric
          value="~$74.47/mo"
          label="Infrastructure estimate · other charges unknown"
        />
      </div>
      <article className="limitations">
        <h2>Grounding and control gates</h2>
        <p>
          Accepted unsupported causal claims: 0. Authorization and approval
          failures accepted: 0 in the measured suites. The candidate fails the
          zero-invented-ID gate and the recall gate. 68 of 404 model jobs failed
          strict output validation.
        </p>
        <p>
          Source: docs/results.md,
          docs/evidence/eval/20261018T1745-bedrock/report.json, and
          docs/evidence/latency/deployed-m5.json. Models are a within-family
          Nova generation comparison. Evaluation cost is not the live cloud
          bill.
        </p>
      </article>
      <div className="limitations">
        <h2>What remains unknown</h2>
        <ul>
          <li>
            Human investigation time is untested; no participants were recorded.
          </li>
          <li>
            The frozen benchmark is deterministic by construction and cannot
            show an AI advantage.
          </li>
          <li>
            One run per cell carries sampling noise; no statistical test was
            run.
          </li>
          <li>
            Infrastructure cost is an estimate; billing data was still lagging.
          </li>
        </ul>
      </div>
    </section>
  );
}

function Metric({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}
function Bar({
  label,
  value,
  text,
}: {
  label: string;
  value: number;
  text: string;
}) {
  return (
    <div className="bar-row">
      <span>{label}</span>
      <div>
        <i style={{ width: `${value}%` }} />
      </div>
      <b>{text}</b>
    </div>
  );
}
function Loading({ text }: { text: string }) {
  return (
    <div className="loading">
      <i />
      {text}
    </div>
  );
}
function ErrorCard({ error }: { error: Error }) {
  return (
    <div className="error">
      <b>Unable to load this view</b>
      <span>{error.message}</span>
      {data.mode === "live" && (
        <small>
          Sign in again if your session expired. Local development accepts a
          session token on the sign-in screen.
        </small>
      )}
    </div>
  );
}

export function App({ initialAuthError = "" }: { initialAuthError?: string }) {
  const [view, setView] = useState<View>("queue");
  const [order, setOrder] = useState("");
  const [authError, setAuthError] = useState(initialAuthError);
  const nav = useMemo(
    () =>
      [
        { id: "queue", label: "Exception queue", n: "01" },
        { id: "investigation", label: "Investigation", n: "02" },
        { id: "review", label: "Action review", n: "03" },
        { id: "performance", label: "Evidence", n: "04" },
      ] as { id: View; label: string; n: string }[],
    [],
  );
  const investigate = (id: string) => {
    setOrder(id);
    setView("investigation");
  };
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <span>R</span>
          <div>
            <b>Relay</b>
            <small>Operational evidence</small>
          </div>
        </div>
        <nav>
          {nav.map((x) => (
            <button
              key={x.id}
              className={view === x.id ? "active" : ""}
              onClick={() => setView(x.id)}
            >
              <small>{x.n}</small>
              {x.label}
            </button>
          ))}
        </nav>
        <div className="mode">
          <small>Adapter</small>
          <b>
            {data.mode === "live"
              ? "Live authorized API"
              : data.mode === "evidence"
                ? "Measured evidence replay"
                : "Dummy sandbox"}
          </b>
          {data.mode !== "live" && <span>Simulation · zero API calls</span>}
          {data.mode === "live" && canUseCognito() && (
            <button
              className="auth-button"
              onClick={() =>
                hasToken()
                  ? signOut()
                  : signIn().catch((e: Error) => setAuthError(e.message))
              }
            >
              {hasToken() ? "Sign out" : "Sign in with Cognito"}
            </button>
          )}
        </div>
      </aside>
      <main>
        {authError && (
          <div className="error auth-error">
            <b>Authentication failed</b>
            <span>{authError}</span>
          </div>
        )}
        <Workspace>
          {view === "queue" && <Queue onInvestigate={investigate} />}
          {view === "investigation" && (
            <Investigation initialOrder={order} ContextBar={ContextBar} />
          )}
          {view === "review" && <Review />}
          {view === "performance" && <Performance />}
        </Workspace>
      </main>
    </div>
  );
}
