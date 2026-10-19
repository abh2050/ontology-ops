# Business Case and Build Decision

**Project:** Ontology Driven Operational AI (supply chain delivery exception investigation on AWS)
**Owner:** Abhishek Shah
**Document status:** Updated October 18, 2026 after M5 and the M6 grouping measurement. Original assumptions are retained for comparison. Measured results, estimates, and untested pilot inputs are labelled separately. The recommendation is the deterministic workspace (B0).

## 1. Decision this document supports

A marketplace operations leader must decide whether to fund a limited pilot of an ontology assisted workflow for investigating late deliveries. The pilot proceeds only if measured results show that the workflow saves analyst time and prevents costly errors without weakening authorization or approval controls. If a simpler deterministic workspace delivers most of the value, this document recommends that workspace instead.

## 2. Business problem

The business hypothesis is that analysts spend time assembling related records, open duplicate investigations, and make attribution or counting errors. The assumed 10–15 minutes of manual work and the cost of disputes have not been measured with customer operations. The build tests evidence assembly and controls; a customer pilot must establish the operational cost of these problems.

## 3. How the product creates value

| Value lever | How the product delivers it | Expected size |
|---|---|---|
| Fewer investigations | The system groups late orders that share a seller into one proposed case | Largest lever at volume |
| Less time per investigation | The system assembles related orders, seller exposure, and evidence automatically | Medium |
| Fewer costly errors | Deterministic validation blocks wrong attribution, double counting, and unsupported blame | Medium to large, depends on cost per error |
| Audit record | Every case records the proposer, the approver, and the evidence hash | Hard to price, matters in regulated or partner sensitive businesses |
| Reuse | A second workflow such as returns triage reuses the ontology and the approval pattern | Lowers the cost of later use cases |

## 4. Base case assumptions

| Input | Assumed value | Source of assumption | Measured value (fill after build) | Measured by |
|---|---|---|---|---|
| Monthly late delivery exceptions | 1,000 | Illustrative mid size marketplace | Untested; one Olist snapshot has 825 late open orders, not a monthly rate | Customer pilot; `docs/evidence/business_case.json` |
| Analyst loaded cost | $45 per hour | Illustrative | Untested | Customer pilot |
| Minutes per investigation today | 12 | Illustrative | Untested; no timing participants | `docs/timing_protocol.md` |
| Minutes per investigation with product | 8 | Target of 25 percent or more faster | Untested | Timing study, candidate |
| Share of exceptions that belong in a group | 30 percent | Illustrative | 603 / 825 = 73.09% potential, in disjoint single-seller groups; observed case reduction untested | Scoped query measurement, default Olist as_of |
| Average orders per grouped case | 4 | Illustrative | 603 / 139 = 4.34 orders per potential group | `docs/evidence/business_case.json` |
| Wrong attributions per month today | 20 | Illustrative, 2 percent of cases | Untested customer rate; B0 has zero combined errors in gold-v1 | `docs/results.md`; customer pilot |
| Wrong attributions per month with product | 5 | Target | Untested customer rate; accepted unsupported causal claims 0, relationship precision 1.000, but candidate quality gates fail | `docs/results.md` |
| Cost per wrong attribution | $200 | Illustrative rework and dispute cost | Untested | Customer pilot |
| Hosting and inference per month | $150 | Provisional estimate | Hosting $74.47/month estimate, other charges unknown; measured inference list-price usage $0.3997 in the record run, $0.00035 / $0.00206 per ready job | `docs/results.md`; billing lag means actual monthly bill is unmeasured |
| Maintenance per month | 4 hours at $75 | Illustrative | Untested recurring effort | Customer pilot |
| Build cost | $24,000 (240 hours at $100) | Project estimate | Actual monetary cost unmeasured; milestone session-time estimates are not a cost ledger | `docs/progress/` |
| Integration with a real ERP | $40,000 | Illustrative | Untested; no ERP integration performed | Customer pilot |

## 5. Base case calculation

This is a **conditional sensitivity calculation, not measured ROI**. The build supplies grouping potential and per-ready-job inference cost. All monthly volume, timing, avoided-error, maintenance, and investment inputs remain assumptions. B0 can perform the same deterministic grouping, so none of this establishes incremental AI value.

1. At the Olist default as_of (2018-03-30 23:59:59, dataset local), the authorized operator queues contain 825 distinct late open orders. Of these, 603 share a seller with another order, forming 139 disjoint groups. There are no multi-seller orders in this snapshot. Potential cases = 825 − 603 + 139 = **361**, not an observed intervention outcome. Operator A has 645 orders / 181 potential cases; B has 180 / 180. Split orders stay excluded from operator measurements.
2. Extrapolating that one snapshot to the assumed 1,000 monthly exceptions gives **437.58 potential investigations** (1,000 × 361 / 825). Generalization to real operations is untested.
3. At the assumed 12 minutes before and 8 minutes after, time is 200 hours before and 58.34 hours after: **141.66 assumed hours saved**, worth **$6,374.55** at the assumed $45/hour. Human timing is untested.
4. The original assumed 20-to-5 attribution improvement contributes **$3,000 assumed value** at $200/error. The benchmark does not support that reduction over B0, which already has zero combined errors.
5. Conditional gross value = **$9,374.55/month**. Hosting is an estimate of **$74.47/month**, plus unknown variable AWS charges. At one default-model ready job per potential investigation, inference is 437.58 × $0.00035 = **$0.15/month estimated from measured per-job usage**; failed jobs and unknown outcomes could increase it. Maintenance remains **$300/month assumed**.
6. Conditional net = **about $9,000/month**, before unknown AWS charges. Conditional payback on the original assumed $64,000 investment is about **7.1 months**; first-year ROI about **68.7%**. These figures depend on untested benefits and cannot justify the candidate pilot.
7. **Measured net monthly value, payback, and ROI cannot be determined.** A B0-first timing study must replace the timing and error assumptions before making a business claim.

## 6. Scenarios

| Scenario | Monthly exceptions | Minutes per case | Grouping effect | Wrong attributions per month | Net monthly value | Payback on $64,000 |
|---|---|---|---|---|---|---|
| Conservative | 1,000 | 12 to 10 | 10 percent fewer cases | No change | About $1,950 | About 33 months |
| Base | 1,000 | 12 to 8 | 1,000 down to 775 | 20 down to 5 | About $6,900 | About 9 months |
| Strong | 5,000 | 12 to 8 | 5,000 down to 3,875 | 100 down to 25 | About $35,000 | About 2 months |

These are the original pre-build illustrative scenarios, not measured outcomes; the updated conditional calculation is in §5. The strong scenario assumes running cost rises to $1,500 per month at the higher volume.

## 7. Sensitivity

Volume, actual analyst time, grouping eligibility, and cost per error drive the investment. A minimum viable volume or payback threshold cannot be established from this build. The next study should measure these inputs for B0 before attributing value to AI assistance.

## 8. Decision rules

The project recommends a pilot only when every gate below passes.

| Gate | Threshold | Source | Result (fill after build) |
|---|---|---|---|
| Investigation task success | At least 90 percent | Frozen benchmark | Fail: best candidate 58.1%; B0 100% |
| Relationship precision and recall | At least 0.95 each | Frozen benchmark | Fail: precision 1.000, candidate recall at most 0.530 |
| Aggregate correctness | 100 percent | Deterministic tests | Pass: deterministic tests; model-mediated results 0.4–0.9 |
| Unsupported causal claims accepted | Zero | Validator and benchmark | Pass: 0 accepted; 44 constructions rejected |
| Authorization failures accepted | Zero | Security suite | Pass: local security suite and deployed smoke; see results |
| Approval integrity failures accepted | Zero | Security suite | Pass: revision/self/duplicate/competing tests and deployed crash drill |
| Candidate beats B0 on task success or error rate | Meaningful margin (defined below) | Comparator results | Fail: B0 1.000 with zero combined errors; best candidate 0.581 |
| Projected net value with measured inputs | Base scenario or better | Section 5 recomputed | Untested: timing and economic inputs missing; conditional sensitivity is not measured value |

**Meaningful margin (defined 2026-10-17, before any evaluation; mirrored in configs/policy.yaml and included in the gold set freeze hash).** The candidate beats B0 when, on the frozen benchmark, either:

1. It improves investigation task success by at least 10 percentage points over B0, or
2. It reduces the combined error rate by at least 50 percent relative to B0. The combined error rate counts wrong attribution, double counting, and unsupported causal claims accepted.

In both cases the candidate must show no regression on the authorization or approval gates.

If the security or approval gates fail, the project makes no business claim. If the candidate does not beat the B0 deterministic workspace by a meaningful margin, the recommendation is to ship B0 and skip the inference and governance cost. If the measured inputs fall to the conservative scenario, the recommendation is to wait for higher volume or to target a second use case that shares the build cost.

## 9. What the build can and cannot prove

The build measures task success, relationship accuracy, aggregate accuracy, error and abstention rates, authorization behavior, latency, and actual cloud and inference cost. Those results replace the benchmark related assumptions in section 4.

The build cannot measure real exception volume, real analyst cost, real cost per wrong attribution, or real ERP integration effort. Only a customer pilot supplies those inputs. The public Olist data contains no outcome of this intervention, so this project never claims reduced delivery delays, refunds, or churn.

## 10. Final decision (fill after build)

| Item | Entry |
|---|---|
| Decision | Recommend the deterministic workspace (B0); do not fund the assisted candidate pilot on this evidence |
| Date | 2026-10-18 |
| Gates passed | Deterministic aggregate correctness, unsupported causal claims accepted, authorization, approval; deployed read latency |
| Gates failed | Candidate task success, relationship recall, zero invented IDs, meaningful margin over B0 |
| Measured net monthly value | Not measurable: human timing, operational error cost, volume and recurring costs remain untested |
| Recommended next step | Run a scoped B0 timing/usability study; revise the assistance benchmark before any new paid evaluation. Keep the current gold set frozen |
