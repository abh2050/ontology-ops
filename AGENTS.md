# Agent instructions: Ontology Driven Operational AI

Persistent rules for any coding agent working in this repository.
`.github/copilot-instructions.md` is an identical copy, so update both together.

The full specification is `claude.md` (r2, 2026-10-17), and `docs/prd.md` is its repository copy.
Owner decisions dated 2026-10-17 amend it. They are recorded below and in `docs/decisions.md`.
If anything here conflicts with the spec, the owner decisions win.

## Product boundary
- Decision supported: whether to open an evidence-supported **internal** investigation for a delivery exception.
- Allowed actions: `CreateInvestigation` (core) and `DraftCustomerUpdate` (secondary, internal, no recipient, never sent). Cut `DraftCustomerUpdate` first if the schedule slips.
- Never contact customers, change source commerce records, move inventory, issue refunds or payments, or claim real causes of delay.
- Do not add product features the spec does not name. Do not add graph DBs, vector DBs, agent frameworks, Kafka, Redis, read replicas, sharding, or other clouds.

## Stack (do not substitute)
React 19, TS 5, Vite, Tailwind 4, TanStack Query, Cytoscape.js · Python 3.12, FastAPI, Uvicorn, Pydantic 2 · PostgreSQL 16, SQLAlchemy 2, psycopg 3, Alembic · boto3 Bedrock Converse with strict client-side Pydantic validation · SQS+DLQ, Cognito PKCE, ECS Fargate, ALB, ACM, RDS, S3, Secrets Manager, ECR, CloudWatch · CDK v2 (Python), GitHub Actions, GitHub Pages · pytest, Ruff, Playwright, MLflow 3 (local only).

## Data rules
- Read exactly five Olist files. Validate every header, including the source spelling `lenght`. Load the full data and never sample.
- Store money as integer centavos, rounded half up with `Decimal`. Never use float arithmetic for money.
- Quarantine invalid rows with a reason code. Never drop or repair them silently. A conflicting duplicate fails the import.
- `order_status` is for data-quality reporting only. No module under `backend/ops/queries`, `backend/ops/agents`, or `backend/ops/commands` may reference it, and a test enforces this.
- Commerce timestamps are timezone-less and labelled "dataset local". Never reveal events after `as_of`.
- Every source table has `provenance` = `olist` | `authored`. Authored fixtures live only in batch `fixtures-v1`.
- Synthetic rows have `scenario_id` and `is_synthetic = true`, and every UI use of them carries a "Synthetic scenario" badge. A job with null `scenario_id` never reads synthetic tables.

## Model and cost rules
- Model IDs appear **only** in `configs/models.yaml`. A test enforces this. Never commit ARNs or AWS account numbers.
- Never substitute a model silently. Preflight must verify every configured model is invocable from us-east-1.
- Disable SDK retries. Never retry an unknown paid outcome. Invalid JSON fails safely, with no repair loop.
- Write one-time content (fixtures, gold set, test cases) by hand in-session, not through paid model APIs. Estimate spend before any paid run and ask the owner before anything over a few dollars. Keep evaluations small.
- The model comparison is a **within-family Nova generation comparison**, not a cross-vendor comparison.

## Security rules
- Role never implies seller scope. An order is visible only when **every** seller on it is granted to the actor.
- Apply authorization before joins, counts, totals, graph construction, caching, and serialization. Hidden IDs never appear in nodes, counts, totals, logs, or errors.
- Orders that span operator_a and operator_b sellers are invisible to both operators and can never become a case. This is the least-privilege rule (owner decision 4).
- A reviewer can never approve their own proposal, and must independently hold scope over every target.

## Owner decisions (2026-10-17)
1. `docs/business_case.md` is the ROI source of truth. The spec §3 math is the capacity-only illustration.
2. Meaningful margin over B0: at least +10 pp task success, OR at least 50 % relative reduction in combined error rate, with no auth or approval regression. It lives in `configs/policy.yaml` and is part of the gold set freeze hash.
3. operator_a receives the top half of sellers with at least 1 late open order at the default as_of. The odd middle seller goes to operator_a.
4. Split operator orders are invisible to both operators (see Security rules).
5. Fixture batch grants follow the same split rule, applied to authored assignments.
6. `provenance` column on all five source tables.
7. Late open means `date(as_of) > date(estimated_at)` with no delivery known at as_of. `line_no` = `order_item_id`.
8. Static builds publish authored fixtures only.
9. The agent drafts the gold set, then stops for owner review.
10. M6 also fills every measurable cell in `docs/business_case.md`, recomputes §5 with measured inputs, and completes the §10 decision table.

## Process
- Milestones run in order: M1 → M2 → M3 → M4 → M4.5 → M5 → M6. Do not start a milestone until the previous gate passes and `docs/progress/Mx.md` is written.
- Never report an unmeasured number as a result. Mark blocked and unrun checks explicitly.
- Never claim a deployment succeeded without verification. Confirm with the owner before paid cloud provisioning.

## Layout
Follow the spec §20 layout, plus `docs/business_case.md`. CLI entry point: `uv run ops --help`.
