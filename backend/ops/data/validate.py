"""ops data validate: recheck an imported batch against its manifest and integrity rules.

This module may read order_status: it reports data quality only.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from ops.data.as_of import AsOfError, output_paths, resolve_batch
from ops.data.manifest import manifest_hash
from ops.db import engine


class ValidationFailed(Exception):
    pass


ORPHAN_CHECKS = {
    "orders without customer": """
        SELECT count(*) FROM orders o LEFT JOIN customers c
          ON c.batch_id = o.batch_id AND c.customer_id = o.customer_id
        WHERE o.batch_id = :b AND c.customer_id IS NULL""",
    "lines without order/product/seller": """
        SELECT count(*) FROM order_items i
        LEFT JOIN orders o ON o.batch_id = i.batch_id AND o.order_id = i.order_id
        LEFT JOIN products p ON p.batch_id = i.batch_id AND p.product_id = i.product_id
        LEFT JOIN sellers s ON s.batch_id = i.batch_id AND s.seller_id = i.seller_id
        WHERE i.batch_id = :b
          AND (o.order_id IS NULL OR p.product_id IS NULL OR s.seller_id IS NULL)""",
    "negative money": """
        SELECT count(*) FROM order_items
        WHERE batch_id = :b AND (price_centavos < 0 OR freight_centavos < 0)""",
    "orders missing estimate": """
        SELECT count(*) FROM orders WHERE batch_id = :b AND estimated_at IS NULL""",
    "rows with wrong provenance": """
        SELECT (SELECT count(*) FROM orders WHERE batch_id = :b AND provenance <> :p)
             + (SELECT count(*) FROM order_items WHERE batch_id = :b AND provenance <> :p)
             + (SELECT count(*) FROM customers WHERE batch_id = :b AND provenance <> :p)
             + (SELECT count(*) FROM sellers WHERE batch_id = :b AND provenance <> :p)
             + (SELECT count(*) FROM products WHERE batch_id = :b AND provenance <> :p)""",
}


def validate_batch(batch_id: str | None = None) -> str:
    failures: list[str] = []
    lines: list[str] = []
    try:
        with engine("import").connect() as conn:
            batch_id, manifest = resolve_batch(conn, batch_id)
            lines.append(f"batch {batch_id} ({manifest['provenance']})")
            for table, expected in manifest["loaded_rows"].items():
                actual = conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE batch_id = :b"), {"b": batch_id}
                ).scalar_one()
                ok = actual == expected
                lines.append(f"  {table}: {actual} rows (manifest {expected}) "
                             f"{'ok' if ok else 'MISMATCH'}")
                if not ok:
                    failures.append(f"{table} row count {actual} != manifest {expected}")

            quarantined = dict(conn.execute(text(
                "SELECT reason_code, count(*) FROM quarantine WHERE batch_id = :b "
                "GROUP BY reason_code"), {"b": batch_id}).all())
            if dict(sorted(quarantined.items())) != manifest["quarantine_counts"]:
                failures.append(
                    f"quarantine {quarantined} != manifest {manifest['quarantine_counts']}"
                )
            lines.append(f"  quarantine: {dict(sorted(quarantined.items()))}")

            for label, sql in ORPHAN_CHECKS.items():
                n = conn.execute(text(sql), {"b": batch_id, "p": manifest["provenance"]}
                                 ).scalar_one()
                lines.append(f"  {label}: {n}")
                if n:
                    failures.append(f"{label}: {n}")

            no_lines = conn.execute(text(
                "SELECT count(*) FROM orders o WHERE o.batch_id = :b AND NOT EXISTS "
                "(SELECT 1 FROM order_items i WHERE i.batch_id = o.batch_id "
                "AND i.order_id = o.order_id)"), {"b": batch_id}).scalar_one()
            lines.append(f"  orders with no lines (never visible): {no_lines}")

            statuses = conn.execute(text(
                "SELECT coalesce(order_status, '(null)'), count(*) FROM orders "
                "WHERE batch_id = :b GROUP BY 1 ORDER BY 2 DESC"), {"b": batch_id}).all()
            lines.append("  order_status (data quality report only): "
                         + ", ".join(f"{s}={n}" for s, n in statuses))
    except AsOfError as exc:
        raise ValidationFailed(str(exc)) from exc

    _, manifest_file = output_paths(manifest)
    if manifest_file.exists():
        on_disk = json.loads(manifest_file.read_text())
        same = manifest_hash(on_disk) == manifest_hash(manifest)
        lines.append(f"  {manifest_file.name} matches database: {same}")
        if not same:
            failures.append(f"{manifest_file} differs from the database manifest")
    else:
        failures.append(f"{manifest_file} missing")

    if failures:
        raise ValidationFailed("\n".join(lines + ["FAILED:"] + [f"  - {f}" for f in failures]))
    return "\n".join(lines + ["validation passed"])
