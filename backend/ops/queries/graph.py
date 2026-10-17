"""Bounded, authorized graph projection for Cytoscape (spec 8, display projection).

OrderLine collapses into an Order -> Seller edge carrying line_no, product, and
line price. Depth counts on this projection: Order -> Seller -> related Order is
depth 2. At most 50 nodes are shown; exact totals come from the tools'
aggregates, which never depend on the display limit. Every node comes from a
tool result, so authorization has already been applied.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection

from ops.ontology.registry import ONTOLOGY_VERSION, registry
from ops.queries.scope import Principal
from ops.queries.tools import (
    DisruptionContextInput,
    NotVisible,
    OrderSnapshotInput,
    SellerScopeInput,
    get_disruption_context,
    get_order_snapshot,
    get_seller_exception_scope,
)

MAX_NODES = 50


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    label: str
    depth: int
    is_synthetic: bool = False
    provenance: str
    data: dict


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source: str
    target: str
    relationship: str
    meaning: str
    is_synthetic: bool = False
    data: dict


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ontology_version: str = ONTOLOGY_VERSION
    batch_id: str
    as_of: datetime
    scenario_id: str | None
    root: str
    nodes: list[Node]
    edges: list[Edge]
    max_nodes: int = MAX_NODES
    truncated: bool
    totals: dict[str, int]
    limit_note: str = ("The graph shows at most 50 nodes. Totals are exact and computed "
                       "separately from the display limit.")


class _Builder:
    def __init__(self, as_of: datetime):
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        self.truncated = False
        self.rels = registry().relationships

    def node(self, node: Node) -> bool:
        if node.id in self.nodes:
            return True
        if len(self.nodes) >= MAX_NODES:
            self.truncated = True
            return False
        self.nodes[node.id] = node
        return True

    def edge(self, source: str, target: str, rel: str, data: dict, key: str = "") -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        meaning = (self.rels["contains"].meaning + " " + self.rels["fulfilled_by"].meaning
                   if rel == "order_line" else self.rels[rel].meaning)
        edge_id = f"{rel}:{source}->{target}{key}"
        synthetic = rel in ("shipped_by", "overlaps")
        self.edges[edge_id] = Edge(id=edge_id, source=source, target=target, relationship=rel,
                                   meaning=meaning, is_synthetic=synthetic, data=data)


def _order_node(order_id: str, depth: int, provenance: str, data: dict) -> Node:
    return Node(id=f"Order:{order_id}", type="Order", label=order_id[:8], depth=depth,
                provenance=provenance, data=data)


def _seller_node(seller_id: str, depth: int, provenance: str, data: dict) -> Node:
    return Node(id=f"Seller:{seller_id}", type="Seller", label=seller_id[:8], depth=depth,
                provenance=provenance, data=data)


def _line_edge(b: _Builder, order_id: str, seller_id: str, line) -> None:
    b.edge(f"Order:{order_id}", f"Seller:{seller_id}", "order_line",
           {"line_no": line.line_no, "product_id": line.product_id,
            "price_centavos": line.price_centavos}, key=f"#{line.line_no}")


def _add_context(b: _Builder, conn, principal, target_type, target_id, as_of, scenario_id,
                 totals) -> None:
    if scenario_id is None:
        return
    ctx = get_disruption_context(conn, principal, DisruptionContextInput(
        target_type=target_type, target_id=target_id, as_of=as_of, scenario_id=scenario_id))
    for order_id, carrier in sorted(ctx.carriers.items()):
        cid = f"Carrier:{scenario_id}/{carrier['carrier_code']}"
        if f"Order:{order_id}" in b.nodes and b.node(Node(
                id=cid, type="Carrier", label=carrier["display_name"], depth=1,
                is_synthetic=True, provenance="synthetic", data=carrier)):
            b.edge(f"Order:{order_id}", cid, "shipped_by", {"carrier_code": carrier["carrier_code"]})
    for e in ctx.events:
        eid = f"DisruptionEvent:{scenario_id}/{e.event_id}"
        if b.node(Node(id=eid, type="DisruptionEvent", label=e.kind, depth=1,
                       is_synthetic=True, provenance="synthetic",
                       data=e.model_dump(mode="json", exclude={"overlaps"}))):
            for o in e.overlaps:
                b.edge(eid, f"Order:{o.order_id}", "overlaps", o.model_dump(mode="json"))
    totals["overlapping_events"] = len(ctx.events)


def build_graph(conn: Connection, principal: Principal, root_type: Literal["Order", "Seller"],
                root_id: str, as_of: datetime, scenario_id: str | None = None) -> Graph:
    b = _Builder(as_of)
    totals: dict[str, int] = {}
    if root_type == "Order":
        snap = get_order_snapshot(conn, principal, OrderSnapshotInput(order_id=root_id,
                                                                      as_of=as_of))
        prov = snap.order.provenance
        b.node(_order_node(root_id, 0, prov, snap.order.model_dump(mode="json")))
        cust = snap.customer["customer_id"]
        b.node(Node(id=f"Customer:{cust}", type="Customer", label=cust[:8], depth=1,
                    provenance=prov, data=snap.customer))
        b.edge(f"Customer:{cust}", f"Order:{root_id}", "places", {})
        sellers = sorted({line.seller_id for line in snap.lines})
        states = {line.seller_id: line.seller_state for line in snap.lines}
        for s in sellers:
            b.node(_seller_node(s, 1, prov, {"seller_id": s, "state": states[s]}))
        for line in snap.lines:
            _line_edge(b, root_id, line.seller_id, line)
        totals["root_lines"] = len(snap.lines)
        totals["related_late_open_orders"] = 0
        related: set[str] = set()
        for s in sellers:
            scope = get_seller_exception_scope(conn, principal,
                                               SellerScopeInput(seller_id=s, as_of=as_of))
            totals[f"seller_late_open_orders:{s}"] = scope.aggregates.late_open_orders
            for o in scope.orders:
                if o.order_id == root_id:
                    continue
                related.add(o.order_id)
                if b.node(_order_node(o.order_id, 2, prov, {"days_overdue": o.days_overdue})):
                    for line in o.seller_lines:
                        _line_edge(b, o.order_id, s, line)
            if scope.truncated:
                b.truncated = True
        totals["related_late_open_orders"] = len(related)
        _add_context(b, conn, principal, "Order", root_id, as_of, scenario_id, totals)
    else:
        scope = get_seller_exception_scope(conn, principal,
                                           SellerScopeInput(seller_id=root_id, as_of=as_of))
        prov = scope.seller["provenance"]
        b.node(_seller_node(root_id, 0, prov, scope.seller))
        totals.update(scope.aggregates.model_dump())
        for o in scope.orders:
            if not b.node(_order_node(o.order_id, 1, prov, {"days_overdue": o.days_overdue})):
                continue
            for line in o.seller_lines:
                _line_edge(b, o.order_id, root_id, line)
        for o in scope.orders:
            if f"Order:{o.order_id}" not in b.nodes or not o.multi_seller:
                continue
            snap = get_order_snapshot(conn, principal, OrderSnapshotInput(order_id=o.order_id,
                                                                          as_of=as_of))
            for line in snap.lines:
                if line.seller_id == root_id:
                    continue
                if b.node(_seller_node(line.seller_id, 2, prov,
                                       {"seller_id": line.seller_id,
                                        "state": line.seller_state})):
                    _line_edge(b, o.order_id, line.seller_id, line)
        if scope.truncated:
            b.truncated = True
        _add_context(b, conn, principal, "Seller", root_id, as_of, scenario_id, totals)
    return Graph(batch_id=principal.batch_id, as_of=as_of, scenario_id=scenario_id,
                 root=f"{root_type}:{root_id}", nodes=list(b.nodes.values()),
                 edges=list(b.edges.values()), truncated=b.truncated, totals=totals)


__all__ = ["Graph", "NotVisible", "build_graph"]
