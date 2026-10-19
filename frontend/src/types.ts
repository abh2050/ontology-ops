export type AppMode = "live" | "evidence" | "sandbox";
export type View = "queue" | "investigation" | "review" | "performance";

export interface QueueItem {
  order_id: string;
  provenance: string;
  purchased_at: string;
  estimated_delivery_date: string;
  days_overdue: number;
  line_count: number;
  seller_ids: string[];
  multi_seller: boolean;
  line_value_centavos: number;
}
export interface QueuePage {
  batch_id: string;
  as_of: string;
  items: QueueItem[];
  aggregates: {
    late_open_orders: number;
    distinct_sellers: number;
    multi_seller_orders: number;
    line_value_centavos: number;
  };
  sort_note: string;
  next_cursor: string | null;
}
export interface GraphNode {
  id: string;
  type: string;
  label: string;
  depth: number;
  provenance: string;
  is_synthetic: boolean;
  data: Record<string, unknown>;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationship: string;
  meaning: string;
  is_synthetic: boolean;
  data: Record<string, unknown>;
}
export interface GraphData {
  batch_id: string;
  as_of: string;
  scenario_id: string | null;
  root: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  max_nodes: number;
  truncated: boolean;
  totals: Record<string, number>;
  limit_note: string;
}
export interface Proposal {
  proposal_id: string;
  job_id: string;
  created_by: string;
  kind: string;
  target_type: string;
  target_id: string;
  payload: Record<string, any>;
  evidence_hash: string;
  state: string;
  revision: number;
  reviewed_by: string | null;
  review_reason: string | null;
  created_at: string;
}
export interface AppData {
  mode: AppMode;
  meta(): Promise<Meta>;
  me(): Promise<Actor>;
  queue(filters?: Record<string, string>): Promise<QueuePage>;
  graph(orderId: string): Promise<GraphData>;
  snapshot(orderId: string): Promise<any>;
  seller(id: string): Promise<any>;
  submit(orderId: string, key: string): Promise<{ job_id: string }>;
  job(id: string): Promise<Job>;
  propose(id: string): Promise<Proposal>;
  proposals(): Promise<Proposal[]>;
  decide?(
    proposal: Proposal,
    decision: "approve" | "reject",
    reason: string,
  ): Promise<Proposal>;
}
export interface Actor {
  subject: string;
  role: string | null;
  provisioned: boolean;
  granted_sellers: number;
  batch_id: string;
  as_of: string;
}
export interface Meta {
  batches: { batch_id: string; provenance: string; demo_as_of: string }[];
  scenarios: { scenario_id: string; description: string }[];
}
export interface Selection {
  batch: string;
  as_of: string;
  scenario_id: string;
}
export interface Job {
  job_id: string;
  state: string;
  revision: number;
  result: any;
}
