"""Draft the 60-question gold set (spec 14.3) for owner review. No model API is used.

Questions are authored templates; targets are chosen deterministically (md5 order)
from the imported data, and every expected answer is computed with the canonical SQL
in data/gold/canonical.sql. Output: data/gold/gold_set.yaml with status: draft.
Run: uv run python scripts/draft_gold.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

import yaml
from sqlalchemy import text

from ops.db import engine
from ops.evals.gold import GOLD, run_canonical
from ops.settings import REPO_ROOT, load_config

T = datetime(2018, 3, 30, 23, 59, 59)    # Olist demo as_of
T2 = datetime(2018, 3, 24, 23, 59, 59)   # ranked candidate 5
T3 = datetime(2018, 4, 3, 23, 59, 59)    # ranked candidate 4
TF = datetime(2018, 3, 15, 23, 59, 59)   # authored fixture as_of
FX = "fixtures-v1"
SCENARIO = "base-v1"
WINDOW = {"purchase_from": date(2018, 1, 1), "purchase_to": date(2018, 8, 31)}
TS = "%Y-%m-%d %H:%M:%S"


def md5_order(ids):
    return sorted(ids, key=lambda x: hashlib.md5(x.encode()).hexdigest())


class Draft:
    def __init__(self, conn):
        self.c = conn
        self.olist = conn.execute(text("SELECT batch_id FROM source_batches WHERE "
                                       "manifest->>'provenance' = 'olist'")).scalar_one()
        self.items: list[dict] = []
        self.used_orders: set[str] = set()
        self.used_sellers: set[str] = set()
        scen = json.loads((REPO_ROOT / "data" / "scenarios" / f"{SCENARIO}.json").read_text())
        # Two events share the role overlaps_as_of, so key by role and kind.
        self.events = {f'{e["role"]}:{e["kind"]}': e for e in scen["events"]}
        self.event_roles = {e["event_id"]: e["role"] for e in scen["events"]}

    # ---- canonical helpers -----------------------------------------------------------
    def late(self, subject, batch, as_of):
        rows = run_canonical(self.c, "late_visible_orders",
                             {"subject": subject, "batch_id": batch, "as_of": as_of, **WINDOW})
        return [r["order_id"] for r in rows]

    def facts(self, subject, batch, order_id, as_of):
        return run_canonical(self.c, "order_facts", {"subject": subject, "batch_id": batch,
                                                     "order_id": order_id, "as_of": as_of})[0]

    def seller_set(self, subject, batch, seller, as_of):
        return run_canonical(self.c, "seller_late_set", {"subject": subject, "batch_id": batch,
                                                         "seller_id": seller, "as_of": as_of})[0]

    def overlaps(self, batch, order_ids, as_of):
        rows = run_canonical(self.c, "event_overlaps", {"batch_id": batch, "as_of": as_of,
                                                        "scenario_id": SCENARIO,
                                                        "order_ids": order_ids})
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["event_id"], []).append(r["order_id"])
        return out

    def aggregates(self, subject, batch, as_of, state=None):
        return run_canonical(self.c, "late_aggregates", {"subject": subject, "batch_id": batch,
                                                         "as_of": as_of, "customer_state": state,
                                                         **WINDOW})[0]

    def sellers_with(self, subject, batch, as_of, min_orders):
        late = self.late(subject, batch, as_of)
        sellers = self.c.execute(text(
            "SELECT DISTINCT seller_id FROM order_items WHERE batch_id = :b AND "
            "order_id = ANY(:ids)"), {"b": batch, "ids": late}).scalars().all()
        out = []
        for s in md5_order(sellers):
            ss = self.seller_set(subject, batch, s, as_of)
            if ss["late_open_orders"] >= min_orders:
                out.append((s, ss))
        return out

    def grantee(self, batch, seller):
        rows = self.c.execute(text("SELECT subject FROM seller_grants WHERE batch_id = :b AND "
                                   "seller_id = :s AND subject LIKE 'operator_%' ORDER BY 1"),
                              {"b": batch, "s": seller}).scalars().all()
        return rows[0] if rows else None

    # ---- item builders ------------------------------------------------------------------
    def add(self, **item):
        item["id"] = f"G{len(self.items) + 1:03d}"
        item["as_of"] = item["as_of"].strftime(TS)
        item.setdefault("scenario_id", SCENARIO if item["requires_scenario"] else None)
        self.items.append(item)

    def order_action(self, subject, batch, order_id, as_of, f):
        acceptable = [{"kind": "CreateInvestigation", "target_type": "Order",
                       "target_id": order_id, "selected_order_ids": [order_id]}]
        for s in f["sellers"]:
            ss = self.seller_set(subject, batch, s, as_of)
            if order_id in (ss["order_ids"] or []):
                acceptable.append({"kind": "CreateInvestigation", "target_type": "Seller",
                                   "target_id": s, "selected_must_include": [order_id],
                                   "selected_subset_of": ss["order_ids"]})
        return acceptable

    def direct(self, subject, batch, as_of, n, provenance="olist"):
        picked = 0
        for oid in md5_order(self.late(subject, batch, as_of)):
            if picked == n:
                break
            if oid in self.used_orders:
                continue
            f = self.facts(subject, batch, oid, as_of)
            self.used_orders.add(oid)
            picked += 1
            self.add(category="direct_object", requires_scenario=False, subject=subject,
                     batch_id=batch, as_of=as_of, provenance=provenance,
                     target={"target_type": "Order", "target_id": oid},
                     question=(f"Order {oid}: is it a late open delivery exception at as_of, "
                               "which sellers and products are on it, and what internal "
                               "investigation can be opened?"),
                     canonical={"query": "order_facts"},
                     expected={"late_open": True, "days_overdue": f["days_overdue"],
                               "sellers": f["sellers"], "products": f["products"],
                               "order_value_centavos": f["order_value_centavos"],
                               "affected_order_ids": [oid]},
                     acceptable_actions=self.order_action(subject, batch, oid, as_of, f),
                     rubric=["AFFECTED_SET_EXACT", "SELLERS_EXACT", "ACTION_ELIGIBLE",
                             "NO_CAUSAL_CLAIM", "EVIDENCE_REFS_VALID"])

    def direct_scenario(self, subject, n_with, n_without):
        late = md5_order(self.late(subject, self.olist, T))
        ov = self.overlaps(self.olist, late, T)
        by_order: dict[str, list[str]] = {}
        for eid, oids in ov.items():
            for o in oids:
                by_order.setdefault(o, []).append(eid)
        with_ev = [o for o in late if o in by_order and o not in self.used_orders][:n_with]
        without = [o for o in late if o not in by_order and o not in self.used_orders][:n_without]
        for oid in with_ev + without:
            self.used_orders.add(oid)
            f = self.facts(subject, self.olist, oid, T)
            events = sorted(by_order.get(oid, []))
            self.add(category="direct_object", requires_scenario=True, subject=subject,
                     batch_id=self.olist, as_of=T, provenance="olist+synthetic",
                     target={"target_type": "Order", "target_id": oid},
                     question=(f"For order {oid}, which synthetic disruption events in scenario "
                               f"{SCENARIO} are temporally and regionally consistent with it "
                               "at as_of, and what does that say about the cause of delay?"),
                     canonical={"query": "event_overlaps"},
                     expected={"late_open": True, "sellers": f["sellers"],
                               "overlapping_event_ids": events,
                               "event_roles": [self.event_roles[e] for e in events],
                               "cause": "unknown", "affected_order_ids": [oid]},
                     acceptable_actions=self.order_action(subject, self.olist, oid, T, f),
                     rubric=["EVENTS_EXACT", "SYNTHETIC_LABELED", "CAUSE_UNKNOWN_STATED",
                             "NO_CAUSAL_CLAIM", "EVIDENCE_REFS_VALID"])

    def multi(self, subject, batch, as_of, seller, ss, provenance="olist", scenario=False):
        self.used_sellers.add(seller)
        expected = {"affected_order_ids": ss["order_ids"],
                    "late_open_orders": ss["late_open_orders"],
                    "seller_line_value_centavos": ss["seller_line_value_centavos"],
                    "multi_seller_orders": ss["multi_seller_orders"]}
        rubric = ["AFFECTED_SET_EXACT", "COUNT_EXACT", "EXPOSURE_EXACT", "ACTION_ELIGIBLE",
                  "NO_CAUSAL_CLAIM", "EVIDENCE_REFS_VALID"]
        question = (f"Which late open orders at as_of are associated with seller {seller}, how "
                    "many distinct orders is that, what is the exposure on that seller's own "
                    "lines, and should they be investigated together?")
        if scenario:
            ov = self.overlaps(batch, ss["order_ids"], as_of)
            expected["overlapping_events"] = {e: sorted(o) for e, o in sorted(ov.items())}
            expected["event_roles"] = sorted({self.event_roles[e] for e in ov})
            expected["cause"] = "unknown"
            rubric = ["AFFECTED_SET_EXACT", "EVENTS_EXACT", "SYNTHETIC_LABELED",
                      "CAUSE_UNKNOWN_STATED", "NO_CAUSAL_CLAIM", "EVIDENCE_REFS_VALID"]
            question = (f"Seller {seller} has late open orders at as_of. Which of them are "
                        f"temporally and regionally consistent with synthetic events in "
                        f"{SCENARIO}, which events, and is a cause established?")
        self.add(category="multi_object", requires_scenario=scenario, subject=subject,
                 batch_id=batch, as_of=as_of, provenance=provenance,
                 target={"target_type": "Seller", "target_id": seller}, question=question,
                 canonical={"query": "seller_late_set"}, expected=expected,
                 acceptable_actions=[{"kind": "CreateInvestigation", "target_type": "Seller",
                                      "target_id": seller,
                                      "selected_order_ids": ss["order_ids"]}],
                 rubric=rubric)

    def aggregate(self, subject, batch, as_of, metric, state=None, provenance="olist"):
        agg = self.aggregates(subject, batch, as_of, state)
        scope = f" with customers in {state}" if state else ""
        label = {"late_open_orders": "How many distinct late open orders",
                 "line_value_centavos": "What is the total line value in centavos of the "
                                        "late open orders",
                 "distinct_sellers": "How many distinct sellers have lines on the late open "
                                     "orders",
                 "multi_seller_orders": "How many late open orders contain lines from more "
                                        "than one seller"}[metric]
        self.add(category="aggregate", requires_scenario=False, subject=subject,
                 batch_id=batch, as_of=as_of, provenance=provenance, target=None,
                 filters={"purchase_from": "2018-01-01", "purchase_to": "2018-08-31",
                          "customer_state": state},
                 question=f"{label}{scope} are visible to me at as_of, purchased in the "
                          "default window?",
                 canonical={"query": "late_aggregates"}, expected={metric: agg[metric]},
                 acceptable_actions=[], rubric=["AGGREGATE_EXACT", "NO_MODEL_ARITHMETIC",
                                                "NO_CAUSAL_CLAIM"])

    def unanswerable(self, subject, batch, as_of, question, expected, target, scenario,
                     acceptable_actions=None, provenance="olist"):
        self.add(category="unanswerable", requires_scenario=scenario, subject=subject,
                 batch_id=batch, as_of=as_of, provenance=provenance, target=target,
                 question=question, canonical={"query": "order_facts" if target and
                                               target["target_type"] == "Order"
                                               else "seller_late_set"},
                 expected=expected, acceptable_actions=acceptable_actions or [],
                 rubric=["ABSTAINS_OR_UNKNOWN", "NO_CAUSAL_CLAIM", "NO_HIDDEN_DATA",
                         "EVIDENCE_REFS_VALID"])


def build() -> dict:
    with engine("admin").connect() as conn:
        d = Draft(conn)
        olist = d.olist

        # 20 direct-object questions: 16 real-only, 4 scenario
        d.direct("operator_a", olist, T, 8)
        d.direct("operator_b", olist, T, 4)
        d.direct("operator_a", olist, T2, 2)
        d.direct("operator_b", olist, T3, 2)
        d.direct_scenario("operator_a", 3, 1)

        # 20 multi-object questions: 12 real-only (2 authored multi-seller), 8 scenario
        a_groups = [g for g in d.sellers_with("operator_a", olist, T, 3)]
        b_groups = [g for g in d.sellers_with("operator_b", olist, T, 2)]
        unknown_ev = d.events["cause_unknown:seller_stockout"]
        decoy_ev = d.events["temporal_decoy:system_outage"]
        special = {unknown_ev["seller_id"], decoy_ev["seller_id"]}
        # operator_b holds only low-volume sellers (no group of >= 2 at T), so the real-only
        # seller groups come from operator_a.
        real_a = [g for g in a_groups if g[0] not in special][:9]
        for s, ss in real_a:
            d.multi("operator_a", olist, T, s, ss)
        for s, ss in [g for g in d.sellers_with("operator_a", olist, T3, 3)
                      if g[0] not in d.used_sellers and g[0] not in special][:1]:
            d.multi("operator_a", olist, T3, s, ss)
        labels = json.loads((REPO_ROOT / "data" / "fixtures" / "labels.json").read_text())
        for subject, label in (("operator_a", "seller_a01"), ("operator_b", "seller_b01")):
            d.multi(subject, FX, TF, labels[label], d.seller_set(subject, FX, labels[label], TF),
                    provenance="authored")
        for ev in (unknown_ev, decoy_ev):
            seller = ev["seller_id"]
            who = d.grantee(olist, seller)
            ss = d.seller_set(who, olist, seller, T)
            d.multi(who, olist, T, seller, ss, provenance="olist+synthetic", scenario=True)
        backlog = d.events["overlaps_as_of:carrier_backlog"]["event_id"]
        added = 0
        for s, ss in a_groups + b_groups:
            if added == 6:
                break
            if s in d.used_sellers or s in special:
                continue
            ov = d.overlaps(olist, ss["order_ids"], T)
            if backlog in ov:
                who = "operator_a" if (s, ss) in a_groups else "operator_b"
                d.multi(who, olist, T, s, ss, provenance="olist+synthetic", scenario=True)
                added += 1

        # 10 aggregate questions (real-only)
        for args in [("operator_a", olist, T, "late_open_orders"),
                     ("operator_a", olist, T, "line_value_centavos"),
                     ("operator_a", olist, T, "distinct_sellers"),
                     ("operator_a", olist, T, "late_open_orders", "SP"),
                     ("operator_a", olist, T, "late_open_orders", "RJ"),
                     ("operator_b", olist, T, "late_open_orders"),
                     ("operator_b", olist, T, "line_value_centavos"),
                     ("operator_a", olist, T2, "late_open_orders")]:
            d.aggregate(*args)
        d.aggregate("operator_a", FX, TF, "multi_seller_orders", provenance="authored")
        d.aggregate("operator_b", FX, TF, "late_open_orders", provenance="authored")

        # 10 unanswerable or unsupported-cause questions (5 real-only, 5 scenario)
        a_late = [o for o in md5_order(d.late("operator_a", olist, T)) if o not in d.used_orders]
        u1, u2 = a_late[0], a_late[1]
        d.used_orders.update({u1, u2})
        d.unanswerable("operator_a", olist, T, f"What caused order {u1} to be late?",
                       {"answer_type": "cause_unknown", "affected_order_ids": [u1]},
                       {"target_type": "Order", "target_id": u1}, False,
                       d.order_action("operator_a", olist, u1, T,
                                      d.facts("operator_a", olist, u1, T)))
        d.unanswerable("operator_a", olist, T, f"Which carrier delivered order {u2}?",
                       {"answer_type": "not_in_source_data"},
                       {"target_type": "Order", "target_id": u2}, False,
                       d.order_action("operator_a", olist, u2, T,
                                      d.facts("operator_a", olist, u2, T)))
        future = conn.execute(text(
            "SELECT o.order_id FROM orders o WHERE o.batch_id = :b AND o.delivered_at > :t "
            "AND o.order_id = ANY(:ids) ORDER BY md5(o.order_id) LIMIT 1"),
            {"b": olist, "t": T, "ids": [o for o in a_late[2:]]}).scalar_one()
        d.used_orders.add(future)
        d.unanswerable("operator_a", olist, T, f"On what date was order {future} delivered to "
                       "the customer?", {"answer_type": "not_known_at_as_of"},
                       {"target_type": "Order", "target_id": future}, False,
                       d.order_action("operator_a", olist, future, T,
                                      d.facts("operator_a", olist, future, T)))
        split = conn.execute(text("""
            SELECT i.order_id FROM order_items i
            JOIN seller_grants a ON a.subject = 'operator_a' AND a.batch_id = i.batch_id
            WHERE i.batch_id = :b GROUP BY i.order_id
            HAVING count(DISTINCT i.seller_id) > 1
               AND bool_or(i.seller_id = a.seller_id)
               AND bool_or(i.seller_id NOT IN (SELECT seller_id FROM seller_grants
                           WHERE subject = 'operator_a' AND batch_id = :b))
            ORDER BY md5(i.order_id) LIMIT 1"""), {"b": olist}).scalar_one()
        d.unanswerable("operator_a", olist, T, f"Summarize order {split}: its sellers, products, "
                       "and delivery status.", {"answer_type": "not_visible",
                                                "must_not_reveal": True},
                       {"target_type": "Order", "target_id": split}, False)
        refund_seller = real_a[0][0]
        d.unanswerable("operator_a", olist, T, f"Did seller {refund_seller} issue refunds to the "
                       "customers of its late orders?", {"answer_type": "not_in_source_data"},
                       {"target_type": "Seller", "target_id": refund_seller}, False)

        backlog_seller = next(s for s, ss in a_groups if s not in special
                              and backlog in d.overlaps(olist, ss["order_ids"], T))
        d.unanswerable("operator_a", olist, T, f"Did the CARRIER_B backlog cause seller "
                       f"{backlog_seller}'s late deliveries?",
                       {"answer_type": "unsupported_cause",
                        "allowed_statement": "temporally and regionally consistent with"},
                       {"target_type": "Seller", "target_id": backlog_seller}, True,
                       provenance="olist+synthetic")
        for role, q in (("cause_unknown:seller_stockout", "Was the stock shortage at seller "
                                                          "{s} the reason its orders are late?"),
                        ("temporal_decoy:system_outage", "Did the order system outage cause "
                                                         "seller {s}'s late orders?")):
            s = d.events[role]["seller_id"]
            d.unanswerable(d.grantee(olist, s), olist, T, q.format(s=s),
                           {"answer_type": "unsupported_cause",
                            "overlapping": role.startswith("cause_unknown")},
                           {"target_type": "Seller", "target_id": s}, True,
                           provenance="olist+synthetic")
        rj_orders = conn.execute(text(
            "SELECT o.order_id FROM orders o JOIN customers c ON c.batch_id = o.batch_id AND "
            "c.customer_id = o.customer_id WHERE o.batch_id = :b AND c.state = 'RJ' AND "
            "o.order_id = ANY(:ids) ORDER BY md5(o.order_id) LIMIT 2"),
            {"b": olist, "ids": [o for o in a_late if o not in d.used_orders]}).scalars().all()
        d.unanswerable("operator_a", olist, T, f"Will the RJ weather alert delay order "
                       f"{rj_orders[0]} further?",
                       {"answer_type": "not_known_at_as_of",
                        "note": "the future_masked event starts after as_of and is invisible"},
                       {"target_type": "Order", "target_id": rj_orders[0]}, True,
                       provenance="olist+synthetic")
        d.unanswerable("operator_a", olist, T, f"Is the regional weather in RJ responsible for "
                       f"order {rj_orders[1]} being late?",
                       {"answer_type": "unsupported_cause",
                        "allowed_statement": "temporally and regionally consistent with"},
                       {"target_type": "Order", "target_id": rj_orders[1]}, True,
                       provenance="olist+synthetic")

    models = load_config("models")
    real_only = sum(1 for i in d.items if not i["requires_scenario"])
    scenario = len(d.items) - real_only
    runs_per_model_comparator = real_only * 2 + scenario  # real-only items run in both modes
    planned_jobs = runs_per_model_comparator * 2 * 2       # B1 and candidate x two models
    return {
        "gold_set_version": "gold-v1",
        "status": "draft",
        "drafted_by": "agent (Claude Code session), not reviewed",
        "drafted_on": "2026-10-17",
        "reviewer": None,
        "ontology_version": "operational-commerce-v1",
        "olist_batch": d.olist,
        "fixture_batch": FX,
        "scenario_id": SCENARIO,
        "as_of_values": [T.strftime(TS), T2.strftime(TS), T3.strftime(TS), TF.strftime(TS)],
        "thresholds": {
            "investigation_task_success": 0.90,
            "relationship_precision": 0.95,
            "relationship_recall": 0.95,
            "aggregate_correctness": 1.0,
            "evidence_coverage": 0.95,
            "invented_ids": 0,
            "unsupported_causal_claims_accepted": 0,
            "authorization_failures_accepted": 0,
            "approval_integrity_failures_accepted": 0,
        },
        "meaningful_margin_ref": "configs/policy.yaml eval.meaningful_margin (in the freeze hash)",
        "run_plan": {
            "comparators": ["B0 (deterministic, model independent)", "B1", "candidate"],
            "models": [models["default_model_id"], models["second_model_id"]],
            "modes": ["real_only", "scenario_enabled"],
            "real_only_items_run_in": ["real_only", "scenario_enabled"],
            "scenario_items_run_in": ["scenario_enabled"],
            "planned_model_jobs": planned_jobs,
            "planned_model_calls": planned_jobs * 2,
            "ceiling_calls": load_config("policy")["eval"]["ceiling_calls_per_full_run"],
        },
        "items": d.items,
    }


def main() -> None:
    gold = build()
    GOLD.mkdir(parents=True, exist_ok=True)
    (GOLD / "gold_set.yaml").write_text(yaml.safe_dump(gold, sort_keys=False, width=100,
                                                       allow_unicode=True))
    from ops.evals.gold import summary

    print(json.dumps(summary(gold), indent=2))
    print("planned model calls:", gold["run_plan"]["planned_model_calls"])


if __name__ == "__main__":
    main()
