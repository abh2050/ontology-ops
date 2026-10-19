"""Read-only grouping potential from authorized default queues; no human savings claim."""

import json
from collections import Counter
from datetime import datetime

from sqlalchemy import text

from ops.db import engine
from ops.queries import tools as T
from ops.queries.scope import load_principal
from ops.settings import REPO_ROOT


def main():
    result = {"method": "Disjoint single-seller groups of at least two late open orders; "
              "multi-seller orders remain individual. Operators measured separately. "
              "Potential grouping only, not observed case reduction.", "cohorts": []}
    with engine("api").connect() as conn:
        batches = conn.execute(text("SELECT batch_id, manifest->'demo_as_of'->>'as_of' "
                                    "AS as_of FROM source_batches ORDER BY batch_id")).all()
        for batch in batches:
            if not batch.as_of:
                continue
            for actor in ("operator_a", "operator_b", "reviewer"):
                principal = load_principal(conn, actor, batch.batch_id)
                items, cursor = [], None
                while True:
                    page = T.find_late_orders(conn, principal, T.FindLateOrdersInput(
                        as_of=datetime.fromisoformat(batch.as_of), limit=100, cursor=cursor))
                    items.extend(page.items)
                    cursor = page.next_cursor
                    if not cursor:
                        break
                counts = Counter(i.seller_ids[0] for i in items if len(i.seller_ids) == 1)
                groups = [n for n in counts.values() if n >= 2]
                result["cohorts"].append({"batch_id": batch.batch_id, "actor": actor,
                    "as_of": batch.as_of, "late_open_orders": len(items),
                    "groupable_orders": sum(groups), "groups": len(groups),
                    "potential_cases": len(items) - sum(groups) + len(groups),
                    "multi_seller_orders": sum(i.multi_seller for i in items)})
    target = REPO_ROOT / "docs" / "evidence" / "business_case.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
