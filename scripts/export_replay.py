"""Export only authored, authorization-scoped evidence for the static UI; no model calls."""

import json
from datetime import datetime

from sqlalchemy import text

from ops.db import engine
from ops.queries import tools as T
from ops.queries.graph import build_graph
from ops.queries.scope import load_principal
from ops.settings import REPO_ROOT


def main():
    batch = "fixtures-v1"
    as_of = datetime(2018, 3, 15, 23, 59, 59)
    with engine("api").connect() as conn:
        principal = load_principal(conn, "operator_a", batch)
        if not principal.provisioned:
            raise RuntimeError("seed the local users before exporting replay")
        queue = T.find_late_orders(conn, principal, T.FindLateOrdersInput(
            as_of=as_of, limit=100)).model_dump(mode="json")
        graphs, snapshots, sellers = {}, {}, {}
        for item in queue["items"]:
            if item["provenance"] != "authored":
                raise RuntimeError("static replay may contain authored rows only")
            oid = item["order_id"]
            snapshots[oid] = T.get_order_snapshot(conn, principal, T.OrderSnapshotInput(
                as_of=as_of, order_id=oid)).model_dump(mode="json")
            for scenario in (None, "base-v1"):
                graphs[f"{oid}|{scenario or ''}"] = build_graph(
                    conn, principal, "Order", oid, as_of, scenario).model_dump(mode="json")
            for sid in item["seller_ids"]:
                sellers[sid] = T.get_seller_exception_scope(conn, principal, T.SellerScopeInput(
                    as_of=as_of, seller_id=sid)).model_dump(mode="json")
        grants = conn.execute(text("SELECT count(*) FROM seller_grants "
                                   "WHERE subject = :s AND batch_id = :b"),
                              {"s": principal.subject, "b": batch}).scalar_one()
    payload = {"source": "Authorized deterministic query export; no model output",
               "license": "authored for this project", "queue": queue,
               "me": {"subject": principal.subject, "role": principal.role,
                      "provisioned": True, "granted_sellers": grants,
                      "batch_id": batch, "as_of": as_of.isoformat()},
               "graphs": graphs, "snapshots": snapshots, "sellers": sellers}
    target = REPO_ROOT / "frontend" / "src" / "replay.json"
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    print(f"Exported {len(queue['items'])} authorized authored orders, {len(graphs)} graphs")


if __name__ == "__main__":
    main()
