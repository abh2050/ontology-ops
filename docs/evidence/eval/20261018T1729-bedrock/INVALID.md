# INVALID RUN: do not use these scores

Paid run 2026-10-18 17:29 UTC (eval_run_id in report.json). Its summary is **not a valid evaluation**:

- **Validator crash.** 31 jobs crashed in the validator: an empty server-side selection reached `EligibilityInput`. The jobs stayed `validating`.
- **Blocked submissions.** Those active jobs filled operator_a's 20-active-jobs limit, so 194 of 412 cells were never submitted (`submit_error`).
- **Prompt regression.** The "single compact line" prompt caused 29 malformed-JSON outputs from Nova 2 Lite.

Spend at list price, from returned usage, was about $0.25 (Nova Lite about $0.03, Nova 2 Lite about $0.22). Kept for the record. Fixed in the next commit and superseded by the next paid run.
