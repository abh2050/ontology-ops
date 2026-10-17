# Ontology operational-commerce-v1

Source of truth: [backend/ops/ontology/definitions.yaml](../backend/ops/ontology/definitions.yaml), validated by `backend/ops/ontology/registry.py`. PostgreSQL holds the data. The ontology declares identity, direction, cardinality, provenance, derived semantics, and action preconditions.

## Object types
| Type | Identity | Table | Synthetic |
|---|---|---|---|
| Customer | customer_id | customers | no |
| Order | order_id | orders | no |
| OrderLine | order_id + line_no | order_items | no |
| Seller | seller_id | sellers | no |
| Product | product_id | products | no |
| Carrier | scenario_id + carrier_code | carriers | **yes** |
| DisruptionEvent | scenario_id + event_id | disruption_events | **yes** |
| InvestigationCase | case_id | cases | application |
| ActionProposal | proposal_id | proposals | application |

Source identities are scoped to `batch_id`.

## Relationships
| Name | Direction | Cardinality | Provenance |
|---|---|---|---|
| places | Customer → Order | one to many | source |
| contains | Order → OrderLine | one to many | source |
| references | OrderLine → Product | many to one | source |
| fulfilled_by | OrderLine → Seller | many to one | source (never a blame statement) |
| shipped_by | Order → Carrier | many to one | synthetic |
| overlaps | DisruptionEvent → Order | many to many | derived by `event_overlap`, synthetic |

## Named derived functions
`late_open_order(as_of)`, `known_delivery_state(as_of)`, `seller_associated_late_orders(as_of)`, `eligible_investigation(scope, as_of)`, `event_overlap(order, event, as_of)`. Their semantics text is in `definitions.yaml`. Changing any of them requires a new ontology version and a regression test.

## Display projection
In the graph, OrderLine collapses into an Order–Seller edge that carries line_no, product, and line price. Depth is counted on this projection, so Order → Seller → related Order is depth 2. The graph shows at most 50 nodes. Exact totals are computed separately from the display limit.

The registry refuses to load any synthetic type or relationship that lacks `synthetic: true`.
