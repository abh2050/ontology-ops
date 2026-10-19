import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { data, selection } from "./adapters";
import { useActor } from "./Workspace";

export function JobAction({ orderId }: { orderId: string }) {
  const actor = useActor(),
    qc = useQueryClient();
  const key = useRef(crypto.randomUUID());
  const [jobId, setJobId] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [proposed, setProposed] = useState(false);
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => data.job(jobId),
    enabled: Boolean(jobId),
    refetchInterval: (q) =>
      ["queued", "running", "validating"].includes(
        q.state.data?.state || "queued",
      )
        ? 2000
        : false,
  });
  const run = async () => {
    setBusy(true);
    setError("");
    try {
      setJobId((await data.submit(orderId, key.current)).job_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const propose = async () => {
    setBusy(true);
    setError("");
    try {
      await data.propose(jobId);
      setProposed(true);
      await qc.invalidateQueries({ queryKey: ["proposals"] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const state = job.data?.state;
  const validation = job.data?.result?.validation?.proposal_state;
  const allowed = actor.data?.role === "operator" || data.mode !== "live";
  return (
    <article className="panel job-panel">
      <div className="panel-title">
        <span>Assisted internal investigation</span>
        <b>{state || "Not submitted"}</b>
      </div>
      {data.mode !== "live" && (
        <p className="simulation-label">
          Hand-authored action simulation · no model calls or real cases
        </p>
      )}
      <p>
        Cause remains unknown. The output must pass evidence validation before
        it can become a reviewable proposal.
      </p>
      {selection.scenario_id && (
        <p className="badge synthetic">Synthetic scenario</p>
      )}
      {!jobId && (
        <button className="primary" disabled={!allowed || busy} onClick={run}>
          {busy
            ? "Submitting…"
            : data.mode === "live"
              ? "Generate proposal evidence"
              : "Simulate assisted investigation"}
        </button>
      )}
      {!allowed && <p>Only a provisioned operator may submit a job.</p>}
      {(error || job.error) && (
        <p role="alert">
          {error || job.error?.message} The request will not be retried
          automatically.
        </p>
      )}
      {job.data?.result?.analysis?.findings?.map((f: any, i: number) => (
        <p className="finding" key={i}>
          {f.text}
        </p>
      ))}
      {job.data?.result?.analysis?.unresolved_questions?.map((u: string) => (
        <p className="unknown" key={u}>
          {u}
        </p>
      ))}
      {state &&
        !["queued", "running", "validating", "ready"].includes(state) && (
          <p role="status">
            Job {state}:{" "}
            {job.data?.result?.reason || "No action can be proposed."}
          </p>
        )}
      {state === "ready" && (
        <button
          className="primary"
          disabled={
            busy ||
            proposed ||
            !["pending", "needs_review"].includes(validation || "")
          }
          onClick={propose}
        >
          {proposed
            ? "Proposal saved · open Action review"
            : "Save internal proposal for review"}
        </button>
      )}
    </article>
  );
}
