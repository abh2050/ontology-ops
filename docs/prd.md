> Repository reference copy of the master build specification (claude.md, r2 2026-10-17).
> Owner decisions recorded 2026-10-17 (see AGENTS.md and docs/decisions.md) amend it:
> - docs/business_case.md is the source of truth for ROI figures. The section 3
>   calculation below is kept as the **capacity only illustration**; every value is an assumption.
> - "Meaningful margin" over B0 is defined in configs/policy.yaml and docs/business_case.md.
> - second_model_id is global.amazon.nova-2-lite-v1:0 (configs/models.yaml).

MASTER BUILD SPECIFICATION
ONTOLOGY DRIVEN OPERATIONAL AI
Supply chain delivery exception investigation on AWS
Specification version: 2026-10-17 r2

This prompt is the complete project specification. No separate PRD exists.
If you are continuing an existing repository, inspect it first and preserve
working components that meet these requirements.

Build the application described here. Do not replace its business problem,
dataset, technology stack, evaluation design, or deployment approach.
Do not add product features that this specification does not name.

============================================================
1. BUSINESS PROBLEM
============================================================

Marketplace operations analysts investigate delayed orders using
disconnected order, seller, customer, and product records.

A dashboard can identify an overdue order. The analyst still needs to
complete these tasks:
1. Identify the sellers and products associated with the order.
2. Find other related late orders.
3. Count affected orders without counting multi seller orders twice.
4. Attribute monetary exposure to the correct seller's order lines.
5. Separate observed facts from unsupported explanations.
6. Assemble evidence for an internal investigation.
7. Obtain approval from an independent reviewer.

The product answers this question:
"Which delivery exceptions should we investigate together, what connected
evidence supports that grouping, and which internal response can an
authorized operator approve?"

The application connects business objects through a typed, versioned
ontology. It retrieves authorized evidence. Bounded AI agents prepare a
recommendation. The application creates an internal investigation case
only after an independent reviewer approves it.

The user decides whether to open an evidence supported investigation.
The user does not decide whether to blame a seller, issue a refund, or
promise a delivery date.

The application must never:
1. Contact customers.
2. Change source commerce records.
3. Move inventory.
4. Issue refunds or payments.
5. Claim to establish real causes of delay.

Product positioning:
"Turn connected operational evidence into a reviewable action."

This is an operational decision application. Its evaluation tests whether
typed relationships and action contracts improve investigation quality
and task completion compared with simpler alternatives. It is not a model
release control plane, an energy dispatch application, a general chatbot,
or a general ontology editor.

Modeled current enterprise environment:
Marketplace or ERP exports contain orders and master data. BI dashboards
show exceptions. Analysts connect records by hand in spreadsheets.
Investigation handoffs happen through email or task systems. This is a
modeled customer environment. It makes no claim about Olist's internal
systems or any employer's architecture.

============================================================
2. USERS AND CORE PRODUCT REQUIREMENTS
============================================================

Personas:
1. Operations analyst. Finds related delivery exceptions and assembles an
   evidence supported case.
2. Operations lead and reviewer. Checks evidence, authority, scope, and the
   proposed internal action.
3. Customer support specialist. Prepares a factual internal customer
   update draft that states uncertainty.
4. Data and platform engineer. Verifies relationship definitions,
   provenance, authorization, and reliability.
5. Product sponsor. Decides whether the assisted workflow warrants a
   limited pilot.

Application roles: operator, reviewer, viewer.
The application serves one organization. Explicit seller grants determine
data access. Do not implement multi tenancy.

Required capabilities:
1. Import and validate the full specified Olist data.
2. Reconstruct historical evidence at a selected as_of.
3. Display and investigate a queue of late open orders.
4. Traverse authorized business relationships.
5. Calculate exact distinct order counts and line level monetary exposure.
6. Retrieve optional, clearly labeled synthetic disruption context.
7. Generate a typed, evidence linked recommendation.
8. Validate the recommendation with deterministic code.
9. Require a different authorized reviewer before case execution.
10. Create the internal case idempotently.
11. Persist asynchronous job progress and failure states.
12. Compare deterministic, flat evidence, and ontology assisted workflows.
13. Serve the same interface in static evidence and dummy data modes.

Allowed actions:
1. CreateInvestigation. Creates an internal case concerning an order or a
   seller associated group. It never modifies commerce records. This
   action is the core of the product.
2. DraftCustomerUpdate. Stores an internal factual draft for one order.
   It has no send capability and no recipient field. This action is
   secondary and is the first feature to cut if the schedule slips.

============================================================
3. BUSINESS CASE AND SUCCESS MEASURES
============================================================

Illustrative business case (CAPACITY ONLY ILLUSTRATION; docs/business_case.md
is the ROI source of truth). These values are assumptions, not measured
savings:
1,000 investigations per month at 12 minutes each at $45 per hour equals
$9,000 per month of investigation labor. Reducing complete task time to
8 minutes creates $3,000 per month of capacity value. Subtracting an
assumed $150 per month for hosting and inference and 4 maintenance hours
at $75 per hour leaves an illustrative net capacity value of $2,550 per
month.

Label these values as assumptions everywhere they appear. Task time
measurements include verification, correction, and approval. Never claim
reduced delivery delays, churn, refunds, or order loss.

Metrics and proposed targets:
1. Investigation task success. The response names the correct affected
   set and an eligible action supported by evidence. Target: at least 90
   percent on the frozen benchmark.
2. Relationship precision and recall against canonical authorized SQL
   results. Target: at least 0.95 each.
3. Aggregate correctness for distinct order counts and integer centavo
   values. Target: 100 percent on deterministic tests.
4. Evidence coverage. Factual claims carry valid evidence references.
   Target: at least 95 percent, with zero invented object IDs.
5. Unsupported causal claims accepted. Target: zero.
6. Authorization failures accepted for forbidden reads or writes.
   Target: zero.
7. Approval integrity failures accepted for self, stale, or duplicate
   executions. Target: zero.
8. Human investigation time. Target: at least 25 percent faster without
   lower quality. This claim remains untested until participants are
   recorded.
9. Warm read latency. Target: p95 authenticated read response under
   750 ms at 20 concurrent readers on the full imported Olist dataset.
10. AI job completion. Target: submit to ready p95 under 60 seconds with
    at most two concurrent jobs. Report queue wait separately.
11. Cost. Report actual inference usage and allocated infrastructure cost
    per completed investigation. Unknown provider charges stay labeled
    unknown.

Targets are not results. Report measured values, failures, and untested
claims honestly.

============================================================
4. REQUIRED TECHNOLOGY STACK
============================================================

Frontend: React 19, TypeScript 5, Vite, Tailwind CSS 4, TanStack Query,
Cytoscape.js.

Backend: Python 3.12, FastAPI, Uvicorn, Pydantic 2.

Persistence: PostgreSQL 16, SQLAlchemy 2, psycopg 3, Alembic.

AI: boto3 Bedrock Converse with strict client side Pydantic output
validation. Default model amazon.nova-lite-v1:0 in us-east-1. A second
model is named in configs/models.yaml (see section 10.6).

AWS: Amazon SQS Standard queue with DLQ, Cognito authorization code flow
with PKCE, ECS Fargate, Application Load Balancer, ACM HTTPS, RDS
PostgreSQL 16, S3, Secrets Manager, ECR, CloudWatch.

Infrastructure and delivery: AWS CDK v2 in Python, GitHub Actions,
GitHub Pages for static evidence replay and the dummy sandbox.

Testing and evaluation: pytest, Ruff, Playwright, MLflow 3 with local
experiment artifacts, Python and scikit-learn metrics where applicable.

Resolve compatible patch versions. Commit uv.lock and
frontend/package-lock.json.

Do not drop or substitute any required technology to save time.
Do not add graph databases, vector databases, agent frameworks, Kafka,
Redis, read replicas, sharding, Databricks, Foundry, or other cloud
platforms.

============================================================
5. REAL PUBLIC DATA
============================================================

Dataset: Brazilian E-Commerce Public Dataset by Olist.
Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
License: CC BY-NC-SA 4.0.

Load the full dataset. Do not sample.

Read exactly these five files and no others:
1. olist_orders_dataset.csv
2. olist_order_items_dataset.csv
3. olist_sellers_dataset.csv
4. olist_products_dataset.csv
5. olist_customers_dataset.csv

Do not use reviews, payments, geolocation, or any other source file.

Validate these exact source headers, including the source spelling:

Orders: order_id, customer_id, order_status, order_purchase_timestamp,
order_approved_at, order_delivered_carrier_date,
order_delivered_customer_date, order_estimated_delivery_date

Order items: order_id, order_item_id, product_id, seller_id,
shipping_limit_date, price, freight_value

Sellers: seller_id, seller_zip_code_prefix, seller_city, seller_state

Products: product_id, product_category_name, product_name_lenght,
product_description_lenght, product_photos_qty, product_weight_g,
product_length_cm, product_height_cm, product_width_cm

Customers: customer_id, customer_unique_id, customer_zip_code_prefix,
customer_city, customer_state

Validate every header. Persist only the fields named in the database
schema in section 9. Do not build features around ZIP codes, cities, or
physical product dimensions.

The project owner acquires the dataset with their own Kaggle account and
places the files in data/raw/olist. Never store acquisition credentials
in the repository.

5.1 Manifest
Selection version: full-v1. manifest.json records the source URL, SHA-256
hash per file, row count per file, download date, license, importer
version, quarantine counts by reason, and the chosen demo as_of with its
counts. Reimporting the same files produces the same batch content and
the same manifest hashes. Test this.

5.2 Import validation
1. Fail the import on any header mismatch.
2. Validate types and ID formats.
3. Parse money with Decimal and round half up to integer centavos. Never
   use floating point arithmetic for money.
4. Quarantine invalid rows. Never discard or repair them silently.
5. Each quarantine record stores batch_id, source_file,
   source_row_number, reason_code, and the raw row as JSON.

Reason codes:
NEG_MONEY, BAD_MONEY, APPROVED_BEFORE_PURCHASE, CARRIER_BEFORE_PURCHASE,
DELIVERED_BEFORE_CARRIER, DELIVERED_BEFORE_PURCHASE, MISSING_ESTIMATE,
BROKEN_FK, ORDER_QUARANTINED, CONFLICTING_DUPLICATE, DUPLICATE_IDENTICAL.

6. A conflicting duplicate fails the whole import.
7. An identical duplicate is kept once and counted under
   DUPLICATE_IDENTICAL.
8. When an order is quarantined, every order item that references it is
   quarantined under ORDER_QUARANTINED. The manifest reports both counts.
9. Store order_status in the orders table for data quality reporting
   only. No snapshot tool, runtime query, view, prompt, or UI evidence
   panel may read it. Add a test that fails if any module under
   backend/ops/queries, backend/ops/agents, or backend/ops/commands
   references the column.

5.3 Data limitations
Olist contains order level delivery timestamps. It does not contain
seller specific shipment tracking. Orders can contain lines from several
sellers. The data does not contain carrier identities, causes of delay,
seller inventory, customer contact history, or cancellation event
timestamps. Never present any of these as real facts.

============================================================
6. HISTORICAL SNAPSHOTS AND DEMO DATE
============================================================

Source timestamps have no timezone. Store commerce timestamps without
timezone and label them dataset local in the UI and docs.

At a selected as_of:
1. Include only purchases at or before as_of.
2. Reveal approval, carrier handoff, and customer delivery only when the
   event occurred at or before as_of.
3. Never reveal a future delivery event.
4. Never use final order_status to reconstruct historical knowledge.
5. Do not reconstruct cancellation history.

Late open definition: the as_of date is later than the estimated
delivery date, and no customer delivery is known at as_of. Estimated
delivery is a date level commitment. Item shipping_limit_date keeps its
own timestamp meaning and is reported separately.

Static seller and product mappings are an explicit reconstruction
assumption. Record this in docs/decisions.md.

Default queue purchase window: 2018-01-01 through 2018-08-31 inclusive,
dataset local. The window is a UI default filter. Queries outside it
still work.

Command ops data pick-as-of evaluates every day in the demo window and
reports three counts per day: late open orders, sellers with at least
three late open orders, and late open multi seller orders. It writes the
top five candidates to data/as_of_candidates.json. The default demo
as_of is the day with the most sellers having at least three late open
orders. Break ties by the larger late open order count, then by the
earlier date. Record the chosen value and its counts in manifest.json.

============================================================
7. SYNTHETIC SCENARIO LAYER
============================================================

The real dataset has no carrier identities or delay causes. An authored
scenario overlay lets the application demonstrate context traversal and
separate relevant events from decoys. Real Olist tables stay unchanged.

Every synthetic row has scenario_id and
is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic).

Tables:
synthetic_scenarios(scenario_id text primary key, seed integer,
  generator_version text, description text, created_at timestamptz,
  is_synthetic)
carriers(scenario_id, carrier_code text, display_name text, is_synthetic,
  primary key (scenario_id, carrier_code))
carrier_assignments(scenario_id, batch_id, order_id, carrier_code,
  assigned_at timestamp, is_synthetic,
  primary key (scenario_id, batch_id, order_id),
  foreign keys to orders and carriers)
disruption_events(event_id uuid primary key, scenario_id,
  kind text CHECK (kind IN ('carrier_backlog','seller_stockout',
  'regional_weather','system_outage')), carrier_code text null,
  seller_id text null, affected_states text[], starts_at timestamp,
  ends_at timestamp, summary text, is_synthetic)

Rules:
1. Create five carriers with codes CARRIER_A through CARRIER_E. Display
   names must be obviously fictional and must not resemble real
   companies.
2. Assign each order a carrier by a stable hash of
   (seller_state, customer_state, seed) modulo 5. For multi seller
   orders, use the seller_state of the order line with the lowest
   line_no. Record this rule in docs/decisions.md and show it in the
   carrier edge explanation in the UI.
3. assigned_at equals the order's carrier_at. Orders without carrier_at
   receive no assignment.
4. Seed six to eight events inside the demo window. At least two overlap
   the default as_of. At least one overlaps a seller group with no
   matching carrier pattern, so the correct answer is cause unknown. At
   least one is a temporal decoy that sits near related orders but does
   not overlap them in time.
5. Command: ops scenario generate --seed 42 --scenario base-v1. The same
   seed produces identical rows. Test this.
6. Every job records scenario_id or null. With null, no tool reads a
   synthetic table. Evaluation runs in both real only and scenario
   enabled modes.
7. Every evidence reference to synthetic data carries is_synthetic=true.
8. The UI shows a visible "Synthetic scenario" badge on every node, edge,
   table row, and draft that uses synthetic evidence. Static exports keep
   the badge.
9. Only the import database role writes synthetic tables. API and worker
   roles read them.

============================================================
8. ONTOLOGY
============================================================

Version: operational-commerce-v1.

Domain object types and identities:
Customer: customer_id
Order: order_id
OrderLine: order_id plus line_no
Seller: seller_id
Product: product_id
Carrier: scenario_id plus carrier_code (synthetic)
DisruptionEvent: scenario_id plus event_id (synthetic)

Application object types:
InvestigationCase: case_id
ActionProposal: proposal_id

Source identities are scoped to batch_id.

Relationships:
1. places: Customer to Order, one to many.
2. contains: Order to OrderLine, one to many.
3. references: OrderLine to Product, many to one.
4. fulfilled_by: OrderLine to Seller, many to one.
5. shipped_by: Order to Carrier, many to one, synthetic.
6. overlaps: DisruptionEvent to Order, derived, synthetic.

definitions.yaml declares identity, edge direction, cardinality,
provenance, derived semantics, and action preconditions. Pydantic
validates the definitions and every domain object. Every synthetic type
and relationship declares synthetic: true. The registry refuses to load a
synthetic type that lacks this declaration.

Do not build a general schema compiler or ontology editor. PostgreSQL is
the source of truth. Cytoscape.js renders an authorized, bounded
projection.

Named derived functions:
late_open_order(as_of)
known_delivery_state(as_of)
seller_associated_late_orders(as_of)
eligible_investigation(scope, as_of)
event_overlap(order, event, as_of)

event_overlap returns true only when both conditions hold:
1. The order's carrier, any of its sellers, or the customer state
   matches the event scope.
2. The event window intersects the order interval. The order interval
   starts at carrier_at when carrier_at is known at as_of, otherwise at
   purchased_at. The interval ends at as_of.
Only events with starts_at at or before as_of are visible. Apply
historical masking before any assignment or event evidence leaves the
query layer.

Changing any derived function requires a new ontology version and a
regression test.

Graph display projection:
1. In the displayed graph, OrderLine collapses into an edge between Order
   and Seller. The edge carries line_no, product, and line price.
2. Depth is counted on this projection. The path Order to Seller to
   related Order is depth two and must be displayable.
3. OrderLine remains a full object in the detail drawer, the evidence
   table, and the API.
4. The graph shows at most 50 nodes. Exact aggregate counts are computed
   separately from the display limit. The UI labels truncation and
   pagination clearly.

============================================================
9. DATABASE SCHEMA
============================================================

Use Alembic migrations. Never let an LLM generate a migration at runtime.
Commerce timestamps use timestamp without time zone. Application audit
timestamps use timestamptz. Money uses integer centavos. Application IDs
use UUID where specified.

source_batches(batch_id text primary key, manifest jsonb not null,
  imported_at timestamptz default now())

users(subject text primary key, role text CHECK (role IN
  ('operator','reviewer','viewer')), active boolean not null default true)

sellers(batch_id references source_batches, seller_id text, state text,
  primary key (batch_id, seller_id))

seller_grants(subject references users, batch_id, seller_id,
  primary key (subject, batch_id, seller_id),
  foreign key (batch_id, seller_id) references sellers)

customers(batch_id references source_batches, customer_id text,
  customer_unique_id text, state text,
  primary key (batch_id, customer_id))

products(batch_id references source_batches, product_id text,
  category text null, primary key (batch_id, product_id))

orders(batch_id, order_id text, customer_id text,
  purchased_at timestamp not null, approved_at timestamp null,
  carrier_at timestamp null, delivered_at timestamp null,
  estimated_at timestamp, order_status text,
  primary key (batch_id, order_id),
  foreign key (batch_id, customer_id) references customers)
  order_status is for data quality reporting only (see 5.2 rule 9).

order_items(batch_id, order_id, line_no integer, product_id, seller_id,
  shipping_limit_at timestamp,
  price_centavos bigint CHECK (price_centavos >= 0),
  freight_centavos bigint CHECK (freight_centavos >= 0),
  primary key (batch_id, order_id, line_no),
  batch scoped foreign keys to orders, products, sellers)

quarantine(quarantine_id uuid primary key, batch_id, source_file text,
  source_row_number integer, reason_code text, raw_row jsonb,
  created_at timestamptz)

jobs(job_id uuid primary key, subject references users,
  idempotency_key text, request_hash text,
  batch_id references source_batches,
  scenario_id null references synthetic_scenarios,
  ontology_version text, as_of timestamp,
  state CHECK (state IN ('queued','running','validating','ready',
  'failed','unknown','blocked')),
  input jsonb, checkpoint jsonb default '{}', result jsonb null,
  scope_hash text, evidence_hash text null, lease_token uuid null,
  lease_until timestamptz null, revision bigint default 0,
  created_at timestamptz, unique (subject, idempotency_key))

outbox(event_id uuid primary key, job_id references jobs,
  created_at timestamptz, sent_at timestamptz null)

proposals(proposal_id uuid primary key, job_id references jobs,
  created_by references users,
  kind CHECK (kind IN ('CreateInvestigation','DraftCustomerUpdate')),
  target_type CHECK (target_type IN ('Order','Seller')),
  target_id text, payload jsonb, evidence_hash text, proposal_hash text,
  state CHECK (state IN ('pending','executed','rejected','stale',
  'needs_review')), revision bigint default 0,
  reviewed_by null references users, review_reason text null,
  created_at timestamptz)

cases(case_id uuid primary key, proposal_id unique references proposals,
  case_key text unique, owner_subject references users,
  case_payload jsonb, created_at timestamptz)

internal_drafts(draft_id uuid primary key,
  proposal_id uuid unique references proposals, body jsonb not null,
  created_at timestamptz)
  No column stores a recipient. Only the API role inserts rows.

audit_events(event_id uuid primary key, actor text, kind text,
  object_id text, safe_payload jsonb, created_at timestamptz)

usage_days(day date primary key,
  admitted_calls integer default 0 CHECK (admitted_calls >= 0))

eval_runs(eval_run_id uuid primary key, planned_calls integer,
  admitted_calls integer default 0, ceiling integer,
  created_at timestamptz)

model_calls(call_id uuid primary key, job_id references jobs,
  stage CHECK (stage IN ('planner','analyst')),
  state CHECK (state IN ('reserved','sent','complete','known_failure',
  'unknown')), model_id text, price_snapshot jsonb, request_hash text,
  usage jsonb null, admitted_day references usage_days,
  eval_run_id null references eval_runs, created_at timestamptz,
  unique (job_id, stage))

Also implement the four synthetic tables in section 7 and a provenance
column on fixture rows (see section 14).

Required initial indexes:
order_items(batch_id, seller_id, order_id)
order_items(batch_id, product_id)
orders(batch_id, estimated_at, order_id)
orders(batch_id, customer_id)
outbox(created_at) WHERE sent_at IS NULL
audit_events(object_id, created_at)

Polymorphic proposal targets and selected order IDs cannot use a single
foreign key. Validate target existence, batch, scenario, ownership, and
action eligibility on the server at proposal creation and at execution.

============================================================
10. TOOLS AND AGENTS
============================================================

10.1 Tools
Implement five tools with strict input schemas backed by parameterized,
server authored SQL:
1. get_order_snapshot(order_id, as_of): the authorized order, its lines,
   and events known at as_of.
2. find_late_orders(as_of, bounded_filters): paginated distinct orders
   and exact authorized aggregates.
3. get_seller_exception_scope(seller_id, as_of): authorized related
   orders and line price exposure for that seller.
4. check_case_eligibility(target, snapshot_hash): deterministic action
   preconditions and an existing case check.
5. get_disruption_context(target_type, target_id, as_of, scenario_id):
   overlapping synthetic events and the basis of each overlap. It returns
   empty without reading synthetic tables when scenario_id is null.

Do not expose arbitrary SQL, shell, browsing, arbitrary HTTP, messaging,
payments, or source record mutation.

10.2 Agent stages
Use exactly two bounded AI stages.
1. Planner. Returns a typed ToolPlan with at most three allowlisted tool
   requests. It cannot choose actor identity, change permissions, or
   raise graph limits.
2. Analyst. Receives only authorized tool results and produces findings
   plus an optional typed action.
A deterministic validator runs after the analyst. The validator is code,
not a third LLM. No recursive delegation and no open ended agent loop.

Workflow:
operator selects a target or question, the API validates identity and
scope, the API persists the job and outbox row, the worker claims the
job, the planner runs, authorized tools run, the analyst runs, the
validator runs, an independent reviewer decides, and the action
transaction executes.

10.3 Proposal contents
Action kind, target type and ID, selected authorized order IDs, evidence
references, snapshot hash, ontology version, reason codes, and unresolved
questions. Counts and money come from deterministic evidence metrics.
The model never authors arithmetic.

10.4 Validator rejections
The validator rejects invented IDs, unresolvable evidence, unauthorized
objects, incorrect arithmetic, invalid action targets, stale evidence,
and unsupported causal claims.

10.5 Language rule
The analyst may state that orders are "temporally and regionally
consistent with" a synthetic event. The analyst may not claim that a
seller, carrier, or event caused a delay. The validator rejects these
constructions when attached to a seller, carrier, or event: caused, due
to, because of, resulted from, responsible for. A rejection sets the
proposal to needs_review. Report causal rejections as a separate metric.

10.6 Model configuration
Default model: amazon.nova-lite-v1:0 in us-east-1 through Bedrock
Converse. Validate output with strict client side Pydantic JSON
validation. Do not assume native constrained JSON support.

configs/models.yaml names the second experimental model:
  second_model_id: <OWNER FILLS IN BEFORE M1>
If this value is still a placeholder when M1 begins, stop and report the
missing input. Do not pick a model yourself. Do not hardcode either model
anywhere except configs/models.yaml.

Preflight verifies access to every configured model and fails if any is
unavailable. Never substitute a model silently. Log model_id in every
evaluation run and report results per model.

Disable SDK automatic inference retries. Test that a timeout produces the
unknown state and no second paid call.

============================================================
11. IDENTITY, AUTHORIZATION, AND APPROVAL
============================================================

11.1 Deployed identity
Cognito authorization code flow with PKCE. The server verifies access
token signature, issuer, expiry, token_use=access, and client_id. The
users and seller_grants tables are authoritative. A valid token without
an active provisioned user grants no data access. Self sign up is
disabled. Users are provisioned only by ops seed-users.

11.2 Local identity
AUTH_MODE=local issues signed test tokens from a fixture key with the
same claims as Cognito access tokens. The server verifies local tokens
through the same verification code path with a different key source.
The application refuses to start with AUTH_MODE=local when DEPLOY_ENV is
anything other than local.

11.3 Seeded users and grants
ops seed-users creates four users: operator_a, operator_b, reviewer, and
viewer.
1. operator_a receives the sellers in the top half of late open seller
   groups at the default as_of, ranked by late open order count
   descending, then seller_id ascending.
2. operator_b receives all remaining sellers.
3. reviewer receives all sellers.
4. viewer is provisioned and active with no seller grants. The demo uses
   viewer to show that a valid identity without grants sees nothing.
5. At least one fixture multi seller order spans operator_a and
   operator_b grants.

11.4 Visibility rules
Role never implies seller scope. An order is visible only when every
seller on that order is granted to the actor. An order with an empty or
unmatched line set is not visible. Customer traversal exposes only
visible orders.

Apply authorization before joins, traversals, counts, totals, graph
construction, caching, and saved result serialization. Hidden IDs never
appear in nodes, counts, totals, logs, or error details.

Recheck current scope during worker retrieval, when reading saved
results, and at review and execution. A grant revoked mid job forces a
rerun or blocks the job.

11.5 Independent approval
A reviewer cannot approve their own proposal. The reviewer must
independently hold scope over every target. The approval transaction
locks the proposal and validates the current actor, current permissions,
proposal revision, evidence and snapshot hash, ontology version, current
eligibility, and any existing equivalent case.

For CreateInvestigation, the transaction inserts the case, marks the
proposal executed, and appends an audit event atomically. For
DraftCustomerUpdate, the transaction inserts the internal_drafts row,
marks the proposal executed, and appends an audit event. It never
inserts a case and never produces an external side effect.

UNIQUE(proposal_id) on cases and internal_drafts makes duplicate
acceptance safe. case_key derives from batch, target, as_of, and case
type. Take a transaction level advisory lock on the target so competing
proposals cannot open the same investigation. A stale proposal returns
HTTP 409 and must be regenerated.

A proposal in needs_review cannot be executed. The operator regenerates
the job to produce a new proposal. Rejected and needs_review proposals
stay in audit history.

Two browser tabs for the same user never count as independent approval.

11.6 Database roles
Separate credentials for migration and admin, import, API, and worker.
1. Import writes source tables, quarantine, and synthetic tables.
2. API reads permitted source and synthetic data and writes jobs, outbox,
   proposals, approved cases, internal drafts, and audit events.
3. Worker reads source and synthetic data and writes job results,
   checkpoints, outbox sent_at, and model call records. Worker cannot
   approve proposals or insert cases.
4. Runtime roles cannot modify users or grants and cannot delete audit
   events. No runtime role uses superuser credentials.
Test these permissions against PostgreSQL.

============================================================
12. QUEUE, FAILURE HANDLING, AND COST
============================================================

One codebase and one container image with API and worker entry points.
The outbox relay runs inside the worker process.

12.1 Job lifecycle
1. Submission writes the job and the outbox row in one transaction and
   returns HTTP 202 with the job ID. The same idempotency key with the
   same request hash returns the existing job. A different hash returns
   HTTP 409.
2. The relay polls committed outbox rows every two seconds, publishes
   job and event IDs to SQS, and marks sent only after a successful
   send. A crash between send and mark can produce a duplicate message.
3. Queue messages carry IDs only, never prompts or customer records.
4. The worker claims a job with a random lease token and a 120 second
   lease and writes only while it owns the lease. It persists
   checkpoints before acknowledging SQS.
5. SQS visibility timeout starts at 180 seconds. At most two jobs run at
   once. The full workflow deadline is 60 seconds.

12.2 Paid call admission
1. Before each paid call, one transaction reserves the unique
   model_calls(job_id, stage) row and increments the admitted count.
2. Persist state sent before the external inference call. Inference runs
   outside any database transaction.
3. Retry a provider rejection only when the provider confirms that no
   generation occurred, with one jittered retry.
4. Never retry an unknown paid outcome automatically. No hidden SDK
   retries.
5. A reclaimed stage in sent or unknown is held for explicit
   reconciliation through ops recover-job.
6. A reclaimed stage in reserved that was never sent may resume.
7. Completed stages are reused only when scope and evidence hashes still
   match.
8. Acknowledge SQS only after a durable terminal state: ready, failed,
   blocked, or unknown hold.

12.3 Dead letters and breaker
Unhandled poison messages reach the DLQ after five receives. Source queue
retention is four days. DLQ retention is fourteen days. Never redrive
blindly. After five consecutive known provider failures, the circuit
breaker opens for 60 seconds, blocks new paid admissions, shows a
provider unavailable state, and allows one half open probe. One worker
permits a process local breaker. Document that it is not fleet wide.
Durable call limits survive process restart.

12.4 Live cost limits
1. 100 admitted model calls per day for live traffic.
2. Two calls per job.
3. 20 queued jobs per user.
4. Planner: at most 2,000 input tokens and 512 output tokens.
5. Analyst: at most 4,000 input tokens and 768 output tokens.
6. Serialize bounded evidence only, never a database dump.
7. Invalid JSON fails safely with no repair call loop.

12.5 Evaluation budget
Frozen evaluation runs use a separate budget recorded in eval_runs and
configs/policy.yaml, with a ceiling of 1,500 calls per full run. Eval
calls do not count against the live daily cap. ops eval prints the
planned call count before starting and refuses to start if the plan
exceeds the ceiling.

12.6 Pricing and hosting envelope
configs/price_card.yaml records model and region rates, source URL,
effective date, and infrastructure assumptions from official current
pricing. Report actual returned usage. Unknown charges are never zero.
$25 is an experiment planning allowance, not a guaranteed cap.
$80 to $180 per month is a provisional hosting estimate pending a
regional calculation.

Initial sizing: API task 0.25 vCPU and 0.5 GiB. Worker task 0.5 vCPU and
1 GiB. RDS single AZ development tier with encrypted 20 GiB storage.
CloudWatch logs retained seven days. Temporary S3 staging expires after
seven days.

============================================================
13. SYSTEM DESIGN CHOICES
============================================================

Each choice responds to a workload. Document the scale trigger for each
deferred service without implementing it.

1. Too many reads. Indexes, keyset pagination, ETags on job and metadata
   responses, and in process caching of immutable ontology metadata.
   Never cache approvals or role decisions. Any later scoped cache keys
   on principal scope hash, ontology version, batch, as_of, scenario, and
   filters. Mutable entity responses send Cache-Control: private,
   no-store.
2. Too many writes. CSV staging with COPY in batches of 1,000,
   transactional upserts, append only audit batches, background import.
   No sharding.
3. Timely updates. The UI polls job status every two seconds with ETag
   and exponential idle backoff. This is near real time job visibility,
   not live commerce streaming. No WebSockets or SSE.
4. Slow jobs. SQS with a bounded worker. The API returns 202 with a job
   ID.
5. Failures. Safe retries with backoff, idempotent commands, leases,
   checkpoints, DLQ, and the circuit breaker.
6. Read and write contention. Logical CQRS with separate command handlers
   and query services on one PostgreSQL database. A stale expected
   revision returns 409. No separate read store and no event sourcing.

============================================================
14. FIXTURES AND EVALUATION
============================================================

14.1 Authored fixtures
Load authored fixtures into a separate batch named fixtures-v1. Never
mix fixture rows into an Olist batch. Include at least 30 multi seller
orders, orders split across operator_a and operator_b grants, duplicate
line attempts, a prompt injection string inside a product category, a
stale snapshot, a grant revoked mid job, and a missing link. The UI and
every report label fixture rows as authored.

14.2 Comparators
1. B0. Deterministic SQL queue, filters, and source record views. No AI.
2. B1. Flat evidence assistant using the same authorized facts, model,
   token and call limits, and approval boundary.
3. Candidate. Ontology traversal, named semantics, typed relationships,
   and typed action proposals with the same model and approval boundary.
When scenarios are enabled, B1 receives the same carrier and event facts
as the candidate. Never withhold facts from a baseline to manufacture a
win.

14.3 Gold set
60 questions: 20 direct object, 20 multi object, 10 aggregate, and 10
unanswerable or unsupported cause. At least 15 require synthetic
traversal. At least 20 are answerable with real Olist data alone. Tag
each question requires_scenario true or false.

Gold set review gate:
1. Codex drafts the questions, canonical SQL, rubric, thresholds, and
   as_of values under data/gold, then stops.
2. The project owner reviews and edits every item.
3. The freeze commit records the reviewer identity, the review date, and
   a hash of the gold set.
4. ops eval refuses to run on a gold set without reviewer metadata or
   with a changed hash.

14.4 Runs and reporting
Evaluate both modes: real only and scenario enabled. Evaluate both
configured models for B1 and the candidate. B0 is model independent, so
never invent model usage for it. Report every metric in section 3 per
comparator, model, and mode where applicable, and mark not applicable
values explicitly. Report causal rejections separately.

Also implement 20 security and approval scenarios and 15 reliability
scenarios.

MLflow 3 local artifacts record model, comparator, mode, ontology
version, source hashes, as_of, prompt hash, code commit, limits, metrics,
and raw results. No hosted tracking service.

14.5 Human timing
Write docs/timing_protocol.md with 12 matched tasks, counterbalanced
order, a consent note, and raw participant timing records. Use two or
three participants if available. Developer timing alone does not
establish general productivity. If no participants are recorded,
docs/results.md states: "Human timing improvement is untested."

============================================================
15. AWS ARCHITECTURE AND DEPLOYMENT
============================================================

Request flow: React workspace to HTTPS ALB to FastAPI on ECS Fargate to
private RDS PostgreSQL.
Job flow: job and outbox rows to the worker relay to SQS and DLQ to the
Fargate worker to Bedrock to the persisted result.

Cognito provides identity. S3 stores versioned imports and sanitized
exports. ECR stores the image. Secrets Manager supplies secrets.
CloudWatch stores redacted logs and queue alarms. The API serves the
compiled React UI from the same origin.

One CDK stack in us-east-1 creates: a VPC with two public and two private
subnets, an internet gateway, the ALB with an ACM certificate, the ECS
cluster with API and worker services, private RDS, SQS with DLQ, the
Cognito user pool and client, ECR, Secrets Manager entries, S3, and
CloudWatch.

Network:
1. Fargate tasks may run in public subnets with assigned public IPs for
   outbound HTTPS, which avoids NAT gateway cost.
2. API ingress is allowed only from the ALB security group.
3. The worker accepts no inbound traffic.
4. RDS accepts port 5432 only from the API and worker security groups
   and is not public.
5. All service calls and database sessions use TLS.

IAM:
1. API task role: required S3 read and export, its own secret, safe
   logs. No Bedrock invocation and no queue send.
2. Worker task role: specific queue send, receive, and delete, its own
   secret, invocation of configured Bedrock models, safe logs. No
   approval capability.
3. Migration runs as a separate one off task with its own role.
4. Use task roles. Never put AWS credentials in the browser.

Preflight (ops preflight --cloud aws) fails with a clear message when
any item is missing: a domain the owner controls, a valid ACM
certificate, an HTTPS Cognito callback on that domain, access to every
configured Bedrock model, an ECR repository that exists or can be
created, account and region that match configuration, and project tags
on all resources. Preflight prints an estimated monthly cost table from
configs/price_card.yaml with every value labeled estimate.

Deployment sequence: preflight, CDK synth and diff, provisioning needed
for migration, one off ECS migration task, source import, Cognito user
and grant provisioning, API and worker release, authenticated smoke
tests, limited live evaluation.

Never claim a deployment succeeded without verification. Never bypass a
missing cloud input.

============================================================
16. FRONTEND AND PUBLIC DEMOS
============================================================

Four views built from shared React components:
1. Exception queue. Default purchase window, historical as_of, and
   deterministic urgency sorted by days overdue descending, eligible line
   value descending, then order_id. Label the sort as a prioritization
   heuristic, not learned intervention value.
2. Connected investigation. Cytoscape graph linked to the object detail
   drawer and the evidence table. Selecting an edge explains its business
   meaning. Graph limits are shown separately from exact totals. A
   seller relationship never becomes a blame statement.
3. Action review. Proposed internal action, evidence, unknowns, owner,
   revision, and independent approval or rejection state.
4. Evidence and performance. Comparator results, measured latency and
   cost, provenance, and limitations.

Every view shows the batch, the as_of, and any authored or synthetic
labels that apply. Viewer and reviewer UI states reflect server
permissions.

Three adapters share the same components:
1. Live authenticated API.
2. Measured static evidence replay.
3. Dummy data sandbox.

GitHub Pages serves /evidence/ and /sandbox/. Static actions are visibly
labeled as simulations. Static builds contain no credentials and make no
backend API calls. Playwright verifies zero API requests.

Preserve source attribution and license terms. If derivative
redistribution of Olist data is unresolved, publish authored fixtures
only in the static builds.

============================================================
17. HIRING MANAGER DEMONSTRATION
============================================================

Record the real deployed application before teardown. Length 3 minutes
40 seconds.

0:00 to 0:25 Business problem and operational decision.
0:25 to 1:10 Late order to seller to related authorized orders, with an
explanation of typed relationships and historical evidence.
1:10 to 1:45 Exact counts, seller line value, optional synthetic
context, and a cause that remains unknown.
1:45 to 2:20 Agent proposal and independent internal case approval.
2:20 to 2:50 The viewer, provisioned with no grants, sees nothing. A
worker crash followed by SQS redelivery still produces one case. Label
fault injection on screen.
2:50 to 3:15 Measured comparator results and the architecture.
3:15 to 3:40 Pilot recommendation and the public static replay.

Never present mock footage as a live deployment. Never show secrets,
tokens, or private identity data.

Produce an editable draw.io architecture diagram and an SVG export after
implementation verification so the diagram matches the deployed system.
Also produce the recorded video, sanitized evidence artifacts, and both
static interfaces.

README order: business problem, user decision, measured findings, pilot
recommendation, evidence and video, architecture, stack, reproduction,
synthetic layer disclosure, limitations, cloud resource status.

Pilot recommendation rule: recommend proceeding only if quality,
grounding, authorization, and approval gates pass and timing supports
the productivity claim. Otherwise state what needs revision, or
recommend the deterministic workspace.

============================================================
18. MILESTONES AND ACCEPTANCE GATES
============================================================

Implement milestones in this order. Do not start a milestone until the
previous milestone's checks pass and the results are written to
docs/progress.

M1 DATA AND ONTOLOGY
1. Full Olist import completes with manifest and quarantine report,
   including the ORDER_QUARANTINED cascade.
2. ops data pick-as-of writes candidates and records the chosen date.
3. Scenario generator is deterministic for a fixed seed.
4. fixtures-v1 batch loads separately.
5. All ontology types load. Direction and cardinality tests pass.
6. The order_status isolation test passes.
7. configs/models.yaml contains a real second model ID.

M2 DETERMINISTIC WORKSPACE
1. All five tools work with strict schemas and parameterized SQL.
2. Multi seller deduplication and line price attribution tests pass.
3. Future timestamp masking passes at three as_of values.
4. Hidden node leakage tests pass for IDs, counts, totals, logs, and
   errors.
5. The display projection renders Order to Seller to related Order at
   depth two.
6. EXPLAIN ANALYZE output is saved for every query.
7. p95 read latency is measured locally on the full data.

M3 AGENTS AND QUEUE
1. Outbox, relay, consumer, leases, and checkpoints work locally with the
   fixture queue and fixture provider.
2. Duplicate delivery, crash after send, unknown outcome, and circuit
   breaker tests pass.
3. The validator rejects invented IDs, model authored arithmetic, and
   prohibited causal language.

M4 ACTIONS AND SECURITY
1. Self approval, stale revision, duplicate execution, competing
   proposal, and needs_review execution tests pass.
2. A grant revoked mid job forces a rerun or a block.
3. Database role permissions are tested against PostgreSQL.
4. Local identity mode refuses to start outside DEPLOY_ENV=local.
5. Seeded grants match section 11.3.

M4.5 MINIMUM DEPLOYMENT
1. Preflight passes.
2. CDK deploys the full stack.
3. The one off migration task, source import, scenario generation, and
   user seeding complete in AWS.
4. Authenticated HTTPS smoke tests pass for all four users.
5. A cost snapshot is recorded.

M5 EVALUATION AND SYSTEM CHECKS
1. The gold set is reviewed by the owner and frozen.
2. B0, B1, and the candidate run across both models and both modes
   within the eval budget.
3. Local MLflow artifacts are exported to the repository.
4. A load test with 20 concurrent readers runs against the deployed
   stack.
5. SQS and Bedrock failure drills run against the deployed stack and are
   recorded.

M6 UI, DEMO, AND TEARDOWN
1. All four views are complete.
2. The 3:40 demo is recorded, including the ungranted viewer and the
   crash and redelivery drill.
3. Static /evidence/ and /sandbox/ builds make zero API calls.
4. Architecture diagrams match the deployed system.
5. Teardown dry run prints the tagged inventory.
6. Teardown runs and the actual resource status is documented.

Reporting after each milestone: write docs/progress/Mx.md with passed
checks, failed checks, blocked or unrun checks, exact commands, measured
values, evidence paths, open gaps, gate status, and actual hours spent.
Never report an unmeasured number as a result.

Planning estimate: 180 to 240 focused hours.

============================================================
19. TEARDOWN
============================================================

Before teardown: export sanitized evidence, pin configuration and
ontology versions, record the live video, and verify both static
interfaces.

Teardown runs a dry run of the tagged resource inventory first and acts
only on project tagged resources. Handle the RDS snapshot choice
explicitly. Remove ECS services and tasks, the ALB, the database, queues,
temporary storage, secrets, logs, and public IPv4 resources as
appropriate. Report retained resources and their remaining costs. State
that paid resources are stopped only after verification. Never imply
that retained snapshots or storage are free.

============================================================
20. REPOSITORY AND COMMANDS
============================================================

Repository layout:

README.md
AGENTS.md
pyproject.toml
uv.lock
Dockerfile
compose.yaml
backend/ops/
  api.py, worker.py, settings.py, auth.py, cli.py
  ontology/ (models.py, registry.py, definitions.yaml)
  queries/
  commands/
  agents/ (planner.py, analyst.py, contracts.py, validator.py)
  providers/ (bedrock.py, fixture.py)
  jobs/ (outbox.py, consumer.py, checkpoints.py, breaker.py)
  data/ (importer.py, manifest.py, scenario.py)
  evals/ (runner.py, gold.py, metrics.py)
frontend/src/ (views, components, adapters, types)
db/ (Alembic migrations)
infra/ (app.py, stack.py)
scripts/ (preflight, seed, export, teardown)
configs/ (models.yaml, policy.yaml, price_card.yaml)
data/ (raw/olist, manifest.json, as_of_candidates.json, fixtures, gold)
docs/ (prd.md, business_case.md, decisions.md, ontology.md, timing_protocol.md,
  results.md, pilot.md, architecture.drawio, architecture.svg, progress/)
tests/ (unit, integration, e2e)
.github/ (copilot-instructions.md, workflows/ci.yml)

Write the persistent agent instructions to AGENTS.md at the repository
root. Keep .github/copilot-instructions.md as an identical copy. Create
docs/prd.md from this specification as a repository reference. It is a
setup output, not a missing input.

Required CLI commands, each with --help, clear errors, and a nonzero
exit on failure:
ops data import --directory data/raw/olist
ops data validate
ops data pick-as-of
ops scenario generate --seed 42 --scenario base-v1
ops migrate
ops seed-users --mode local|aws
ops eval --suite frozen
ops worker --queue fixture|sqs --provider fixture|bedrock
ops recover-job
ops export-demo
ops preflight --cloud aws

Local setup runs PostgreSQL 16 through compose.yaml with the fixture
queue, fixture provider, and AUTH_MODE=local, and needs no AWS
credentials. Local fixture runs never count as deployed acceptance
checks.

Local command contract:
uv sync --locked
docker compose up -d postgres
uv run ops migrate
uv run ops data import --directory data/raw/olist
uv run ops data validate
uv run ops data pick-as-of
uv run ops scenario generate --seed 42 --scenario base-v1
uv run ops seed-users --mode local
uv run uvicorn ops.api:app --host 127.0.0.1 --port 8000
uv run ops worker --queue fixture --provider fixture
uv run pytest
npm --prefix frontend ci
npm --prefix frontend run build
uv run ops eval --suite frozen
uv run ops preflight --cloud aws

============================================================
21. FIRST ACTION
============================================================

Inspect the workspace. Then write a short report that covers:
1. Any existing implementation.
2. Missing inputs, including the Olist files, the second model ID, the
   domain, and AWS account access.
3. Any remaining ambiguity in this specification.
4. Your milestone plan from M1 through M6, including M4.5.

Then implement M1.

Do not start with decorative UI work, paid cloud provisioning, or
invented benchmark results. Keep the implementation bounded to this
specification.