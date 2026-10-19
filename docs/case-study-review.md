# Portfolio case-study revision — 2026-10-19

`docs/index.html` is the buildless GitHub Pages portfolio, separate from the React sandbox and the pending video composition. Git history records this revision; a successful push is not, by itself, verification of the GitHub Pages deployment.

## Narrative and evidence

- Business problem → bounded workflow → interactive architecture → evaluation → product judgment.
- Frozen comparison values come from `docs/results.md`. B0 is recommended; human timing and ROI remain untested. The benchmark location and later synthetic-citation finding are disclosed.
- Historical AWS deployment is distinguished from current static demos and the completed teardown.
- Real authored-fixture screenshots and native draw.io AWS symbols are kept distinct from generated conceptual artwork. Asset details are in `assets/case-study/PROVENANCE.md`.
- Sites guidance informed the local, buildless, presentation-led layout and progressive disclosure. Archify validated the optional source-linked request/worker explorer against committed repository evidence. Its candidate source is in `.archify/architecture-case-study-20261019-141512/candidate.json`. Receipts and visual captures are retained locally, not included in this commit; receipts were moved out of the public asset directory after validation, without modifying the HTML.

## Checks performed

`node scripts/check_case_study.mjs` passed: widths 1440, 1024, 768, 390 and 320; no horizontal overflow; six stage tabs with arrow/Home/End keyboard control; six architecture component selectors; five policy paths; four model/mode cells; mobile menu including Escape; local and repository-source links; image loading; no JavaScript errors, failed page requests or API calls. Default content was also checked with JavaScript disabled. Browser captures used reduced-motion mode.

Desktop and mobile captures were visually inspected, including the hero, architecture, evaluation and social preview. Automated Archify validation, delivery, strict checks and browser checks passed; the optional explorer's dark capture was also inspected. Screenshots are local QA artifacts, not additional evaluation results.

Whitespace checks passed for authored source. The generated explorer retains the generator's blank-line whitespace to preserve its validated bytes. `uv run pytest -q tests/unit/test_guards.py` reported five passes and one failure: the account-number scanner treats a binary font in the pre-existing untracked video workspace (`brag-output-2026-10-19-134102/composition/assets/fonts/body.ttf`) as text. No website file was reported by that guard. The unrelated font and guard were left unchanged. The backend/full application test suite was not rerun for this static page change.

## Higgsfield and credentials

One API image-generation request completed and was incorporated as explicitly labelled conceptual art. It contains no source commerce data. The credential was supplied only to the one-shot local process, not to browser code, source files or generated assets. Actual billing was not independently checked. The shared credential should be rotated because it was pasted into chat.

The existing local static server remains available at `http://127.0.0.1:4176/ontology-ops/`. User-facing in-app browser handoff was unavailable; browser QA itself completed successfully before that handoff attempt.
