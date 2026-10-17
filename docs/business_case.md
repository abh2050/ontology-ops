# Business Case and Build Decision

**Project:** Ontology Driven Operational AI (supply chain delivery exception investigation on AWS)
**Owner:** Abhishek Shah
**Document status:** Base case written before the build on October 17, 2026. Every number in this version is an assumption. After the build, the measured columns replace the assumptions, and the decision section records the outcome.

## 1. Decision this document supports

A marketplace operations leader must decide whether to fund a limited pilot of an ontology assisted workflow for investigating late deliveries. The pilot proceeds only if measured results show that the workflow saves analyst time and prevents costly errors without weakening authorization or approval controls. If a simpler deterministic workspace delivers most of the value, this document recommends that workspace instead.

## 2. Business problem

Operations analysts investigate late orders by joining order, seller, customer, and product records by hand. This manual work causes three problems. Analysts spend 10 to 15 minutes assembling evidence for each case. Analysts open separate tickets for late orders that share one seller, so the team investigates the same issue many times. Analysts sometimes attribute a late order to the wrong seller or count a multi seller order twice, and those errors trigger seller disputes and inflate the exposure figures that leadership uses.

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
| Monthly late delivery exceptions | 1,000 | Illustrative mid size marketplace | | Customer pilot |
| Analyst loaded cost | $45 per hour | Illustrative | | Customer pilot |
| Minutes per investigation today | 12 | Illustrative | | Timing study, B0 baseline |
| Minutes per investigation with product | 8 | Target of 25 percent or more faster | | Timing study, candidate |
| Share of exceptions that belong in a group | 30 percent | Illustrative | | Benchmark and Olist data at default as_of |
| Average orders per grouped case | 4 | Illustrative | | Olist data at default as_of |
| Wrong attributions per month today | 20 | Illustrative, 2 percent of cases | | Customer pilot |
| Wrong attributions per month with product | 5 | Target | | Benchmark error rates |
| Cost per wrong attribution | $200 | Illustrative rework and dispute cost | | Customer pilot |
| Hosting and inference per month | $150 | Provisional estimate | | Measured AWS and Bedrock cost |
| Maintenance per month | 4 hours at $75 | Illustrative | | Build log |
| Build cost | $24,000 (240 hours at $100) | Project estimate | | Actual hours in docs/progress |
| Integration with a real ERP | $40,000 | Illustrative | | Customer pilot |

## 5. Base case calculation

1. Grouping reduces investigations. Thirty percent of 1,000 exceptions is 300 orders. Those 300 orders fold into 75 cases. The team now handles 700 single cases plus 75 grouped cases, which is 775 investigations.
2. Time today equals 1,000 cases at 12 minutes, which is 200 hours.
3. Time with the product equals 775 cases at 8 minutes, which is about 103 hours.
4. The team saves about 97 hours per month. At $45 per hour, that saving is worth about $4,350.
5. Wrong attributions fall from 20 to 5. Fifteen avoided errors at $200 each save $3,000.
6. Gross monthly value is about $7,350.
7. Running cost is $150 for hosting and inference plus $300 for maintenance, which is $450.
8. Net monthly value is about $6,900, or about $82,800 per year.
9. Total investment is $64,000. Payback takes about 9 months. First year ROI is about 30 percent. Later years return more because the build cost is already paid.

## 6. Scenarios

| Scenario | Monthly exceptions | Minutes per case | Grouping effect | Wrong attributions per month | Net monthly value | Payback on $64,000 |
|---|---|---|---|---|---|---|
| Conservative | 1,000 | 12 to 10 | 10 percent fewer cases | No change | About $1,950 | About 33 months |
| Base | 1,000 | 12 to 8 | 1,000 down to 775 | 20 down to 5 | About $6,900 | About 9 months |
| Strong | 5,000 | 12 to 8 | 5,000 down to 3,875 | 100 down to 25 | About $35,000 | About 2 months |

The strong scenario assumes running cost rises to $1,500 per month at the higher volume.

## 7. Sensitivity

Monthly exception volume decides the investment. Below about 1,000 exceptions per month, time savings alone do not repay the integration cost. Grouping and error reduction contribute more value than faster investigation. The cost per wrong attribution is the most uncertain input and the one a pilot must measure first.

## 8. Decision rules

The project recommends a pilot only when every gate below passes.

| Gate | Threshold | Source | Result (fill after build) |
|---|---|---|---|
| Investigation task success | At least 90 percent | Frozen benchmark | |
| Relationship precision and recall | At least 0.95 each | Frozen benchmark | |
| Aggregate correctness | 100 percent | Deterministic tests | |
| Unsupported causal claims accepted | Zero | Validator and benchmark | |
| Authorization failures accepted | Zero | Security suite | |
| Approval integrity failures accepted | Zero | Security suite | |
| Candidate beats B0 on task success or error rate | Meaningful margin (defined below) | Comparator results | |
| Projected net value with measured inputs | Base scenario or better | Section 5 recomputed | |

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
| Decision | |
| Date | |
| Gates passed | |
| Gates failed | |
| Measured net monthly value | |
| Recommended next step | |
