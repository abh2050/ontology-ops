# Live demo validation finding · 2026-10-18

During the first genuine M6 browser recording, a real model job in real-only mode
(`scenario_id = null`) returned a finding of kind `synthetic_context`. It cited an
ordinary order reference rather than synthetic evidence. The validator accepted
that reference as resolvable. A separate demo reviewer approved the proposal and
one internal demo investigation was created before this gap was noticed during
footage review. No source commerce record or customer communication was changed.

The original recording and resulting internal case are preserved, not silently
deleted or presented as a successful final demonstration. Raw capture directory:
`.local/demo/capture-2026-10-18T22-45-57-669Z` (gitignored).

The synthetic-table isolation rule remains intact: a null-scenario job reads no
synthetic tables. The defect was acceptance of unsupported model-authored context,
not unauthorized synthetic-data access. A visible synthetic label alone is not
adequate grounding.

## Correction

`ops.agents.validator.validate` now requires every `synthetic_context` finding to
cite at least one actual tool evidence reference marked `is_synthetic = true`.
Merely having synthetic evidence elsewhere in the tool results does not suffice.
Unsupported findings receive `UNRESOLVABLE_EVIDENCE`, zero coverage for that
finding, and cannot yield an approvable proposal.

Five new regression cases cover absent synthetic evidence, uncited synthetic
evidence, a real synthetic citation, false synthetic flags, and empty citations.
Full local suite: **287 passed**; Ruff passed. Final footage is to be captured
with scenario selection explicit, after the corrected release.

The M5 evaluation predates this correction. Its recorded scores remain historical
measurements; no claim is made that they measure the corrected validator. The
frozen gold set, prompts, and old evaluation artifacts are unchanged. No new paid
benchmark was run for this fix.
