# Decisions

Each entry records a choice, its reason, and where it is enforced. Owner decisions are dated.

## D-001 Static seller and product mappings (reconstruction assumption)
Olist gives one seller and one product per order line, with no history. Historical snapshots assume these mappings held at every as_of. Only order event timestamps are masked by as_of.

## D-002 Dataset-local timestamps
Source timestamps have no timezone. Commerce timestamps are stored as `timestamp without time zone` and labelled "dataset local". Application audit timestamps use `timestamptz`.

## D-003 Late open definition (owner decisions 7 and 2026-10-17 overdue cap)
An order is late open at `as_of` when all of these hold:
- `purchased_at <= as_of`
- `date(as_of)` is **1 to 30 days** after `date(estimated_at)`
- `delivered_at` is null or later than `as_of`

Why the 30-day cap: on the full Olist data, the uncapped rule kept every order that never receives a delivery timestamp (orders still "shipped", "processing", "canceled", ... since 2016) late open forever. The spec forbids reading final status or reconstructing cancellations. At the uncapped pick (2018-08-25), only 106 of 2,268 late open orders (about 5 %) were ever delivered. With the purchase window alone (2018-08-18), it was 103 of 1,026. With the window plus the cap, the pick is 2018-03-30 and 643 of 825 are later delivered, which is real in-flight lateness.

The owner chose window plus cap on 2026-10-17, before operational-commerce-v1 was frozen.

- `ops data pick-as-of` counts only orders purchased inside the default queue purchase window (2018-01-01 to 2018-08-31). The window is still only a default filter for queries.
- `line_no` = source `order_item_id`.
- Demo as_of values are end of day (`23:59:59`, dataset local).
- Orders with no lines are excluded from late-open counts because no actor can see them (spec 11.4).
- Enforced in `backend/ops/queries/late_orders.py` (`MAX_OVERDUE_DAYS`), with the cap boundary covered by `tests/integration/test_m1_data.py::test_overdue_cap_boundary`.

## D-004 Carrier assignment rule (synthetic)
`CARRIER_{A..E}` is chosen as `sha256(f"{seller_state}|{customer_state}|{seed}") mod 5`, in code order A–E.

- For multi-seller orders, `seller_state` is taken from the line with the lowest `line_no`.
- `assigned_at` = `carrier_at`. Orders without `carrier_at`, or without lines, get no assignment.
- Carrier display names are deliberately fictional ("Zephyr Otter Fictional Freight", ...).
- The UI carrier edge explanation shows this rule. It comes from the `shipped_by` meaning in `definitions.yaml`.
- Enforced in `backend/ops/data/scenario.py`.

## D-005 Scenario anchoring
Disruption events are authored templates placed relative to the anchor batch's demo as_of. The anchor is the latest Olist batch that has a demo as_of; otherwise `fixtures-v1`.

Event roles:
- Two events overlap as_of: a carrier backlog and a regional weather event.
- `cause_unknown`: a seller stockout on a seller group whose late orders share no backlogged carrier.
- `temporal_decoy`: an outage scoped to a seller that ends before that seller's late orders entered transit.
- `future_masked`: starts after as_of.
- `early_window`.
- `stale_regional_decoy`.

Re-running `ops scenario generate` after the Olist import re-anchors `base-v1` on Olist. Roles are recorded in `data/scenarios/<scenario>.json`.

## D-006 Quarantine reason codes beyond the spec list
The spec requires type and ID-format validation but lists no codes for those failures. Three codes are added:
- `BAD_ID`: an ID is not 32 lowercase hex characters.
- `BAD_TIMESTAMP`: a required timestamp is unparseable or missing.
- `BAD_VALUE`: a malformed state, line number, or numeric attribute.

All eleven spec codes are kept unchanged. If a row has several faults, one code is recorded, in this precedence:
1. Duplicate check.
2. `ORDER_QUARANTINED` cascade (order lines only).
3. Field parse.
4. Order sequence: approved → carrier → delivered-vs-purchase → delivered-vs-carrier.
5. Foreign key.

## D-007 Import loading
The whole import runs in one transaction as the import role, using COPY in batches of 1,000 rows straight into the target tables.

- There is no temp staging table, because validation and deduplication finish in memory before load.
- Re-importing identical files is a no-op that reports the existing batch.
- The same batch id with different content fails.
- Olist batch id = `olist-full-v1-<first 12 hex of sha256 over the five file hashes>`.
- Quarantine IDs are uuid5 values derived from batch, file, row, and reason, so reimports give identical content.

## D-008 Fixture batch as_of
`fixtures-v1` uses the authored as_of `2018-03-15 23:59:59`. `ops data pick-as-of --batch fixtures-v1` still writes ranked candidates, but records the authored as_of as the demo as_of (`selected_by: authored fixture as_of`).

## D-009 Global cross-region inference profile (owner decision, 2026-10-17)
`second_model_id` is `global.amazon.nova-2-lite-v1:0`, invoked from the project region (us-east-2 since D-023; originally specified as us-east-1). Bedrock may route this global profile's requests outside that region. This is a **known deviation from the single-region data boundary**. It is acceptable because the project sends only public Olist data and authored fixtures.

- Preflight must verify the profile is invocable from the project region and fail clearly if it is not.
- No ARN or account number is committed; preflight resolves the account at runtime.
- Both configured models are Amazon Nova, so results are labelled a within-family generation comparison, not a cross-vendor comparison.

## D-010 Least-privilege rule for split orders (owner decision 4, 2026-10-17)
An order is visible only when every seller on it is granted to the actor. An order spanning operator_a and operator_b sellers is therefore invisible to both operators and can never become a case: the reviewer sees it, but cannot approve their own proposal.

This is intended least-privilege behaviour. A security scenario (M4) will prove both operators get no node, count, or total for such an order, and that no case can be created for it.

## D-011 Seller grants (owner decisions 3 and 5, 2026-10-17)
For Olist, take the sellers with at least 1 late open order at the default as_of. Rank them by late open count descending, then by seller_id ascending.

- operator_a gets the top half, and the odd middle seller goes to operator_a.
- operator_b gets all remaining sellers.
- reviewer gets all sellers.
- viewer gets none.

For `fixtures-v1`, grants are authored in `data/fixtures/grants.json` with the same A/B split. `seller_revoked` is granted to operator_a so the mid-job revocation can be tested.

## D-012 Static builds (owner decision 8, 2026-10-17)
Static `/evidence/` and `/sandbox/` builds publish authored fixtures only, not Olist-derived rows.

## D-013 ROI source of truth (owner decisions 1 and 2, 2026-10-17)
`docs/business_case.md` is the ROI source of truth. Spec §3 is kept in `docs/prd.md` as the capacity-only illustration.

"Meaningful margin" is defined in `configs/policy.yaml` and `docs/business_case.md`:
- task success up at least 10 pp, OR
- combined error rate down at least 50 % relative to B0,
- with no authorization or approval regression.

This definition is included in the gold set freeze hash.

## D-014 Local database roles
`compose.yaml` creates non-superuser login roles: `ops_admin` (owns the schema, runs migrations), `ops_import`, `ops_api`, and `ops_worker`. Privileges are granted in migration `0002_role_grants`. Local passwords are fixtures for development only; deployed credentials come from Secrets Manager.

## Deferred services and scale triggers (spec 13)
- Read replica: revisit if p95 warm reads exceed 750 ms at 20 readers after indexing and keyset pagination.
- Scoped result cache: revisit if repeated identical scoped reads dominate load. Keys are principal scope hash, ontology version, batch, as_of, scenario, and filters.
- Fleet-wide circuit breaker: needed once more than one worker runs.
- Separate read store or event sourcing: not planned. Revisit only if command and query contention shows up in measured latency.

## D-015 Process-local circuit breaker
The breaker opens after 5 consecutive known provider failures and stays open for 60 s, then allows one half-open probe. It lives in the worker process (`backend/ops/jobs/breaker.py`). It is **not fleet-wide**, which is correct only while one worker runs, as the spec sizes it. Durable limits do survive restarts, because they live in PostgreSQL: the daily admitted calls and the eval ceiling.

## D-016 Paid call admission and reconciliation
- Every paid stage reserves the unique `model_calls(job_id, stage)` row and increments `usage_days` (live) or `eval_runs` (evaluation) in one transaction.
- `sent` is persisted before the call, and the call runs outside any transaction.
- A completed call and its checkpointed output are written in one transaction, so `complete` always has a reusable output.
- A redelivered job is handled by the stage's slot state:
  - `reserved`: resumes.
  - `sent` or `unknown`: is held as `unknown / RECONCILE_REQUIRED`.
  - `complete`: is reused only while the request, scope, and evidence hashes match.
- `ops recover-job <job_id> [--mark-failed]` shows the hold and can resolve it as failed, with an audit event. Unknown paid outcomes are never retried automatically, and the user regenerates the job.
- A confirmed no-generation rejection (throttling, model not ready, connection refused before send) gets one jittered retry.

## D-017 Proposal hand-off between worker and API
The worker role cannot insert proposals (spec 11.6). The worker stores the analyst's typed action, the validation report, and deterministic metrics in `jobs.result`. The API creates the proposal row from a ready job (M4), re-validating target existence, batch, scenario, ownership, and eligibility at creation.

## D-018 Numbers in model output
The model never authors arithmetic. Every number in analyst text must appear verbatim in the deterministic evidence: integer values, or centavos rendered as reais. Otherwise the validator rejects it as `INCORRECT_ARITHMETIC`. Proposal counts and money come from `deterministic_metrics`.

## D-019 Causal language rule (conservative)
A sentence is rejected when it contains one of "caused", "due to", "because of", "resulted from", or "responsible for" (and close variants), and it also names a seller, carrier, or event, a synthetic event word, or an object ID. Negated forms ("not caused by the carrier") are also rejected. That is deliberately conservative: a false rejection only sends the proposal to `needs_review`.

## D-020 Traversal and comparators
After the planner's tools run, the worker follows the ontology from an Order target to its sellers (`fulfilled_by`), adding at most 3 seller scopes. B1 receives the same tool results, so no facts are withheld, serialized as flat key=value rows without typed structure. The candidate receives typed, compact evidence.

## D-021 Fixture provider
`FixtureProvider` is a deterministic stand-in that reads the same prompt Bedrock would receive and returns schema-shaped JSON. It supports injected faults: timeout, throttle, reject, invalid JSON, causal, invented ID, and arithmetic. Fixture runs never count as model evaluation results.

## D-022 Deployment design (M4.5, prepared and unverified)
- **One CDK stack** (`infra/stack.py`, Python, CDK v2). Fargate runs ARM64 tasks in public subnets with public IPs for outbound HTTPS, so there is no NAT gateway. RDS PostgreSQL 16 is a single-AZ `db.t4g.micro` with 20 GiB gp3, encrypted, with `rds.force_ssl=1`, in private isolated subnets. Port 5432 is open only to the API, worker, and one-off task security groups.
- **Services stay at `desired_count=0`** until the image is pushed and the migration, import, and seeding tasks have run, which follows the spec's deployment sequence. They are released with `-c services_running=true`.
- **One-off ECS tasks each have their own role:**
  - migration: master credentials plus runtime role passwords; it bootstraps `ops_import`, `ops_api`, and `ops_worker`
  - import: S3 `imports/` read, import credentials
  - seeding: Cognito admin, write access to the demo-users secret
- **Task roles.** The API can read S3 and write `exports/`; it has no Bedrock and no queue access. The worker can use the queue and invoke only the two configured models, including the global profile's foundation models in any region.
- **Cognito.** Self sign-up is disabled. The public client uses the authorization code grant with PKCE and an HTTPS callback on the owner's domain. `ALLOW_ADMIN_USER_PASSWORD_AUTH` is enabled only for IAM-authenticated smoke tests; it is never usable from a browser.
- **Nothing account-specific is committed.** No ARN or account number appears in the repo: the certificate ARN is passed as CDK context at deploy time, and `cdk.context.json` is gitignored.
- **Pricing.** List prices were retrieved from the AWS Price List API on 2026-10-17 into `configs/price_card.yaml`. The estimated infrastructure cost is about $74/month, plus inference of about $0.37 (Nova Lite) or $2.71 (Nova 2 Lite) per 1,000 jobs.
- **Image.** The runtime image excludes the `dev` and `eval` dependency groups (734 MB).

## D-023 Single project region us-east-2 for infrastructure and Bedrock (owner decision, 2026-10-17)
The account's AWS Organizations SCP explicitly denies EC2, ECS, RDS, ELB, Cognito, SQS, ECR, CloudFormation, Secrets Manager, and SSM in us-east-1 and us-west-2, and allows them in **us-east-2 (Ohio)**. Only the organization's management account can change the SCP, and the member account's `AccountFullAccessRole` cannot. Amazon Q confirmed us-east-2 as the account's working region. The owner's earlier machine-failure-api project also deployed there.

After briefly requiring us-east-1, the owner chose **us-east-2 for everything**: the CDK stack and Bedrock inference. This is a deviation from spec §15 ("one CDK stack in us-east-1") and §10.6 ("Nova Lite in us-east-1").

- On 2026-10-17 both models were verified invocable from us-east-2: `amazon.nova-lite-v1:0` on demand, and the `global.amazon.nova-2-lite-v1:0` profile ACTIVE (it routes globally, see D-009).
- Bedrock and infrastructure list prices for us-east-2 (USE2-*) equal the us-east-1 rates.
- The ACM certificate and the Route 53 alias must serve the us-east-2 ALB, so the certificate is issued in us-east-2.
- The CDK bootstrap (`CDKToolkit`) exists in us-east-2.

A correction kept for the record: an earlier probe wrongly reported every region as denied, because the loop passed unsplit command strings under zsh.


## D-024 No custom domain: CloudFront default domain for public HTTPS (owner decision, 2026-10-17)
The owner does not want a domain for this demo. Public HTTPS therefore comes from a **CloudFront distribution's default `*.cloudfront.net` domain and AWS-managed certificate**, placed in front of the ALB. There is no ACM certificate, Route 53 zone, or alias record.

**Cognito.** Its callback is `https://<distribution>.cloudfront.net/auth/callback`, an HTTPS callback on an AWS-provided domain. The hosted-UI prefix is derived from a hash of the account, never the raw number.

**ALB.** It listens on HTTP:80 only, and its security group admits only the AWS-managed prefix list `com.amazonaws.global.cloudfront.origin-facing`.

**Caching.** CloudFront forwards `Authorization`, query strings, and all viewer headers except Host. Caching is effectively disabled: TTL 0, max 1 s, and the API sends `private, no-store` on entity responses.

**Deviations from the spec:**
- §15 "ALB with ACM HTTPS" and "a domain the owner controls" are replaced by the CloudFront default domain.
- §15 "All service calls use TLS" is not met on the CloudFront → ALB hop, which is HTTP inside AWS's network. Viewer → CloudFront is TLS, and API → RDS and SDK calls stay TLS.
- CloudFront is a service the spec does not list.

**Residual risk, accepted for a demo.** The prefix list admits any CloudFront distribution, so someone could point their own distribution at the ALB. Every API request still requires a verified Cognito access token and a provisioned user, so this exposes no data.
