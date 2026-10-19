import replay from "./replay.json";
import type { GraphData, Proposal, QueuePage } from "./types";

// Exported by scripts/export_replay.py from the same scoped tools as the API.
export const staticQueue = replay.queue as QueuePage;
export const staticActor = replay.me;
export const staticGraph = (id: string, scenario: string) => {
  const graph = (replay.graphs as Record<string, GraphData>)[
    `${id}|${scenario}`
  ];
  if (!graph) throw new Error("Order is not in this authored replay.");
  return structuredClone(graph);
};
export const snapshots = replay.snapshots as Record<string, any>;
export const sellers = replay.sellers as Record<string, any>;
// Hand-authored action simulations, never recorded model output.
export const staticProposals: Proposal[] = [];
