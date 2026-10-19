"""Public replay must remain authored and obey the pinned operator scope."""

import json
from pathlib import Path

from ops.queries.graph import Graph
from ops.queries.tools import LateOrdersPage, OrderSnapshot, SellerScope

ROOT = Path(__file__).resolve().parents[2]


def test_replay_schema_provenance_and_split_order_exclusion():
    raw = (ROOT / "frontend/src/replay.json").read_text()
    replay = json.loads(raw)
    page = LateOrdersPage.model_validate(replay["queue"])
    assert page.batch_id == "fixtures-v1" and len(page.items) == page.aggregates.late_open_orders
    assert replay["me"]["subject"] == "operator_a"
    for snapshot in replay["snapshots"].values():
        snapshot = OrderSnapshot.model_validate(snapshot)
        assert snapshot.order.provenance == "authored"
        assert all(ref.provenance in {"authored", "derived"} for ref in snapshot.evidence)
    for scope in replay["sellers"].values():
        assert SellerScope.model_validate(scope).seller["provenance"] == "authored"
    for graph in replay["graphs"].values():
        graph = Graph.model_validate(graph)
        assert len(graph.nodes) <= graph.max_nodes
        assert all(n.provenance in {"authored", "synthetic"} for n in graph.nodes)
        if graph.scenario_id is None:
            assert not any(n.is_synthetic for n in graph.nodes)
    labels = json.loads((ROOT / "data/fixtures/labels.json").read_text())
    for label, ident in labels.items():
        if label.startswith("split_ab_") or label == "shared_customer_split":
            assert ident not in raw, f"hidden order leaked into replay: {label}"
