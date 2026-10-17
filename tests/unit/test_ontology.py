import copy

import pytest
import yaml

from ops.ontology.models import Definitions
from ops.ontology.registry import DEFINITIONS_PATH, OntologyError, registry, validate

EXPECTED_TYPES = {
    "Customer": ["customer_id"],
    "Order": ["order_id"],
    "OrderLine": ["order_id", "line_no"],
    "Seller": ["seller_id"],
    "Product": ["product_id"],
    "Carrier": ["scenario_id", "carrier_code"],
    "DisruptionEvent": ["scenario_id", "event_id"],
    "InvestigationCase": ["case_id"],
    "ActionProposal": ["proposal_id"],
}

EXPECTED_RELATIONSHIPS = {
    "places": ("Customer", "Order", "one_to_many", False),
    "contains": ("Order", "OrderLine", "one_to_many", False),
    "references": ("OrderLine", "Product", "many_to_one", False),
    "fulfilled_by": ("OrderLine", "Seller", "many_to_one", False),
    "shipped_by": ("Order", "Carrier", "many_to_one", True),
    "overlaps": ("DisruptionEvent", "Order", "many_to_many", True),
}


def raw():
    with open(DEFINITIONS_PATH) as fh:
        return yaml.safe_load(fh)


def test_version_and_all_types_load():
    defs = registry()
    assert defs.version == "operational-commerce-v1"
    assert {k: v.identity for k, v in defs.object_types.items()} == EXPECTED_TYPES


@pytest.mark.parametrize("name", EXPECTED_RELATIONSHIPS)
def test_direction_and_cardinality(name):
    rel = registry().relationships[name]
    source, target, cardinality, synthetic = EXPECTED_RELATIONSHIPS[name]
    assert (rel.source, rel.target, rel.cardinality) == (source, target, cardinality)
    assert bool(rel.synthetic) is synthetic


def test_only_expected_relationships():
    assert set(registry().relationships) == set(EXPECTED_RELATIONSHIPS)


def test_synthetic_types_declared():
    types = registry().object_types
    assert types["Carrier"].synthetic is True
    assert types["DisruptionEvent"].synthetic is True


@pytest.mark.parametrize("type_name", ["Carrier", "DisruptionEvent"])
def test_refuses_synthetic_type_without_declaration(type_name):
    data = copy.deepcopy(raw())
    del data["object_types"][type_name]["synthetic"]
    with pytest.raises(OntologyError, match="synthetic type"):
        validate(Definitions.model_validate(data))


def test_refuses_synthetic_relationship_without_declaration():
    data = copy.deepcopy(raw())
    data["relationships"]["shipped_by"]["synthetic"] = False
    with pytest.raises(OntologyError, match="synthetic relationship"):
        validate(Definitions.model_validate(data))


def test_refuses_unknown_endpoint():
    data = copy.deepcopy(raw())
    data["relationships"]["places"]["target"] = "Shipment"
    with pytest.raises(OntologyError, match="unknown type"):
        validate(Definitions.model_validate(data))


def test_extra_fields_rejected():
    data = copy.deepcopy(raw())
    data["object_types"]["Order"]["colour"] = "red"
    with pytest.raises(ValueError):
        Definitions.model_validate(data)


def test_order_model_has_no_status_field():
    from ops.ontology.models import Order

    assert "order_status" not in Order.model_fields


def test_actions_and_projection():
    defs = registry()
    assert defs.actions["DraftCustomerUpdate"].target_types == ["Order"]
    assert set(defs.actions["CreateInvestigation"].target_types) == {"Order", "Seller"}
    assert defs.display_projection.max_nodes == 50
    assert defs.display_projection.collapse.into_edge == ("Order", "Seller")
    assert set(defs.derived_functions) == {
        "late_open_order",
        "known_delivery_state",
        "seller_associated_late_orders",
        "eligible_investigation",
        "event_overlap",
    }
