"""Evidence references and canonical hashing."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

EvidenceType = Literal[
    "Order", "OrderLine", "Seller", "Product", "Customer", "Carrier", "DisruptionEvent",
    "Aggregate",
]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ref: str            # stable reference, e.g. "Order:<id>" or "OrderLine:<id>#2"
    type: EvidenceType
    batch_id: str | None
    is_synthetic: bool = False
    provenance: Literal["olist", "authored", "synthetic", "derived"]


def ref_for(type_: str, ident: str, batch_id: str | None, provenance: str,
            synthetic: bool = False) -> EvidenceRef:
    return EvidenceRef(ref=f"{type_}:{ident}", type=type_, batch_id=batch_id,
                       is_synthetic=synthetic, provenance=provenance)


def _default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"not serializable: {type(value)}")


def canonical_json(payload: Any) -> str:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json", exclude={"evidence_hash"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_default)


def evidence_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()
