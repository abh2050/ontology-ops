"""Gold set loading, canonical queries, hashing, and the freeze gate (spec 14.3).

ops eval refuses to run on a gold set without reviewer metadata or with a changed
hash. The hash covers the gold items, rubric, canonical SQL, security and
reliability scenarios, and the meaningful-margin definition in configs/policy.yaml
(owner decision 2026-10-17).
"""

from __future__ import annotations

import hashlib
import json
import re

import yaml
from sqlalchemy import Connection, text

from ops.settings import REPO_ROOT, load_config

GOLD = REPO_ROOT / "data" / "gold"
HASHED_FILES = ["gold_set.yaml", "rubric.md", "canonical.sql", "security_scenarios.yaml",
                "reliability_scenarios.yaml"]
FREEZE = GOLD / "FREEZE.json"


class GoldNotFrozen(Exception):
    pass


def canonical_queries() -> dict[str, str]:
    raw = (GOLD / "canonical.sql").read_text()
    parts = re.split(r"^-- name: ([a-z_]+)\s*$", raw, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].strip().rstrip(";") for i in range(1, len(parts), 2)}


def run_canonical(conn: Connection, name: str, params: dict) -> list[dict]:
    sql = canonical_queries()[name]
    names = set(re.findall(r"(?<!:):([a-z_]+)", sql))
    bound = {k: v for k, v in params.items() if k in names}
    return [dict(r._mapping) for r in conn.execute(text(sql), bound)]


def load_gold() -> dict:
    return yaml.safe_load((GOLD / "gold_set.yaml").read_text())


def gold_hash() -> str:
    h = hashlib.sha256()
    for name in HASHED_FILES:
        h.update(name.encode() + b"\0" + (GOLD / name).read_bytes() + b"\0")
    margin = load_config("policy")["eval"]["meaningful_margin"]
    h.update(json.dumps(margin, sort_keys=True).encode())
    return h.hexdigest()


def verify_frozen() -> dict:
    if not FREEZE.exists():
        raise GoldNotFrozen("gold set is a draft: no data/gold/FREEZE.json. The owner reviews "
                            "every item, then runs scripts/freeze_gold.py --reviewer <name>")
    meta = json.loads(FREEZE.read_text())
    if not meta.get("reviewer") or not meta.get("review_date"):
        raise GoldNotFrozen("FREEZE.json lacks reviewer identity or review date")
    current = gold_hash()
    if meta.get("gold_hash") != current:
        raise GoldNotFrozen("gold set changed after the freeze (hash mismatch); re-review and "
                            "re-freeze before evaluating")
    if load_gold().get("status") != "frozen":
        raise GoldNotFrozen("gold_set.yaml status is not 'frozen'")
    return meta


def summary(gold: dict) -> dict:
    items = gold["items"]
    by_cat: dict[str, int] = {}
    for it in items:
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
    return {"items": len(items), "by_category": by_cat,
            "requires_scenario": sum(1 for it in items if it["requires_scenario"]),
            "real_only_answerable": sum(1 for it in items if not it["requires_scenario"]
                                        and it["category"] != "unanswerable")}
