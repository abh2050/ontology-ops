"""Load and validate ontology definitions. The result is immutable and cached in process."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

from ops.ontology.models import DOMAIN_MODELS, Definitions

DEFINITIONS_PATH = Path(__file__).with_name("definitions.yaml")
ONTOLOGY_VERSION = "operational-commerce-v1"


class OntologyError(ValueError):
    pass


def validate(defs: Definitions) -> Definitions:
    types = defs.object_types
    for name, obj in types.items():
        if obj.looks_synthetic and obj.synthetic is not True:
            raise OntologyError(f"synthetic type {name} must declare synthetic: true")
        if obj.kind == "domain" and name not in DOMAIN_MODELS:
            raise OntologyError(f"domain type {name} has no Pydantic model")

    for name, rel in defs.relationships.items():
        for end in (rel.source, rel.target):
            if end not in types:
                raise OntologyError(f"relationship {name} references unknown type {end}")
        touches_synthetic = (
            rel.provenance == "synthetic"
            or types[rel.source].looks_synthetic
            or types[rel.target].looks_synthetic
        )
        if touches_synthetic and rel.synthetic is not True:
            raise OntologyError(f"synthetic relationship {name} must declare synthetic: true")
        if rel.derived_by and rel.derived_by not in defs.derived_functions:
            raise OntologyError(f"relationship {name} uses unknown function {rel.derived_by}")

    collapse = defs.display_projection.collapse
    for t in (collapse.object, *collapse.into_edge):
        if t not in types:
            raise OntologyError(f"display projection references unknown type {t}")
    return defs


def load(path: Path = DEFINITIONS_PATH) -> Definitions:
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    try:
        defs = Definitions.model_validate(raw)
    except ValueError as exc:
        raise OntologyError(str(exc)) from exc
    return validate(defs)


@cache
def registry() -> Definitions:
    defs = load()
    if defs.version != ONTOLOGY_VERSION:
        raise OntologyError(f"expected {ONTOLOGY_VERSION}, found {defs.version}")
    return defs
