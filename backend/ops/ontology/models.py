"""Pydantic models for the ontology definitions and for every domain object."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Strict = ConfigDict(extra="forbid", frozen=True)

Cardinality = Literal["one_to_many", "many_to_one", "one_to_one", "many_to_many"]
Provenance = Literal["source", "synthetic", "derived", "application"]


class ObjectType(BaseModel):
    model_config = Strict
    kind: Literal["domain", "application"]
    identity: list[str] = Field(min_length=1)
    table: str
    batch_scoped: bool
    provenance: Provenance
    synthetic: bool | None = None

    @property
    def looks_synthetic(self) -> bool:
        return self.provenance == "synthetic" or "scenario_id" in self.identity


class Relationship(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    source: str
    target: str
    cardinality: Cardinality
    provenance: Provenance
    synthetic: bool | None = None
    derived_by: str | None = None
    meaning: str
    join: str | None = None

    @model_validator(mode="after")
    def _derived_needs_function(self) -> Relationship:
        if (self.provenance == "derived") != (self.derived_by is not None):
            raise ValueError("derived relationships, and only those, declare derived_by")
        return self


class DerivedFunction(BaseModel):
    model_config = Strict
    inputs: list[str]
    semantics: str


class ActionDef(BaseModel):
    model_config = Strict
    target_types: list[Literal["Order", "Seller"]] = Field(min_length=1)
    side_effects: list[str]
    preconditions: list[str] = Field(min_length=1)


class Collapse(BaseModel):
    model_config = Strict
    object: str
    into_edge: tuple[str, str]
    edge_fields: list[str]


class DisplayProjection(BaseModel):
    model_config = Strict
    collapse: Collapse
    max_nodes: int = Field(gt=0, le=50)
    max_depth: int = Field(ge=2)


class Definitions(BaseModel):
    model_config = Strict
    version: str
    object_types: dict[str, ObjectType]
    relationships: dict[str, Relationship]
    derived_functions: dict[str, DerivedFunction]
    actions: dict[Literal["CreateInvestigation", "DraftCustomerUpdate"], ActionDef]
    display_projection: DisplayProjection


# ---- domain objects -----------------------------------------------------------
# Commerce timestamps are dataset local and carry no timezone.


class _Source(BaseModel):
    model_config = Strict
    batch_id: str
    provenance: Literal["olist", "authored"]


class Customer(_Source):
    customer_id: str
    customer_unique_id: str
    state: str


class Seller(_Source):
    seller_id: str
    state: str


class Product(_Source):
    product_id: str
    category: str | None


class Order(_Source):
    """Historical view of an order. Deliberately has no order_status field."""

    order_id: str
    customer_id: str
    purchased_at: datetime
    approved_at: datetime | None
    carrier_at: datetime | None
    delivered_at: datetime | None
    estimated_at: datetime


class OrderLine(_Source):
    order_id: str
    line_no: int = Field(ge=1)
    product_id: str
    seller_id: str
    shipping_limit_at: datetime
    price_centavos: int = Field(ge=0)
    freight_centavos: int = Field(ge=0)


class _Synthetic(BaseModel):
    model_config = Strict
    scenario_id: str
    is_synthetic: Literal[True] = True


class Carrier(_Synthetic):
    carrier_code: str
    display_name: str


class DisruptionEvent(_Synthetic):
    event_id: UUID
    kind: Literal["carrier_backlog", "seller_stockout", "regional_weather", "system_outage"]
    carrier_code: str | None
    seller_id: str | None
    affected_states: list[str]
    starts_at: datetime
    ends_at: datetime
    summary: str


DOMAIN_MODELS: dict[str, type[BaseModel]] = {
    "Customer": Customer,
    "Order": Order,
    "OrderLine": OrderLine,
    "Seller": Seller,
    "Product": Product,
    "Carrier": Carrier,
    "DisruptionEvent": DisruptionEvent,
}
