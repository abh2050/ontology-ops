"""Frozen evaluation runner (spec 14.2 and 14.4).

Comparators: B0 (deterministic tools, no model), B1 (flat evidence), and the
candidate (typed ontology evidence and traversal). B1 and the candidate run on both
configured models and both modes; real-only items run in both modes and scenario
items only with the scenario enabled. Paid calls are admitted against the separate
evaluation budget in eval_runs (ceiling from configs/policy.yaml), never the live cap.
Jobs run through the same consumer code path as production, at most two at a time.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from ops.agents import analyst, planner
from ops.data.users import seed_users
from ops.db import engine
from ops.evals import gold as G
from ops.evals.metrics import score_item, summarize
from ops.jobs.breaker import CircuitBreaker
from ops.jobs.consumer import WorkerDeps, process_job
from ops.jobs.outbox import JobRequest, QuestionFilters, SubmitError, submit_job
from ops.ontology.registry import ONTOLOGY_VERSION
from ops.queries import tools as T
from ops.queries.scope import load_principal
from ops.settings import REPO_ROOT, load_config

TS = "%Y-%m-%d %H:%M:%S"
MODES = ("real_only", "scenario_enabled")
COMPARATORS = ("b1", "candidate")
MODEL_KEYS = ("default", "second")


@dataclass(frozen=True)
class Cell:
    item_id: str
    comparator: str
    model_key: str
    mode: str


@dataclass
class EvalConfig:
    provider: str = "fixture"            # fixture | bedrock
    comparators: tuple[str, ...] = COMPARATORS
    model_keys: tuple[str, ...] = MODEL_KEYS
    modes: tuple[str, ...] = MODES
    item_ids: tuple[str, ...] | None = None
    out_root: Path = field(default_factory=lambda: REPO_ROOT / "docs" / "evidence" / "eval")


def plan(gold: dict, cfg: EvalConfig) -> list[Cell]:
    cells = []
    for it in gold["items"]:
        if cfg.item_ids and it["id"] not in cfg.item_ids:
            continue
        for mode in cfg.modes:
            if it["requires_scenario"] and mode == "real_only":
                continue
            for comparator in cfg.comparators:
                for model_key in cfg.model_keys:
                    cells.append(Cell(it["id"], comparator, model_key, mode))
    return cells


def planned_calls(cells: list[Cell]) -> int:
    return 2 * len(cells)


# ---- B0: deterministic workspace ----------------------------------------------------


def b0_outcome(item: dict, mode: str) -> dict:
    """What an analyst gets from the deterministic SQL queue and record views alone."""
    as_of = datetime.strptime(item["as_of"], TS)
    scenario = item["scenario_id"] if mode == "scenario_enabled" else None
    out: dict = {"deterministic": True, "state": "ready", "action": None, "metrics": {},
                 "validation": {"ok": True, "proposal_state": "pending", "rejections": [],
                                "causal_rejections": 0}}
    with engine("api").connect() as conn:
        p = load_principal(conn, item["subject"], item["batch_id"])
        t = item.get("target")
        try:
            if item["category"] == "aggregate":
                f = item["filters"]
                page = T.find_late_orders(conn, p, T.FindLateOrdersInput(
                    as_of=as_of, customer_state=f.get("customer_state"), limit=1))
                out["metrics"] = {"aggregates": page.aggregates.model_dump()}
                return out
            if t["target_type"] == "Order":
                snap = T.get_order_snapshot(conn, p, T.OrderSnapshotInput(
                    order_id=t["target_id"], as_of=as_of))
                out["cited_sellers"] = sorted({li.seller_id for li in snap.lines})
                if snap.order.late_open and item["category"] != "unanswerable":
                    out["action"] = {"kind": "CreateInvestigation", "target_type": "Order",
                                     "target_id": t["target_id"],
                                     "selected_order_ids": [t["target_id"]]}
            else:
                scope = T.get_seller_exception_scope(conn, p, T.SellerScopeInput(
                    seller_id=t["target_id"], as_of=as_of))
                if item["category"] != "unanswerable":
                    out["action"] = {"kind": "CreateInvestigation", "target_type": "Seller",
                                     "target_id": t["target_id"],
                                     "selected_order_ids": [o.order_id for o in scope.orders]}
                out["metrics"] = {"selected_orders": scope.aggregates.late_open_orders,
                                  "seller_line_value_centavos":
                                      scope.aggregates.seller_line_value_centavos}
            if scenario:
                ctx = T.get_disruption_context(conn, p, T.DisruptionContextInput(
                    target_type=t["target_type"], target_id=t["target_id"], as_of=as_of,
                    scenario_id=scenario))
                out["cited_events"] = [e.event_id for e in ctx.events]
        except T.NotVisible:
            out.update(not_visible=True, state="refused")
    return out


# ---- model comparators -------------------------------------------------------------------


def _request(item: dict, cell: Cell) -> JobRequest:
    t = item.get("target") or {}
    return JobRequest(
        target_type=t.get("target_type"), target_id=t.get("target_id"),
        as_of=datetime.strptime(item["as_of"], TS),
        scenario_id=item["scenario_id"] if cell.mode == "scenario_enabled" else None,
        filters=QuestionFilters(customer_state=(item.get("filters") or {}).get(
            "customer_state")),
        model_key=cell.model_key, comparator=cell.comparator, question=item["question"][:300])


def _submit(item: dict, cell: Cell, run_id: str) -> tuple[str | None, dict]:
    key = f"eval:{run_id}:{cell.item_id}:{cell.comparator}:{cell.model_key}:{cell.mode}"
    try:
        with engine("api").begin() as conn:
            p = load_principal(conn, item["subject"], item["batch_id"])
            job_id, _ = submit_job(conn, p, _request(item, cell), key, eval_run_id=run_id)
        return job_id, {}
    except T.NotVisible:
        return None, {"not_visible": True, "state": "refused"}
    except SubmitError as exc:
        return None, {"state": "submit_error", "error": exc.detail}


def _job_outcome(job_id: str) -> dict:
    with engine("admin").connect() as conn:
        row = conn.execute(text("SELECT state, result, created_at FROM jobs WHERE job_id = :j"),
                           {"j": job_id}).one()
        calls = conn.execute(text("SELECT stage, state, model_id, usage FROM model_calls "
                                  "WHERE job_id = :j"), {"j": job_id}).all()
    result = row.result or {}
    analysis = result.get("analysis")
    return {"job_id": job_id, "state": row.state, "analysis": analysis,
            "action": (analysis or {}).get("action"), "validation": result.get("validation"),
            "metrics": result.get("metrics"), "reason": result.get("reason"),
            "tools_run": result.get("tools_run"),
            "calls": [{"stage": c.stage, "state": c.state, "model_id": c.model_id,
                       "usage": c.usage} for c in calls]}


def _provider(kind: str):
    if kind == "fixture":
        from ops.providers.fixture import FixtureProvider

        return FixtureProvider()
    from ops.providers.bedrock import BedrockProvider

    return BedrockProvider(load_config("models")["region"])


def _cost(outcomes: list[dict], card: dict) -> dict:
    models = load_config("models")
    rates = {models["default_model_id"]: card["models"]["default_model_id"],
             models["second_model_id"]: card["models"]["second_model_id"]}
    tokens_in = tokens_out = 0
    usd = 0.0
    unknown_calls = 0
    for o in outcomes:
        for c in o.get("calls", []):
            u = c.get("usage") or {}
            if c["state"] != "complete" or u.get("input_tokens") is None:
                unknown_calls += 1 if c["state"] in ("sent", "unknown") else 0
                continue
            r = rates[c["model_id"]]
            tokens_in += u["input_tokens"]
            tokens_out += u["output_tokens"]
            usd += (u["input_tokens"] * r["input_per_1k_tokens_usd"]
                    + u["output_tokens"] * r["output_per_1k_tokens_usd"]) / 1000
    return {"input_tokens": tokens_in, "output_tokens": tokens_out,
            "inference_usd_list_price": round(usd, 6), "calls_with_unknown_cost": unknown_calls}


def run(cfg: EvalConfig, *, confirm_paid: bool = False) -> dict:
    meta = G.verify_frozen()
    gold = G.load_gold()
    items = {it["id"]: it for it in gold["items"]}
    cells = plan(gold, cfg)
    calls = planned_calls(cells)
    ceiling = load_config("policy")["eval"]["ceiling_calls_per_full_run"]
    print(f"planned model jobs {len(cells)}, planned model calls {calls} (ceiling {ceiling}), "
          f"provider {cfg.provider}")
    if calls > ceiling:
        raise RuntimeError("planned calls exceed the evaluation ceiling; refusing to start")
    if cfg.provider == "bedrock" and not confirm_paid:
        raise RuntimeError("paid run: re-run with --confirm-paid after reviewing the plan")

    seed_users("local")
    run_id = str(uuid.uuid4())
    with engine("worker").begin() as conn:
        conn.execute(text("INSERT INTO eval_runs (eval_run_id, planned_calls, ceiling) "
                          "VALUES (:r, :p, :c)"), {"r": run_id, "p": calls, "c": ceiling})
    deps = WorkerDeps(engine=engine("worker"), provider=_provider(cfg.provider),
                      breaker=CircuitBreaker())
    started = time.time()

    def execute(cell: Cell) -> tuple[Cell, dict]:
        item = items[cell.item_id]
        t0 = time.perf_counter()
        job_id, early = _submit(item, cell, run_id)
        if job_id is None:
            return cell, {**early, "latency_s": None}
        while process_job(job_id, deps) == "retry":
            time.sleep(0.5)
        return cell, {**_job_outcome(job_id), "latency_s": time.perf_counter() - t0}

    with ThreadPoolExecutor(max_workers=2) as pool:  # at most two concurrent jobs
        results = list(pool.map(execute, cells))

    b0 = {(iid, mode): b0_outcome(items[iid], mode) for iid in {c.item_id for c in cells}
          for mode in cfg.modes if not (items[iid]["requires_scenario"] and mode == "real_only")}

    cell_groups: dict[tuple, list] = {}
    raw = []
    for cell, outcome in results:
        item = items[cell.item_id]
        s = score_item(item, outcome)
        cell_groups.setdefault((cell.comparator, cell.model_key, cell.mode), []).append(
            (item, outcome, s))
        raw.append({"cell": cell.__dict__, "outcome": outcome, "score": s})
    for (iid, mode), outcome in b0.items():
        s = score_item(items[iid], outcome)
        cell_groups.setdefault(("b0", "none", mode), []).append((items[iid], outcome, s))
        raw.append({"cell": {"item_id": iid, "comparator": "b0", "model_key": "none",
                             "mode": mode}, "outcome": outcome, "score": s})

    card = load_config("price_card")
    models = load_config("models")
    summary = {}
    for (comparator, model_key, mode), rows in sorted(cell_groups.items()):
        entry = summarize(rows)
        if comparator == "b0":
            entry["model_id"] = "not applicable (deterministic)"
            entry["inference"] = "not applicable"
            entry["latency_p50_s"] = entry["latency_p95_s"] = "not applicable"
        else:
            entry["model_id"] = models[f"{model_key}_model_id" if model_key == "second"
                                      else "default_model_id"]
            entry["inference"] = _cost([o for _, o, _ in rows], card)
        summary[f"{comparator}|{model_key}|{mode}"] = entry

    with engine("admin").connect() as conn:
        admitted = conn.execute(text("SELECT admitted_calls FROM eval_runs WHERE eval_run_id = :r"),
                                {"r": run_id}).scalar_one()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            cwd=REPO_ROOT).stdout.strip()
    prompt_hash = hashlib.sha256((planner.SYSTEM + analyst.SYSTEM).encode()).hexdigest()
    report = {
        "eval_run_id": run_id, "provider": cfg.provider, "started_utc":
            datetime.fromtimestamp(started, UTC).isoformat(),
        "wall_seconds": round(time.time() - started, 1), "gold_hash": meta["gold_hash"],
        "gold_reviewer": meta["reviewer"], "ontology_version": ONTOLOGY_VERSION,
        "code_commit": commit, "prompt_hash": prompt_hash,
        "planned_calls": calls, "admitted_calls": admitted, "ceiling": ceiling,
        "limits": load_config("policy")["live_limits"],
        "source_hashes": json.loads((REPO_ROOT / "data" / "manifest.json").read_text())["files"],
        "as_of_values": gold["as_of_values"], "summary": summary,
    }
    out = cfg.out_root / f"{datetime.now(UTC):%Y%m%dT%H%M}-{cfg.provider}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (out / "raw_results.json").write_text(json.dumps(raw, indent=2, default=str) + "\n")
    _log_mlflow(report, out)
    report["out_dir"] = str(out.relative_to(REPO_ROOT))
    return report


def _log_mlflow(report: dict, out: Path) -> None:
    """Local MLflow tracking only (no hosted service); one run per comparator cell."""
    try:
        import mlflow
    except ImportError:
        return
    mlflow.set_tracking_uri(f"sqlite:///{REPO_ROOT / 'mlruns' / 'mlflow.db'}")
    (REPO_ROOT / "mlruns").mkdir(exist_ok=True)
    mlflow.set_experiment(f"ontology-ops-eval-{report['provider']}")
    exported = []
    for key, entry in report["summary"].items():
        comparator, model_key, mode = key.split("|")
        with mlflow.start_run(run_name=key) as r:
            mlflow.log_params({
                "comparator": comparator, "model_id": entry["model_id"], "mode": mode,
                "ontology_version": report["ontology_version"],
                "gold_hash": report["gold_hash"], "code_commit": report["code_commit"],
                "prompt_hash": report["prompt_hash"], "eval_run_id": report["eval_run_id"],
                "as_of_values": ",".join(report["as_of_values"]),
                "source_hashes": json.dumps({k: v["sha256"][:12] for k, v in
                                             report["source_hashes"].items()}),
                "limits": json.dumps(report["limits"])[:480]})
            numeric = {k: v for k, v in entry.items() if isinstance(v, int | float)
                       and not isinstance(v, bool)}
            if isinstance(entry.get("inference"), dict):
                numeric.update({f"inference_{k}": v for k, v in entry["inference"].items()})
            mlflow.log_metrics(numeric)
            mlflow.log_artifact(str(out / "report.json"))
            exported.append({"mlflow_run_id": r.info.run_id, "name": key, "metrics": numeric})
    (out / "mlflow_export.json").write_text(json.dumps(exported, indent=2) + "\n")
