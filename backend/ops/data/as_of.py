"""ops data pick-as-of: scan every day of the demo window and record the default as_of."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import Connection, text

from ops.data.manifest import write_manifest
from ops.db import engine
from ops.queries.late_orders import DEMO_WINDOW, daily_scan, rank_days
from ops.settings import REPO_ROOT

TS = "%Y-%m-%d %H:%M:%S"
FIXTURE_GRANTS = REPO_ROOT / "data" / "fixtures" / "grants.json"


class AsOfError(Exception):
    pass


def resolve_batch(conn: Connection, batch_id: str | None) -> tuple[str, dict]:
    if batch_id is None:
        row = conn.execute(text(
            "SELECT batch_id, manifest FROM source_batches "
            "WHERE manifest->>'provenance' = 'olist' ORDER BY imported_at DESC LIMIT 1"
        )).one_or_none()
        if row is None:
            raise AsOfError(
                "no Olist batch imported; run ops data import --directory data/raw/olist "
                "or pass --batch fixtures-v1"
            )
    else:
        row = conn.execute(
            text("SELECT batch_id, manifest FROM source_batches WHERE batch_id = :b"),
            {"b": batch_id},
        ).one_or_none()
        if row is None:
            raise AsOfError(f"batch {batch_id} not found")
    return row.batch_id, row.manifest


def output_paths(manifest: dict) -> tuple[Path, Path]:
    base = REPO_ROOT / "data" / ("fixtures" if manifest["provenance"] == "authored" else "")
    return base / "as_of_candidates.json", base / "manifest.json"


def demo_as_of(conn: Connection, batch_id: str) -> datetime:
    _, manifest = resolve_batch(conn, batch_id)
    chosen = manifest.get("demo_as_of")
    if not chosen:
        raise AsOfError(f"batch {batch_id} has no demo_as_of; run ops data pick-as-of")
    return datetime.strptime(chosen["as_of"], TS)


def pick_as_of(batch_id: str | None = None) -> str:
    with engine("import").begin() as conn:
        batch_id, manifest = resolve_batch(conn, batch_id)
        days = daily_scan(conn, batch_id, *DEMO_WINDOW)
        if not days or all(d["late_open_orders"] == 0 for d in days):
            raise AsOfError(f"batch {batch_id} has no late open orders in the demo window")
        ranked = rank_days(days)

        def fmt(d: dict) -> dict:
            return {
                "as_of": d["as_of"].strftime(TS),
                "late_open_orders": d["late_open_orders"],
                "sellers_with_3_plus_late_open": d["sellers_with_3_plus"],
                "late_open_multi_seller_orders": d["late_open_multi_seller_orders"],
            }

        chosen = fmt(ranked[0]) | {"selected_by": "ranking"}
        if manifest["provenance"] == "authored":
            # The authored batch has a fixed, documented as_of; the scan stays informational.
            authored = json.loads(FIXTURE_GRANTS.read_text())["as_of"]
            match = next((d for d in days if d["as_of"].strftime(TS) == authored), None)
            if match is None:
                raise AsOfError(f"authored fixture as_of {authored} is outside the demo window")
            chosen = fmt(match) | {"selected_by": "authored fixture as_of"}
        candidates = {
            "batch_id": batch_id,
            "window": [DEMO_WINDOW[0].isoformat(), DEMO_WINDOW[1].isoformat()],
            "as_of_convention": "end of day 23:59:59, dataset local",
            "counted_orders": "purchased inside the window; late open = 1 to 30 days past "
                              "the estimated date with no delivery known at as_of",
            "ranking": "most sellers with >= 3 late open orders, then more late open orders, "
                       "then earlier date",
            "days_evaluated": len(days),
            "top5": [fmt(d) for d in ranked[:5]],
        }
        manifest = {**manifest, "demo_as_of": chosen}
        conn.execute(
            text("UPDATE source_batches SET manifest = CAST(:m AS jsonb) WHERE batch_id = :b"),
            {"m": json.dumps(manifest), "b": batch_id},
        )

    candidates_path, manifest_path = output_paths(manifest)
    candidates_path.write_text(json.dumps(candidates, indent=2) + "\n")
    write_manifest(manifest_path, manifest)
    return (
        f"batch {batch_id}: demo as_of {chosen['as_of']} "
        f"(late open {chosen['late_open_orders']}, sellers>=3 "
        f"{chosen['sellers_with_3_plus_late_open']}, multi seller "
        f"{chosen['late_open_multi_seller_orders']}); candidates -> "
        f"{candidates_path.relative_to(REPO_ROOT)}"
    )
