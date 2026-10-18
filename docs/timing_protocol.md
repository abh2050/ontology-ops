# Human timing protocol (spec 14.5)

**Status: no participants recorded. Human timing improvement is untested.** Developer timing alone does not establish general productivity, and none is reported as a result.

## Purpose
Measure complete task time for delivery-exception investigations in two conditions:
- **B0:** the deterministic workspace, meaning the queue, filters, and record views, with no AI.
- **Candidate:** the ontology-assisted workflow, with an AI proposal and independent approval.

Complete task time **includes verification, correction, and approval**, not just reading the AI output. The claim to test is "at least 25 % faster without lower quality".

## Participants
- Two or three people who did not build the system, if available. Operations or analytics background preferred.
- Each participant uses an `operator` account. The approval step is timed with a separate `reviewer` account, so approval stays independent.

## Consent note (read to each participant before starting)
> This session measures how long investigation tasks take in two versions of an internal tool. It is the tool being evaluated, not you. The data is a public e-commerce dataset (Olist, CC BY-NC-SA 4.0) and authored test data. Some context is labelled "Synthetic scenario" and is not real. We record task start and end times, whether each answer was correct, and any comments you choose to make. We do not record your screen, audio, or personal data beyond a participant code. You may stop at any time without giving a reason, and your records will then be deleted.

## Tasks
There are 12 matched tasks: 6 pairs of equal difficulty. One task of each pair is done in each condition. Tasks come from the frozen gold set; IDs refer to `data/gold/gold_set.yaml`.

| Pair | Task A | Task B | Type |
|---|---|---|---|
| 1 | G001 | G002 | direct order, open an investigation |
| 2 | G009 | G010 | direct order, operator_b scope |
| 3 | G021 | G022 | seller group: exact set and exposure |
| 4 | G023 | G024 | seller group: exact set and exposure |
| 5 | G033 | G035 | seller group with synthetic context; cause stays unknown |
| 6 | G051 | G052 | unanswerable cause or unknown carrier |

## Counterbalancing
- Participants alternate which condition comes first: P1 B0→Candidate, P2 Candidate→B0, P3 B0→Candidate.
- Within a participant, task A of each pair goes to the first condition for odd pairs and to the second condition for even pairs, so each task appears in both conditions across participants.

## Procedure
1. Five minutes of orientation on a fixture example, not timed.
2. For each task, the timer starts when the participant opens the task card. It stops when the internal case is approved, or when the participant records "no action" for unanswerable tasks.
3. Correctness is scored with the same rubric as the benchmark (`data/gold/rubric.md`).
4. Corrections count toward the task time.
5. No help on content is given during timed tasks.

## Analysis
- Report the median task time per condition per participant and overall, plus correctness per condition.
- The claim passes only if the candidate median is at least 25 % lower **and** correctness is not lower.
- With 2–3 participants, report raw values without statistical claims.

## Raw participant timing records
| Participant | Order | Task | Condition | Start (UTC) | End (UTC) | Seconds | Correct | Notes |
|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | No sessions recorded |
