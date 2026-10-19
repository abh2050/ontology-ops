# Results

All numbers below are **measured** unless labelled estimate or assumption. Targets are not results.

- **Model comparison scope.** Both configured models are Amazon Nova (`amazon.nova-lite-v1:0` and the global profile `global.amazon.nova-2-lite-v1:0`). This is a **within-family generation comparison, not a cross-vendor comparison**.
- **Human timing improvement is untested.** No participants have been recorded; see `docs/timing_protocol.md`.

## Evaluation run of record
- **Run:** `docs/evidence/eval/20261018T1745-bedrock/` (`report.json`, `raw_results.json`, `mlflow_export.json`), 2026-10-18.
- **Gold set:** gold-v1, frozen; hash `be3636d9…` (see `data/gold/FREEZE.json`). The freeze was authorized by the owner in session; an item-by-item review was not separately evidenced.
- **Inputs:** ontology `operational-commerce-v1`; Olist batch `olist-full-v1-d689b1282dbe` and authored `fixtures-v1`; synthetic scenario `base-v1` (seed 42).
- **Execution:** 412 planned model jobs (824 planned calls, ceiling 1,500). 404 jobs ran; 8 cells were correctly refused before a job existed (the hidden-order item). 783 paid calls were admitted to the evaluation budget, not the live cap. At most two concurrent jobs. Wall time 613 s.
- **Where it ran:** the owner's laptop against the local PostgreSQL copy of the same data, with Bedrock in us-east-2, through the production consumer code path. These are not jobs on the deployed stack.
- **Earlier attempts, kept for the record and not used:** an aborted run (AWS session expiry after 91 calls) and `20261018T1729-bedrock` (invalid; see its `INVALID.md`).

## Comparator results (gold-v1)
Task success = share of items where every rubric rule passes. P/R = relationship precision and recall against the canonical SQL affected sets.

| Comparator | Model | Mode | Task success | P | R | Aggregate correctness | Evidence coverage | Invented-ID items | Causal rejections | Causal accepted | Failed jobs (of items) | Job p50 / p95 (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 | n/a (deterministic) | real only | **1.000** | 1.000 | 1.000 | 1.0 | n/a | 0 | 0 | 0 | 0 / 43 | n/a |
| B0 | n/a | scenario | **1.000** | 1.000 | 1.000 | 1.0 | n/a | 0 | 0 | 0 | 0 / 60 | n/a |
| B1 (flat) | Nova Lite | real only | 0.279 | 1.000 | 0.607 | 0.7 | 0.660 | 0 | 9 | 0 | 6 / 43 | 3.30 / 4.27 |
| B1 (flat) | Nova Lite | scenario | 0.250 | 1.000 | 0.528 | 0.6 | 0.652 | 0 | 12 | 0 | 10 / 60 | 3.28 / 4.44 |
| B1 (flat) | Nova 2 Lite | real only | 0.558 | 1.000 | 0.123 | 0.6 | 0.988 | 0 | 0 | 0 | 8 / 43 | 2.97 / 3.99 |
| B1 (flat) | Nova 2 Lite | scenario | 0.417 | 1.000 | 0.090 | 0.4 | 0.953 | 1 | 1 | 0 | 10 / 60 | 2.99 / 3.92 |
| Candidate | Nova Lite | real only | 0.326 | 1.000 | 0.530 | 0.5 | 0.970 | 0 | 12 | 0 | 9 / 43 | 3.34 / 4.07 |
| Candidate | Nova Lite | scenario | 0.467 | 1.000 | 0.491 | 0.9 | 0.984 | 0 | 10 | 0 | 6 / 60 | 3.33 / 4.23 |
| Candidate | Nova 2 Lite | real only | 0.581 | 1.000 | 0.114 | 0.6 | 0.988 | 0 | 0 | 0 | 8 / 43 | 2.85 / 4.09 |
| Candidate | Nova 2 Lite | scenario | 0.417 | 1.000 | 0.066 | 0.5 | 0.933 | 1 | 0 | 0 | 11 / 60 | 3.10 / 3.90 |

**Notes on this table:**
- **Failed jobs** were all `INVALID_MODEL_OUTPUT`: JSON that did not satisfy the strict contract, with no repair loop. 68 of 404 jobs failed (Nova Lite 31, Nova 2 Lite 37).
- **Causal rejections** are reported separately, as the spec requires. Every causal construction the validator caught set the proposal to `needs_review`, so **unsupported causal claims accepted = 0** in every cell.
- **Precision 1.000 everywhere** reflects the design: selections are server-filled or checked against authorized evidence, so a wrong order cannot enter a pending proposal. Recall is where models differ. Nova 2 Lite usually proposes single-order cases instead of the seller group the multi-object items expect.

### Success by question category (B1 and candidate)
| Cell | Direct object | Multi object | Aggregate | Unanswerable |
|---|---|---|---|---|
| Candidate, Nova Lite, real only | 0.19 | 0.25 | 0.50 | 0.60 |
| Candidate, Nova Lite, scenario | 0.40 | 0.30 | 0.90 | 0.50 |
| Candidate, Nova 2 Lite, real only | 0.94 | 0.17 | 0.60 | 0.40 |
| Candidate, Nova 2 Lite, scenario | 0.85 | 0.05 | 0.50 | 0.20 |
| B1, Nova Lite, real only | 0.25 | 0.00 | 0.70 | 0.20 |
| B1, Nova 2 Lite, real only | 0.94 | 0.17 | 0.60 | 0.20 |

## Gates against targets (spec section 3)
| Metric | Target | Measured (candidate, best cell) | Status |
|---|---|---|---|
| Investigation task success | ≥ 0.90 | 0.581 (Nova 2 Lite, real only) | **Fail** |
| Relationship precision / recall | ≥ 0.95 each | precision 1.000; recall ≤ 0.530 | **Fail** (recall) |
| Aggregate correctness (deterministic tests) | 100 % | 100 % in the deterministic test suite; 0.4–0.9 for model jobs, which fail when the model does not complete the question job | Pass (deterministic) / **fail** (model-mediated) |
| Evidence coverage, zero invented IDs | ≥ 95 %, 0 | 0.93–0.99; 1 invented-ID item in 2 Nova 2 Lite cells | **Fail** (invented IDs ≠ 0) |
| Unsupported causal claims accepted | 0 | 0 (43 Nova Lite and 1 Nova 2 Lite causal constructions rejected to needs_review) | Pass |
| Authorization failures accepted | 0 | 0: 20 security scenarios pass locally; deployed smoke 18/18 | Pass |
| Approval integrity failures accepted | 0 | 0: self, stale, duplicate, competing, and needs_review tests pass; deployed crash drill produced 1 case | Pass |
| Human investigation time | ≥ 25 % faster | **untested** | Untested |
| Warm read latency p95 at 20 readers, full data | < 750 ms | **591 ms deployed** (CloudFront → 1 × 0.25 vCPU API task); 189 ms locally | Pass |
| AI job completion, submit to ready p95 | < 60 s | 3.9–4.4 s per cell (evaluation path, no queue wait); deployed jobs 10–16 s, including the 2 s relay poll and SQS | Pass |
| Cost per completed investigation | report | inference: $0.00035 (Nova Lite) and $0.00206 (Nova 2 Lite) per ready job, list price from returned usage; infrastructure: see below | Reported |

### Meaningful margin over B0 (configs/policy.yaml, owner decision 2026-10-17)
- **Rule.** The candidate must gain at least 10 percentage points of task success over B0, or cut B0's combined error rate by at least 50 %, with no auth or approval regression.
- **Measured.** B0 scored 1.000 task success with zero combined errors. The candidate's best cell is 0.581. **The candidate does not beat B0 by the meaningful margin. It is worse on task success in every cell.**
- **Why B0 scores perfectly.** On gold-v1, every expected answer is produced by deterministic queries of the same kind B0 uses, and B0's default answers (investigate the target or its seller group; cause unknown) match the rubric. **Gold-v1 therefore cannot show an advantage for AI assistance.** Any value of the assisted workflow (narrative evidence, speed) is not captured by this benchmark and remains untested.

### Candidate (typed ontology evidence) vs B1 (flat evidence), same facts
- **Nova Lite.** Candidate beats B1 by **+4.7 pp** (real only) and **+21.7 pp** (scenario). Evidence coverage is 0.97–0.98 vs 0.65–0.66.
- **Nova 2 Lite.** Candidate is **+2.3 pp** (real only) and **0 pp** (scenario).

These differences come from a single run per cell (43 and 60 items) and carry sampling noise. No statistical test was run.

## Security, approval, and reliability scenarios
- **20 security and approval scenarios** (`data/gold/security_scenarios.yaml`): all mapped tests pass locally. Deployed checks: S01, S06, and S09 via the HTTPS smoke test (18/18).
- **15 reliability scenarios** (`data/gold/reliability_scenarios.yaml`): all mapped tests pass locally.
- **Deployed failure drills** (`docs/evidence/drills/`), each labelled fault injection:
  - R04 crash before ack + SQS redelivery → 1 case, repeat approval 409.
  - R09 Bedrock read timeout → unknown hold, no retry.
  - R11 five real Bedrock rejections → breaker open, sixth job `PROVIDER_UNAVAILABLE` without admission.
  - R12 poison message → DLQ after 5 receives, DLQ alarm in ALARM.

All four pass.

## Cost
- **Evaluation inference, run of record,** at list price from returned usage:
  - Nova Lite: 545,308 input and 115,574 output tokens, **$0.0605**.
  - Nova 2 Lite: 391,056 input and 88,768 output tokens, **$0.3392**.
  - Total **$0.3997** for 783 admitted calls.
- **All evaluation attempts** combined (aborted ≈ $0.06, invalid ≈ $0.25, record ≈ $0.40): **≈ $0.71**, within the approved worst case of $1.15.
- **Infrastructure (estimate).** About $74.47/month while running (`ops preflight` table). CloudFront, CloudWatch, SQS, S3, ECR, and Cognito are unknown, expected small. Allocated over the business-case assumption of 1,000 investigations/month, that is **≈ $0.074 per investigation (estimate)**.
- **Cost Explorer** had not reported charges at the time of the snapshot (billing lag); see `docs/progress/M4.5.md`. Unknown charges are not zero.

## Limitations
- **Later validation finding.** The M6 live recording exposed acceptance of a synthetic-context finding without synthetic evidence. A citation guard and five regression tests were added after this evaluation. These scores do not measure that correction; see [the retained failure evidence](evidence/demo-validation-gap.md).
- **Benchmark design.** B0 is perfect by construction on gold-v1, so the benchmark can show only whether AI matches deterministic tooling, not whether it helps a human.
- **Evaluation location.** The evaluation ran from the owner's laptop against a local copy of the same data, not on the deployed stack.
- **One run per cell.** Model outputs at temperature 0 still vary between runs (observed: the same seller target produced a valid and an invalid proposal in different runs).
- **Prompt iterations.** Prompts changed twice during M5 after failure analysis (compact output, then minimal whitespace). The run of record uses prompt hash `report.json:prompt_hash`.
- **Gold freeze.** Authorized in session without evidenced item-by-item review.
- **Multi-seller evidence** comes mainly from authored fixtures. Olist has almost no late multi-seller orders at the demo as_of.
- **Human timing:** untested.
