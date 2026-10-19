# M6 live release and recording · 2026-10-18

Current release: `m6-demo-20261018`, ARM64. ECR digest:
`sha256:e48fd201deadec8639f88248778e6c2bd536599eca572a41ff2edead45b2090c`.
CloudFormation reached `UPDATE_COMPLETE`. Inspected running API and worker both
use this tag with fault injection disabled. An initial package-download build
failure was retried successfully. No unknown paid model outcome was retried.

Live URL: https://d2lgtpubrvhlii.cloudfront.net. Actual Cognito PKCE browser sign-in
passed for operator, reviewer and viewer. HTTPS smoke: **18/18**,
`smoke/smoke-20261018T2303.txt`. Preflight passed before deployment:
`preflight/preflight-20261018T2237.txt`. Final tests: **287 backend**, **5 browser**,
Ruff clean.

The first recording exposed a synthetic-citation gap after an internal demo case
was created. That case and footage are retained as failure evidence; see
[details](demo-validation-gap.md). A narrow guard and five regression cases were
added. M5 evaluation predates this correction; no new paid benchmark ran.

The later job returned validated findings with no proposed action for an
already-cased order. Save was refused with **409**; no second case was created.
The video separately shows an earlier independently checked case. One case exists
for that proposal; repeat approval returned **409**.

The labelled crash recording observed one worker crash and ready revision **6**.
Recording was interrupted during the fault-clearing rolling release. A read-only
task recovered only the operator-owned job reference. Authenticated readback of
the same job showed unchanged revision, drained queue, one case and repeat approval
**409**, over **346 s**. Capture/recovery is disclosed, not presented as an isolated
automatic-restart benchmark.

Video: **220.021 s**, 1600×900, H.264/AAC, captions and disclosed computer narration.
See the recording notes (video later removed at the owner's request). Static replay is authored-only,
labelled, with zero API requests. Neither video nor static pages is publicly
published. The stack remains live and billing. Teardown requires separate approval
and an RDS snapshot choice.

Hours and actual billed cost are unmeasured. Demo work was estimated below $1
incremental, excluding the existing roughly $2.45/day base estimate.
