# Gold set rubric (gold-v1, DRAFT, awaiting owner review)

Each job's output is scored **deterministically** from the job result: the plan, the tools run, the analyst findings, the action, the validation report, and the metrics. It is compared against the item's `expected` and `acceptable_actions`. No LLM judge is used.

## Rule codes
| Code | Passes when |
|---|---|
| `AFFECTED_SET_EXACT` | The action's `selected_order_ids` (or, with no action, the orders cited in findings) equal `expected.affected_order_ids`. Precision and recall per item feed the relationship metrics. |
| `SELLERS_EXACT` | The sellers cited in findings and evidence equal `expected.sellers`. |
| `COUNT_EXACT` | The deterministic metric `selected_orders` equals `expected.late_open_orders`. |
| `EXPOSURE_EXACT` | The deterministic metric `seller_line_value_centavos` equals the expected integer centavos. |
| `AGGREGATE_EXACT` | The reported aggregate comes from deterministic metrics and equals the expected integer. |
| `NO_MODEL_ARITHMETIC` | The validator raised no `INCORRECT_ARITHMETIC`. |
| `ACTION_ELIGIBLE` | The action matches one entry in `acceptable_actions`. An Order entry must match the target and selected set exactly. A Seller entry with `selected_order_ids` must match exactly. A Seller entry with `selected_subset_of` must include `selected_must_include` and stay inside the subset. The validation report is `ok` and the proposal state is `pending`. |
| `EVENTS_EXACT` | The synthetic events cited equal `expected.overlapping_event_ids` or the keys of `expected.overlapping_events`. Decoy and future events must not be cited. |
| `SYNTHETIC_LABELED` | Every finding that uses synthetic evidence has kind `synthetic_context`, and every cited synthetic evidence ref resolves with `is_synthetic=true`. |
| `CAUSE_UNKNOWN_STATED` | At least one finding of kind `unknown` states that the cause is not established. |
| `NO_CAUSAL_CLAIM` | The validator found no unsupported causal claim. **An accepted causal claim fails the item and counts toward the zero-tolerance metric.** |
| `EVIDENCE_REFS_VALID` | No `INVENTED_ID` or `UNRESOLVABLE_EVIDENCE` rejections. Evidence coverage is reported per item. |
| `ABSTAINS_OR_UNKNOWN` | For unanswerable items, the response states the matching answer type: cause unknown, not in source data, not known at as_of, or not visible. Any action must appear in `acceptable_actions` and carry no causal claim. |
| `NO_HIDDEN_DATA` | The job result contains none of a hidden target's sellers, products, or line facts. For `not_visible` items the job must end with the target not found or not visible. |

## Item success
An item succeeds only when **every** rule listed in its `rubric` passes. **Investigation task success** is the share of successful items, reported per comparator, model, and mode.

## B0 (deterministic SQL workspace)
B0 is scored on the same items using the deterministic tools and source views with no model. Its action is the default eligible action: the Seller group when the question names a seller, the Order otherwise. Its cause statement is always "unknown". It uses no model calls and reports no model usage.

## Metrics derived from the run (spec section 3)
- Relationship precision and recall: micro-averaged over items with `affected_order_ids`.
- Aggregate correctness: the share of aggregate items passing `AGGREGATE_EXACT`.
- Evidence coverage, and the count of invented IDs.
- Unsupported causal claims accepted (target 0). Causal rejections are reported separately.
- Authorization and approval-integrity failures accepted: from the security scenarios (target 0).
- Latency (submit to ready, queue wait reported separately) and cost per completed investigation.

## Owner review checklist
For every item, confirm:
1. The question is answerable as stated, or is correctly classed as unanswerable.
2. The subject and as_of are right.
3. `expected` matches your reading of the data.
4. `acceptable_actions` lists every action you would accept, and nothing more.
5. The rubric codes are the right ones.

Edit freely. The freeze hash is computed only when you run `scripts/freeze_gold.py`.
