"""Validate the five source files and load them into one batch.

Validation is pure (no database) so it can be tested and hashed deterministically.
Loading runs in a single transaction as the import role, using COPY in batches of
1,000 rows. Invalid rows are quarantined, never silently dropped or repaired.
"""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ops.data import sources as S
from ops.data.manifest import build_manifest, write_manifest
from ops.settings import REPO_ROOT

IMPORTER_VERSION = "importer-1.0.0"
FIXTURE_BATCH = "fixtures-v1"
COPY_BATCH_SIZE = 1000
_QUARANTINE_NS = uuid.UUID("6f1c2a52-7d8e-4b6a-9a51-2f0f1f0c0b11")

TABLE_COLUMNS: dict[str, list[str]] = {
    "customers": ["batch_id", "customer_id", "customer_unique_id", "state", "provenance"],
    "sellers": ["batch_id", "seller_id", "state", "provenance"],
    "products": ["batch_id", "product_id", "category", "provenance"],
    "orders": ["batch_id", "order_id", "customer_id", "purchased_at", "approved_at",
               "carrier_at", "delivered_at", "estimated_at", "order_status", "provenance"],
    "order_items": ["batch_id", "order_id", "line_no", "product_id", "seller_id",
                    "shipping_limit_at", "price_centavos", "freight_centavos", "provenance"],
}


class ImportError_(Exception):  # noqa: N801 - avoid shadowing the builtin
    """The import must fail as a whole (header mismatch, conflicting duplicate, ...)."""


@dataclass(frozen=True)
class QuarantineRow:
    source_file: str
    source_row_number: int
    reason_code: str
    raw_row: dict[str, str]


@dataclass
class ValidatedBatch:
    batch_id: str
    provenance: str
    file_stats: dict[str, dict[str, Any]]
    rows: dict[str, list[tuple]] = field(default_factory=dict)
    quarantine: list[QuarantineRow] = field(default_factory=list)

    def quarantine_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(q.reason_code for q in self.quarantine).items()))

    def loaded_counts(self) -> dict[str, int]:
        return {t: len(self.rows[t]) for t in S.LOAD_ORDER}


@dataclass
class ImportResult:
    batch_id: str
    manifest: dict[str, Any]
    already_present: bool

    def summary(self) -> str:
        m = self.manifest
        verb = "already imported (identical manifest)" if self.already_present else "imported"
        lines = [f"batch {self.batch_id} {verb}"]
        lines += [f"  {t}: {n} loaded" for t, n in m["loaded_rows"].items()]
        lines += [f"  quarantine {r}: {n}" for r, n in m["quarantine_counts"].items()]
        return "\n".join(lines)


# ---- file reading ---------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read(path: Path, expected: list[str]):
    """Yield (line_number, raw dict). Fails the import on any header mismatch."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is not None and header and header[0].startswith("﻿"):
            header[0] = header[0].removeprefix("﻿")
        if header != expected:
            raise ImportError_(
                f"header mismatch in {path.name}: expected {expected}, found {header}"
            )
        for values in reader:
            if len(values) != len(expected):
                raise ImportError_(
                    f"{path.name} line {reader.line_num}: expected {len(expected)} fields, "
                    f"found {len(values)}"
                )
            yield reader.line_num, dict(zip(expected, values, strict=True))


# ---- validation -------------------------------------------------------------------


class _Table:
    """Dedupe by primary key: identical repeats are quarantined, conflicts fail."""

    def __init__(self, name: str, batch: ValidatedBatch):
        self.name = name
        self.file = S.SOURCES[name][0]
        self.batch = batch
        self.raw_by_key: dict[tuple, dict[str, str]] = {}
        self.good: dict[tuple, tuple] = {}
        self.quarantined: set[tuple] = set()

    def seen(self, key: tuple, line: int, raw: dict[str, str]) -> bool:
        previous = self.raw_by_key.get(key)
        if previous is None:
            self.raw_by_key[key] = raw
            return False
        if previous == raw:
            self.quarantine(line, "DUPLICATE_IDENTICAL", raw, key=None)
            return True
        raise ImportError_(
            f"CONFLICTING_DUPLICATE in {self.file} line {line}: key {key} repeats with "
            "different values; the whole import fails"
        )

    def quarantine(self, line: int, reason: str, raw: dict[str, str], key: tuple | None) -> None:
        self.batch.quarantine.append(QuarantineRow(self.file, line, reason, raw))
        if key is not None:
            self.quarantined.add(key)


def validate_sources(directory: Path, batch_id: str | None = None) -> ValidatedBatch:
    directory = Path(directory)
    if batch_id is not None and batch_id != FIXTURE_BATCH:
        raise ImportError_(
            f"only {FIXTURE_BATCH!r} may be named; Olist batch ids derive from file hashes"
        )
    missing = [f for f, _ in S.SOURCES.values() if not (directory / f).is_file()]
    if missing:
        raise ImportError_(f"missing source files in {directory}: {', '.join(missing)}")

    stats: dict[str, dict[str, Any]] = {}
    for name in S.LOAD_ORDER:
        filename, headers = S.SOURCES[name]
        path = directory / filename
        rows = sum(1 for _ in _read(path, headers))  # also checks headers up front
        stats[name] = {"file": filename, "sha256": _sha256(path), "rows": rows}

    if batch_id is None:
        combined = hashlib.sha256(
            "".join(stats[n]["sha256"] for n in S.LOAD_ORDER).encode()
        ).hexdigest()
        batch_id = f"olist-full-v1-{combined[:12]}"
    provenance = "authored" if batch_id == FIXTURE_BATCH else "olist"
    batch = ValidatedBatch(batch_id=batch_id, provenance=provenance, file_stats=stats)

    def read(name: str):
        filename, headers = S.SOURCES[name]
        return _read(directory / filename, headers)

    # customers
    customers = _Table("customers", batch)
    for line, raw in read("customers"):
        key = (raw["customer_id"],)
        if customers.seen(key, line, raw):
            continue
        try:
            customers.good[key] = (
                batch_id,
                S.parse_id(raw["customer_id"], "customer_id"),
                S.parse_id(raw["customer_unique_id"], "customer_unique_id"),
                S.parse_state(raw["customer_state"], "customer_state"),
                provenance,
            )
        except S.FieldError as exc:
            customers.quarantine(line, exc.reason, raw, key)

    # sellers
    sellers = _Table("sellers", batch)
    for line, raw in read("sellers"):
        key = (raw["seller_id"],)
        if sellers.seen(key, line, raw):
            continue
        try:
            sellers.good[key] = (
                batch_id,
                S.parse_id(raw["seller_id"], "seller_id"),
                S.parse_state(raw["seller_state"], "seller_state"),
                provenance,
            )
        except S.FieldError as exc:
            sellers.quarantine(line, exc.reason, raw, key)

    # products
    products = _Table("products", batch)
    for line, raw in read("products"):
        key = (raw["product_id"],)
        if products.seen(key, line, raw):
            continue
        try:
            for col in S.SOURCES["products"][1][2:]:
                S.check_optional_int(raw[col], col)
            products.good[key] = (
                batch_id,
                S.parse_id(raw["product_id"], "product_id"),
                raw["product_category_name"] or None,
                provenance,
            )
        except S.FieldError as exc:
            products.quarantine(line, exc.reason, raw, key)

    # orders
    orders = _Table("orders", batch)
    for line, raw in read("orders"):
        key = (raw["order_id"],)
        if orders.seen(key, line, raw):
            continue
        try:
            order_id = S.parse_id(raw["order_id"], "order_id")
            customer_id = S.parse_id(raw["customer_id"], "customer_id")
            purchased = S.parse_ts(raw["order_purchase_timestamp"], "purchase", required=True)
            approved = S.parse_ts(raw["order_approved_at"], "approved", required=False)
            carrier = S.parse_ts(raw["order_delivered_carrier_date"], "carrier", required=False)
            delivered = S.parse_ts(
                raw["order_delivered_customer_date"], "delivered", required=False
            )
            if raw["order_estimated_delivery_date"] == "":
                raise S.FieldError("MISSING_ESTIMATE", "estimated")
            estimated = S.parse_ts(raw["order_estimated_delivery_date"], "estimated", required=True)
            reason = _order_sequence_reason(purchased, approved, carrier, delivered)
            if reason:
                raise S.FieldError(reason, "timestamps")
            if (customer_id,) not in customers.good:
                raise S.FieldError("BROKEN_FK", "customer_id")
            orders.good[key] = (
                batch_id, order_id, customer_id, purchased, approved, carrier, delivered,
                estimated, raw["order_status"] or None, provenance,
            )
        except S.FieldError as exc:
            orders.quarantine(line, exc.reason, raw, key)

    # order items
    items = _Table("order_items", batch)
    for line, raw in read("order_items"):
        key = (raw["order_id"], raw["order_item_id"])
        if items.seen(key, line, raw):
            continue
        try:
            if (raw["order_id"],) in orders.quarantined:
                raise S.FieldError("ORDER_QUARANTINED", "order_id")
            order_id = S.parse_id(raw["order_id"], "order_id")
            line_no = S.parse_line_no(raw["order_item_id"], "order_item_id")
            product_id = S.parse_id(raw["product_id"], "product_id")
            seller_id = S.parse_id(raw["seller_id"], "seller_id")
            shipping_limit = S.parse_ts(raw["shipping_limit_date"], "shipping_limit", required=True)
            price = S.parse_money_centavos(raw["price"], "price")
            freight = S.parse_money_centavos(raw["freight_value"], "freight_value")
            if (
                (order_id,) not in orders.good
                or (product_id,) not in products.good
                or (seller_id,) not in sellers.good
            ):
                raise S.FieldError("BROKEN_FK", "order_id/product_id/seller_id")
            items.good[key] = (
                batch_id, order_id, line_no, product_id, seller_id, shipping_limit, price,
                freight, provenance,
            )
        except S.FieldError as exc:
            items.quarantine(line, exc.reason, raw, key)

    for table in (customers, sellers, products, orders, items):
        batch.rows[table.name] = list(table.good.values())
    return batch


def _order_sequence_reason(purchased, approved, carrier, delivered) -> str | None:
    if approved is not None and approved < purchased:
        return "APPROVED_BEFORE_PURCHASE"
    if carrier is not None and carrier < purchased:
        return "CARRIER_BEFORE_PURCHASE"
    if delivered is not None and delivered < purchased:
        return "DELIVERED_BEFORE_PURCHASE"
    if delivered is not None and carrier is not None and delivered < carrier:
        return "DELIVERED_BEFORE_CARRIER"
    return None


# ---- loading ------------------------------------------------------------------------


def quarantine_id(batch_id: str, q: QuarantineRow) -> uuid.UUID:
    return uuid.uuid5(_QUARANTINE_NS, f"{batch_id}|{q.source_file}|{q.source_row_number}|"
                                      f"{q.reason_code}")


def manifest_path_for(batch: ValidatedBatch) -> Path:
    if batch.provenance == "authored":
        return REPO_ROOT / "data" / "fixtures" / "manifest.json"
    return REPO_ROOT / "data" / "manifest.json"


def _comparable(manifest: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in manifest.items() if k != "demo_as_of"}


def run_import(
    directory: Path, batch_id: str | None = None, download_date: date | None = None
) -> ImportResult:
    from sqlalchemy import text

    from ops.db import engine

    directory = Path(directory)
    batch = validate_sources(directory, batch_id)
    if download_date is None:
        newest = max((directory / s["file"]).stat().st_mtime for s in batch.file_stats.values())
        download_date = datetime.fromtimestamp(newest, UTC).date()
    manifest = build_manifest(batch, IMPORTER_VERSION, download_date)

    eng = engine("import")
    with eng.begin() as conn:
        existing = conn.execute(
            text("SELECT manifest FROM source_batches WHERE batch_id = :b"), {"b": batch.batch_id}
        ).scalar_one_or_none()
        if existing is not None:
            if _comparable(existing) != _comparable(manifest):
                raise ImportError_(
                    f"batch {batch.batch_id} already exists with a different manifest"
                )
            return ImportResult(batch.batch_id, existing, already_present=True)

        conn.execute(
            text("INSERT INTO source_batches (batch_id, manifest) VALUES (:b, CAST(:m AS jsonb))"),
            {"b": batch.batch_id, "m": json.dumps(manifest)},
        )
        raw = conn.connection.driver_connection
        with raw.cursor() as cur:
            for table in S.LOAD_ORDER:
                cols = TABLE_COLUMNS[table]
                rows = batch.rows[table]
                for start in range(0, len(rows), COPY_BATCH_SIZE):
                    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as copy:
                        for row in rows[start : start + COPY_BATCH_SIZE]:
                            copy.write_row(row)
            qcols = ["quarantine_id", "batch_id", "source_file", "source_row_number",
                     "reason_code", "raw_row"]
            for start in range(0, len(batch.quarantine), COPY_BATCH_SIZE):
                with cur.copy(f"COPY quarantine ({', '.join(qcols)}) FROM STDIN") as copy:
                    for q in batch.quarantine[start : start + COPY_BATCH_SIZE]:
                        copy.write_row((
                            quarantine_id(batch.batch_id, q), batch.batch_id, q.source_file,
                            q.source_row_number, q.reason_code,
                            json.dumps(q.raw_row, sort_keys=True),
                        ))

    write_manifest(manifest_path_for(batch), manifest)
    return ImportResult(batch.batch_id, manifest, already_present=False)
