import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { data, selection, setSelection } from "./adapters";
import type { Selection } from "./types";
import { hasToken, localAuth } from "./auth";

export function Workspace({ children }: { children: ReactNode }) {
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: data.meta,
    enabled: data.mode !== "live" || hasToken(),
  });
  const [active, setActive] = useState<Selection | null>(null);
  const [draft, setDraft] = useState<Selection>({ ...selection });
  const [localToken, setLocalToken] = useState("");
  useEffect(() => {
    if (!active && meta.data?.batches.length) {
      const first = meta.data.batches[0];
      const value = {
        batch: first.batch_id,
        as_of: first.demo_as_of.replace(" ", "T"),
        scenario_id: "",
      };
      setSelection(value);
      setDraft(value);
      setActive(value);
    }
  }, [active, meta.data]);
  if (data.mode === "live" && !hasToken())
    return (
      <div className="panel">
        <h1>Sign in to your workspace</h1>
        <p>
          Use Cognito sign-in to load the evidence within your granted seller
          scope.
        </p>
        {localAuth() && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              sessionStorage.setItem("ops_local_token", localToken);
              window.location.reload();
            }}
          >
            <label>
              Local development token
              <input
                type="password"
                autoComplete="off"
                value={localToken}
                onChange={(e) => setLocalToken(e.target.value)}
                required
              />
            </label>
            <button>Use local session</button>
          </form>
        )}
      </div>
    );
  if (meta.error)
    return (
      <div className="error" role="alert">
        {meta.error.message}
      </div>
    );
  if (!meta.data || !active) return <p>Loading workspace context…</p>;
  return (
    <>
      <form
        className="workspace-controls"
        onSubmit={(e) => {
          e.preventDefault();
          setSelection(draft);
          setActive({ ...draft });
        }}
      >
        <label>
          Batch
          <select
            aria-label="Batch"
            value={draft.batch}
            disabled={data.mode !== "live"}
            onChange={(e) => {
              const b = meta.data.batches.find(
                (x) => x.batch_id === e.target.value,
              )!;
              setDraft({
                ...draft,
                batch: b.batch_id,
                as_of: b.demo_as_of.replace(" ", "T"),
              });
            }}
          >
            {meta.data.batches.map((b) => (
              <option key={b.batch_id}>{b.batch_id}</option>
            ))}
          </select>
        </label>
        <label>
          As of · dataset local
          <input
            aria-label="As of"
            type="datetime-local"
            step="1"
            value={draft.as_of}
            disabled={data.mode !== "live"}
            required
            onChange={(e) => setDraft({ ...draft, as_of: e.target.value })}
          />
        </label>
        <label>
          Context
          <select
            aria-label="Scenario"
            value={draft.scenario_id}
            onChange={(e) =>
              setDraft({ ...draft, scenario_id: e.target.value })
            }
          >
            <option value="">Commerce evidence only</option>
            {meta.data.scenarios.map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>
                Synthetic scenario · {s.scenario_id}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Apply context</button>
      </form>
      <div key={JSON.stringify(active)}>
        <ActorStatus />
        <div key={JSON.stringify(active)}>{children}</div>
      </div>
    </>
  );
}

export function useActor() {
  return useQuery({
    queryKey: ["me", selection.batch, selection.as_of],
    queryFn: data.me,
    staleTime: 0,
  });
}
function ActorStatus() {
  const actor = useActor();
  return (
    <div className="actor-status">
      {actor.data ? (
        <>
          <b>{actor.data.role || "Unprovisioned"}</b> ·{" "}
          {actor.data.granted_sellers} granted sellers ·{" "}
          {data.mode === "live"
            ? "Server authorization applies to every read and decision"
            : "Authored scope replay; all actions are simulations"}
        </>
      ) : actor.error ? (
        actor.error.message
      ) : (
        "Loading permissions…"
      )}
    </div>
  );
}
