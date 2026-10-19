# Portfolio case-study revision — 2026-10-19

## Hero-media addition — approved for push

Git history records this revision. GitHub Pages publication requires separate verification.

The hero now contains a Higgsfield-generated conceptual supply-chain illustration and five-second animation in the established white/navy/cobalt identity. Real application screenshots remain in the product tour. Business copy, benchmark values, architecture and README are unchanged. The new media is explicitly labelled as conceptual artwork and links to the real product section.

The optimized local MP4 is 133,946 bytes and has no audio; the poster is 58,228 bytes. Autoplay is limited to an in-view, visible page with motion allowed. Reduced-motion and data-saving preferences use the still, and a pause/play button provides explicit control. All three product views, six workflow tabs, six architecture components, five policy paths, four model/mode cells, responsive widths, motion controls and fallback checks passed in `scripts/check_case_study.mjs`. Page errors, failed main-page requests and API requests were zero. Desktop/mobile captures and early/middle/late motion frames were inspected. Full research, provenance and verification notes are in [visual-media-notes.md](visual-media-notes.md).

## Revision 2 — business-first, white/navy/cobalt

Revised after owner feedback and approved for push. Git history records the revision; GitHub Pages publication requires separate verification. The opening now names the user, the work and the product: an operations workspace that connects related late orders and prepares an evidence-backed investigation for review. Scattered record research, grouping and reviewer handoff precede implementation details. Positive capability-led headings replace constraint-led headlines; benchmark results and limitations remain accurate and available in the results section.

The main imagery is the real application. Three keyboard-accessible tabs show authored queue, investigation and review captures. A fresh Higgsfield generation supplied a private layout/color reference, not a published mock product or an implementation claim. No generated root-cause assertions, example records or scaling claims were adopted. The previous amber artwork remains unused. Asset provenance is recorded alongside the images.

Styles and interactions are separated into `case-study.css` and `case-study.js`. The revised `scripts/check_case_study.mjs` passed at 1440, 1024, 768, 390 and 320 pixels, including three product views, six workflow tabs, six architecture components, five policy examples, four model/mode cells, keyboard navigation, mobile-menu Escape behavior, working local and source links, images, and default content without JavaScript. It reported zero page errors, failed requests or API requests. `node --check docs/case-study.js` and authored-source whitespace checks passed.

The revised hero, business opportunity, product, architecture and results captures were visually inspected at desktop and mobile widths. QA artifacts are local under `.local/case-study/revision-2/`. No backend code, product behavior, frozen benchmark, cloud resources, video workspace or model evaluation was changed. The guard-suite limitation described below remains from the prior review; the full backend suite was not rerun for this static revision.

## Revision 1 — earlier review record

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
