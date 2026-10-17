"""Deterministic batch manifest. No import timestamp lives inside it."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ops.data import sources as S

if TYPE_CHECKING:
    from ops.data.importer import ValidatedBatch

SELECTION_VERSION = "full-v1"


def build_manifest(batch: ValidatedBatch, importer_version: str, download_date: date) -> dict:
    counts = batch.quarantine_counts()
    return {
        "batch_id": batch.batch_id,
        "selection_version": SELECTION_VERSION,
        "provenance": batch.provenance,
        "source_url": S.SOURCE_URL if batch.provenance == "olist" else "authored fixtures",
        "license": S.LICENSE if batch.provenance == "olist" else "authored for this project",
        "download_date": download_date.isoformat(),
        "importer_version": importer_version,
        "files": {name: batch.file_stats[name] for name in S.LOAD_ORDER},
        "loaded_rows": batch.loaded_counts(),
        "quarantine_counts": counts,
        "quarantine_total": sum(counts.values()),
        "order_quarantine_cascade": {
            "orders_quarantined": sum(
                1 for q in batch.quarantine
                if q.source_file == S.SOURCES["orders"][0]
                and q.reason_code != "DUPLICATE_IDENTICAL"
            ),
            "order_items_order_quarantined": counts.get("ORDER_QUARANTINED", 0),
        },
        "timestamps": "dataset local, no timezone",
        "demo_as_of": None,
    }


def manifest_hash(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
