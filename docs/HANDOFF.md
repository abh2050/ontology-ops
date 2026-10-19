> **Final status (2026-10-19):** M1 to M6 complete. The AWS stack and CDKToolkit are **torn down** (`docs/evidence/teardown-20261019.md`). The site is published from `/docs` on GitHub Pages. The new 90-second authored Brag walkthrough is exported and embedded near the top of `docs/index.html` (`docs/assets/case-study/brag-demo.mp4`); this addition is locally verified. Confirm GitHub Pages publication separately from the git push. Everything below is the earlier handoff, kept for history.

# Handoff for the next agent (written 2026-10-18)

Read `AGENTS.md` first. It holds the persistent rules and owner decisions. The full spec is `claude.md` (repository copy `docs/prd.md`). Owner decisions that override the spec are in `docs/decisions.md` (D-001 to D-024).

## Where things stand
- **M1 to M5 passed.** Reports are in `docs/progress/M1.md` … `M5.md`, and the measured results in `docs/results.md`.
- **M6 is in progress.** Read `docs/progress/M6.md`: the React UI is deployed as `m6-demo-20261018`; real Cognito browser PKCE and 18/18 HTTPS smoke checks passed. Genuine video footage is captured with disclosed computer-generated narration; see `docs/demo.md`. The native-AWS diagrams and authored static builds are verified locally. Publication and teardown remain unrun. Continue in this order:
  1. React UI
  2. static builds
  3. architecture diagrams
  4. business case, README, and pilot write-up
  5. demo support
  6. teardown
- **The AWS stack is live and billing** (about $2.45/day, estimate) in **us-east-2** (D-023, account SCP) behind **CloudFront's default domain** (D-024, no custom domain). The app URL is the `OutAppUrl` stack output in `cdk.out/outputs.json`, which is gitignored and contains the account number.
- Current tests: `uv run pytest -q` gives **287 passed**. Frontend Playwright: **5 passed**. Ruff is clean. Current live smoke: `docs/evidence/smoke/smoke-20261018T2303.txt`. CloudFormation is `UPDATE_COMPLETE`; running API/worker use the corrected image with fault injection disabled.
- Recording uncovered a synthetic-citation validation gap; the original internal demo case and failed footage are retained. A narrow guard and five tests were added. See `docs/evidence/demo-validation-gap.md`. M5 evaluation scores predate the fix and are not remeasured results for it. The final live job returned validated findings with no action for an already-cased order; save was refused with 409. The video shows an earlier independently checked case separately, not as approval of that no-action attempt.

## Hard rules (do not break)
- **Region and domain.** Everything runs in us-east-2: infrastructure and Bedrock. There is no custom domain, ACM certificate, or Route 53. Do not move anything to us-east-1; the organization SCP denies the needed services there.
- **No account numbers or ARNs in the repo.** `tests/unit/test_guards.py` enforces this. Mask 12-digit numbers in anything you print or commit.
- **Model IDs only in `configs/models.yaml`.** A test enforces it.
- **The gold set is frozen.** Do not edit `data/gold/*`: `ops eval` checks the hash in `data/gold/FREEZE.json`.
- **Paid actions need the owner's explicit OK first.** That covers Bedrock runs, `cdk deploy`, and teardown. Estimate cost before asking. The owner's global rule is to keep model spend low and ask before anything over a few dollars.
- **Never commit or print secrets or tokens.** Login tokens for scripts live only in memory or in a temporary file that is deleted right after use. DB engines use `hide_parameters=True`; keep it.
- **Never present fixture or mock output as model results or as the live deployment.**
- **Report measured values only.** Label estimates, assumptions, and untested claims as such.

## Environment gotchas
- **AWS credentials.** Profile `awsnew`; `export AWS_PROFILE=awsnew`. `OPS_AWS_ACCOUNT_ID` is in `~/.zshrc`, so run `source ~/.zshrc`. Sessions from `aws login` expire after a few hours. When a command says "session has expired", ask the owner to run `aws login --profile awsnew` **in their own terminal**. An agent shell cannot show them the sign-in URL.
- **zsh.** The shell is zsh: unquoted `$var` does not word-split. Use `${=var}` in loops. This once caused a false "all regions denied" report.
- **CDK.** Node 25 triggers a jsii warning; set `JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1`. The `infra` dependency group holds CDK (`uv run --group infra …`); `cdk.json` already uses it.
- **Local stack.** Start Postgres with `docker compose up -d postgres`. Run `unset VIRTUAL_ENV` before `uv run` if an outside conda or venv is active.
- **Data.** `data/raw/olist/` holds the five Kaggle CSVs. It is gitignored; never commit it.

## Key commands
```
uv run pytest -q
uv run uvicorn ops.api:app --host 127.0.0.1 --port 8000      # local API (AUTH_MODE=local)
uv run ops worker --queue fixture --provider fixture           # local worker, free
uv run ops eval --suite frozen --provider fixture              # free dry run of the evaluation
uv run ops preflight --cloud aws                               # must pass before deploys
uv run python scripts/deploy.py image|release|smoke --tag v1   # see the script docstring
uv run python scripts/smoke_https.py                           # 18 HTTPS checks, 4 users
uv run python scripts/teardown.py                              # DRY RUN: tagged inventory
```
Local test tokens: `python -c "from ops.auth import issue_local_token; print(issue_local_token('operator_a'))"`. Users: `operator_a`, `operator_b`, `reviewer`, `viewer`.

## M6 checklist (spec sections 16, 17, 19, and owner additions)
1. **Frontend** (`frontend/`, implemented locally): React 19, TS 5, Vite, Tailwind 4, TanStack Query, Cytoscape.js. Keep `frontend/package-lock.json`.
   - **Four views** sharing one set of components:
     - **Exception queue:** sort by days overdue, then line value, then order_id. Label the sort a heuristic.
     - **Connected investigation:** Cytoscape graph plus detail drawer plus evidence table. Clicking an edge shows its business meaning; the graph cap (50 nodes) is labelled separately from exact totals.
     - **Action review:** propose, approve or reject, with revision and state.
     - **Evidence and performance:** numbers from `docs/results.md` and `docs/evidence/`.
   - **Every view shows** the batch, the as_of, and "Synthetic scenario" or "Authored" labels where they apply. A seller edge must never read as blame.
   - **Three adapters:**
     - live API: Cognito auth code + PKCE, callback `https://<OutAppUrl>/auth/callback`; locally use local tokens
     - static evidence replay
     - dummy sandbox
   - **API endpoints** (see `backend/ops/api.py`): `/api/meta`, `/api/me`, `/api/queue`, `/api/orders/{id}`, `/api/sellers/{id}/scope`, `/api/graph`, `/api/context`, `POST /api/jobs` (needs an `Idempotency-Key` header), `/api/jobs/{id}` (poll every 2 s with ETag), `POST /api/jobs/{id}/proposal`, `/api/proposals`, `POST /api/proposals/{id}/decision` (`{decision, expected_revision, reason}`), and `/api/cases`.
   - **Serving the UI.** The API must serve the compiled UI from the same origin: add static file serving of `frontend/dist` in `api.py`, with routes not under `/api`. The Dockerfile already builds `frontend/` when `package-lock.json` exists.
2. **Static builds** for GitHub Pages at `/evidence/` and `/sandbox/`. **Authored fixtures only, no Olist rows** (owner decision 8). Label static actions as simulations. No credentials and no API calls; a Playwright test must verify zero network requests to `/api`.
3. **Redeploy the UI** (image push plus `deploy.py release`) only with owner approval. Then rerun `deploy.py smoke`.
4. **Architecture diagrams** that match the deployed system: CloudFront → ALB (HTTP, CloudFront prefix list) → Fargate API → RDS, plus worker ↔ SQS/DLQ ↔ Bedrock, Cognito, S3, ECR, Secrets Manager, and CloudWatch. Produce an editable `docs/architecture.drawio` and `docs/architecture.svg`.
5. **`docs/business_case.md`.** Fill every cell the build measured, from `docs/results.md`. Recompute §5 with measured inputs where available; keep pilot-only inputs labelled as assumptions. Complete the §10 decision table. Per the rules, the measured outcome is: **the candidate does not beat B0 by the meaningful margin, so recommend the deterministic workspace (B0)**. Human timing is untested.
6. **README** in the order spec §17 requires. Write `docs/pilot.md` with the recommendation above.
7. **Demo.** The owner records the 3:40 video on the live stack *before* teardown (spec §17). Help with a script; never fake footage. The crash drill (`scripts/drills.py crash` with `deploy.py release --fault crash_before_ack`) is the "crash and redelivery" segment. Label it fault injection, and clear it afterwards with `deploy.py release --tag v1`.
8. **Teardown** (spec §19), after owner approval and after the video and static builds are verified:
   - Run `scripts/teardown.py` (dry run) first.
   - Then `--execute --rds-snapshot keep|delete`, as the owner chooses.
   - Remove the `CDKToolkit` stack in us-east-2 if the owner wants it gone (empty its bucket first).
   - Report what remains and its cost. Write `docs/progress/M6.md`.

## Where to look
- **Backend:** `backend/ops/`: `api.py`, `auth.py`, `queries/` (tools, scope, graph), `commands/proposals.py`, `jobs/`, `agents/`, `providers/`, and `evals/`.
- **Infrastructure:** `infra/stack.py`, plus `scripts/deploy.py`, `scripts/drills.py`, `scripts/loadtest.py`, `scripts/smoke_https.py`, and `scripts/teardown.py`.
- **Evidence:** `docs/evidence/` (preflight, smoke, latency, explain, eval, drills).
- **Fixture data:** `data/fixtures/labels.json` maps readable labels to fixture IDs (for example `split_ab_00` is the order invisible to both operators).
