import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import cytoscape, { type Core } from "cytoscape";
import { data, selection } from "./adapters";
import { money } from "./format";
import { JobAction } from "./JobAction";
import type { GraphEdge, GraphNode } from "./types";

export function Investigation({
  initialOrder,
  ContextBar,
}: {
  initialOrder: string;
  ContextBar: React.ComponentType<{
    batch?: string;
    asOf?: string;
    synthetic?: boolean;
  }>;
}) {
  const orderId = initialOrder;
  const query = useQuery({
    queryKey: [
      "graph",
      selection.batch,
      selection.as_of,
      selection.scenario_id,
      orderId,
    ],
    queryFn: () => data.graph(orderId),
    enabled: Boolean(orderId),
  });
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [selected, setSelected] = useState<GraphNode | GraphEdge | null>(null);
  const sellerId =
    selected && "type" in selected && selected.type === "Seller"
      ? selected.id.slice(7)
      : "";
  const scope = useQuery({
    queryKey: ["seller", selection.batch, selection.as_of, sellerId],
    queryFn: () => data.seller(sellerId),
    enabled: Boolean(sellerId),
  });
  const snapshot = useQuery({
    queryKey: ["snapshot", selection.batch, selection.as_of, orderId],
    queryFn: () => data.snapshot(orderId),
    enabled: Boolean(orderId),
  });
  useEffect(() => {
    if (!host.current || !query.data) return;
    cy.current?.destroy();
    const g = query.data;
    cy.current = cytoscape({
      container: host.current,
      elements: [
        ...g.nodes.map((n) => ({ data: { ...n, id: n.id, label: n.label } })),
        ...g.edges.map((e) => ({
          data: {
            ...e,
            id: e.id,
            source: e.source,
            target: e.target,
            label: e.relationship,
          },
        })),
      ],
      layout: {
        name: "breadthfirst",
        directed: true,
        padding: 32,
        spacingFactor: 1.25,
      },
      style: [
        {
          selector: "node",
          style: {
            "background-color": "#132d46",
            label: "data(label)",
            color: "#e8f1f7",
            "font-size": 10,
            "text-valign": "center",
            width: 50,
            height: 50,
            "border-width": 3,
            "border-color": "#88a7b8",
          },
        },
        {
          selector: "node[type = 'Seller']",
          style: {
            shape: "diamond",
            "background-color": "#a84d32",
            width: 58,
            height: 58,
          },
        },
        {
          selector: "node[?is_synthetic]",
          style: { "border-color": "#d6ad60", "border-style": "dashed" },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#8ca0ad",
            "target-arrow-color": "#8ca0ad",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": 8,
            color: "#5f7481",
            "text-background-color": "#f5f1e8",
            "text-background-opacity": 1,
          },
        },
        {
          selector: ":selected",
          style: {
            "border-color": "#f0b45a",
            "line-color": "#f0b45a",
            "target-arrow-color": "#f0b45a",
          },
        },
      ],
    });
    cy.current.on("tap", "node", (e) =>
      setSelected(g.nodes.find((n) => n.id === e.target.id()) || null),
    );
    cy.current.on("tap", "edge", (e) =>
      setSelected(g.edges.find((x) => x.id === e.target.id()) || null),
    );
    return () => cy.current?.destroy();
  }, [query.data]);
  if (!orderId)
    return (
      <section>
        <h1>Connected investigation</h1>
        <ContextBar batch={selection.batch} asOf={selection.as_of} />
        <p>Select an authorized order from the exception queue.</p>
      </section>
    );
  if (query.isPending)
    return (
      <div className="loading">
        <i />
        Building authorized graph
      </div>
    );
  if (query.error)
    return (
      <div className="error">
        <b>Unable to load investigation</b>
        <span>{query.error.message}</span>
      </div>
    );
  const g = query.data;
  const edge = selected && "relationship" in selected ? selected : null;
  return (
    <section>
      <header className="page-head">
        <div>
          <p className="eyebrow">Connected investigation</p>
          <h1>
            Evidence around order <code>{orderId.slice(0, 8)}</code>
          </h1>
          <p>
            Typed relationships connect only the objects visible within the
            actor’s seller scope.
          </p>
        </div>
        <div className="status-dot">Cause remains unknown</div>
      </header>
      <ContextBar
        batch={g.batch_id}
        asOf={g.as_of}
        synthetic={Boolean(g.scenario_id)}
      />
      <div className="graph-layout">
        <article className="graph-panel">
          <div className="panel-title">
            <span>Relationship graph</span>
            <b>
              {g.nodes.length} / {g.max_nodes} display nodes
            </b>
          </div>
          <div
            ref={host}
            className="cy"
            aria-label="Connected evidence graph"
          />
          <p className="limit-note">
            {g.limit_note}
            {g.truncated
              ? " This projection is truncated."
              : " This projection is within the cap."}
          </p>
        </article>
        <aside className="drawer">
          <div className="panel-title">
            <span>Detail</span>
            <b>
              {selected
                ? "relationship" in selected
                  ? "Edge"
                  : selected.type
                : "Select an object"}
            </b>
          </div>
          {!selected && (
            <p>
              Choose a node or edge to inspect its evidence and business
              meaning.
            </p>
          )}
          {edge && (
            <>
              <h2>{edge.relationship.replace("_", " ")}</h2>
              <p className="meaning">{edge.meaning}</p>
              {edge.is_synthetic && (
                <p className="simulation-label">
                  Synthetic scenario · not evidence of cause
                </p>
              )}
              <ObjectData data={edge.data} />
            </>
          )}
          {selected && "type" in selected && (
            <>
              <h2>{selected.type}</h2>
              <code className="full-id">{selected.id}</code>
              {selected.provenance === "authored" && (
                <span className="badge authored">Authored</span>
              )}
              {selected.is_synthetic && (
                <p className="simulation-label">Synthetic scenario</p>
              )}
              <ObjectData data={selected.data} />
              {scope.data && sellerId && (
                <>
                  <h3>Exact seller scope</h3>
                  <ObjectData data={scope.data.aggregates} />
                  <p>{scope.data.attribution_note}</p>
                </>
              )}
              {scope.error && <p role="alert">{scope.error.message}</p>}
            </>
          )}
        </aside>
      </div>
      <div className="totals">
        <div className="panel-title">
          <span>Exact authorized totals</span>
          <b>Computed separately from graph cap</b>
        </div>
        {Object.entries(g.totals).map(([k, v]) => (
          <div key={k}>
            <span>{k.replaceAll("_", " ").split(":")[0]}</span>
            <strong>{k.includes("centavos") ? money(v) : v}</strong>
          </div>
        ))}
      </div>
      <JobAction key={orderId} orderId={orderId} />
      {snapshot.data && (
        <article className="panel">
          <h2>Historical order evidence</h2>
          <ObjectData data={snapshot.data.order} />
          <ObjectData data={snapshot.data.metrics} />
          <p>
            Evidence hash: <code>{snapshot.data.evidence_hash}</code>
          </p>
        </article>
      )}
      <div className="evidence-table">
        <div className="panel-title">
          <span>Evidence relationships</span>
          <b>{g.edges.length} visible</b>
        </div>
        <table>
          <thead>
            <tr>
              <th>Relationship</th>
              <th>From</th>
              <th>To</th>
              <th>Business meaning</th>
            </tr>
          </thead>
          <tbody>
            {g.edges.map((e) => (
              <tr key={e.id}>
                <td>
                  <button onClick={() => setSelected(e)}>
                    {e.relationship}
                  </button>
                  {e.is_synthetic && (
                    <span className="tag"> Synthetic scenario</span>
                  )}
                </td>
                <td>
                  <code>{e.source.split(":")[0]}</code>
                </td>
                <td>
                  <code>{e.target.split(":")[0]}</code>
                </td>
                <td>{e.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
function ObjectData({ data }: { data: Record<string, unknown> }) {
  return (
    <dl className="object-data">
      {Object.entries(data).map(([k, v]) => (
        <div key={k}>
          <dt>{k.replaceAll("_", " ")}</dt>
          <dd>
            {k.includes("centavos")
              ? money(v)
              : typeof v === "object"
                ? JSON.stringify(v)
                : String(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
