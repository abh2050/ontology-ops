"""FastAPI application: authenticated, authorization-scoped read endpoints (M2).

Scope is reloaded from the database on every request and never cached. Hidden
and nonexistent objects return the same 404. Logs carry the route template,
status, and latency only: never IDs, query strings, or tokens.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Connection, text

from ops.auth import AuthError, Identity, verify_access_token
from ops.db import engine
from ops.ontology.registry import registry
from ops.queries import tools as T
from ops.queries.graph import build_graph
from ops.queries.late_orders import DEMO_WINDOW
from ops.queries.scope import Principal, load_principal
from ops.settings import get_settings

SETTINGS = get_settings()  # refuses AUTH_MODE=local outside DEPLOY_ENV=local
log = logging.getLogger("ops.api")
TS = "%Y-%m-%d %H:%M:%S"
NOT_FOUND = {"detail": "not found or not visible"}



@asynccontextmanager
async def _lifespan(_: FastAPI):
    # The default access log prints request paths, which can carry object IDs.
    logging.getLogger("uvicorn.access").disabled = True
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    yield


app = FastAPI(title="Ontology driven operational AI", version="0.1.0",
              docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan)


@app.get("/ui-config.json")
def ui_config() -> dict:
    """Public OAuth identifiers only; no credentials or source data."""
    return {"auth_mode": SETTINGS.auth_mode, "domain": SETTINGS.cognito_domain,
            "client_id": SETTINGS.cognito_client_id,
            "issuer": (f"https://cognito-idp.{SETTINGS.aws_region}.amazonaws.com/"
                       f"{SETTINGS.cognito_user_pool_id}") if SETTINGS.cognito_user_pool_id
            else None}


@app.middleware("http")
async def _headers_and_safe_log(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    template = getattr(route, "path", "unmatched")
    if template.startswith("/api/") and template != "/api/meta":
        response.headers["Cache-Control"] = "private, no-store"
    log.info("request route=%s method=%s status=%s ms=%.1f", template, request.method,
             response.status_code, (time.perf_counter() - started) * 1000)
    return response


@app.exception_handler(T.NotVisible)
async def _not_visible(_: Request, __: T.NotVisible):
    return JSONResponse(NOT_FOUND, status_code=404)


@app.exception_handler(T.ToolInputError)
async def _bad_tool_input(_: Request, exc: T.ToolInputError):
    return JSONResponse({"detail": "invalid request"}, status_code=422)


@app.exception_handler(RequestValidationError)
async def _bad_request(_: Request, exc: RequestValidationError):
    # Report field locations only; never echo submitted values.
    fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
    return JSONResponse({"detail": "invalid request", "fields": fields}, status_code=422)


# ---- dependencies --------------------------------------------------------------------


def identity(authorization: Annotated[str | None, Header()] = None) -> Identity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        return verify_access_token(authorization.removeprefix("Bearer "), SETTINGS)
    except AuthError:
        raise HTTPException(401, "authentication required",
                            headers={"WWW-Authenticate": "Bearer"}) from None


def connection():
    with engine("api").connect() as conn:
        yield conn


@cache
def _batches_cached(version: int) -> tuple[dict, ...]:
    with engine("api").connect() as conn:
        rows = conn.execute(text(
            "SELECT batch_id, manifest->>'provenance' AS provenance, "
            "manifest->'demo_as_of'->>'as_of' AS demo_as_of FROM source_batches "
            "ORDER BY (manifest->>'provenance' = 'olist') DESC, imported_at DESC")).all()
    return tuple(dict(r._mapping) for r in rows)


def batches() -> tuple[dict, ...]:
    return _batches_cached(0)


def resolve_batch(batch: str | None) -> dict:
    known = batches()
    if not known:
        raise HTTPException(503, "no data imported")
    if batch is None:
        return known[0]
    for b in known:
        if b["batch_id"] == batch:
            return b
    _batches_cached.cache_clear()
    for b in batches():
        if b["batch_id"] == batch:
            return b
    raise HTTPException(404, NOT_FOUND["detail"])


class Ctx:
    def __init__(self, conn: Connection, principal: Principal, batch: dict, as_of: datetime):
        self.conn, self.principal, self.batch, self.as_of = conn, principal, batch, as_of


def ctx(
    who: Annotated[Identity, Depends(identity)],
    conn: Annotated[Connection, Depends(connection)],
    batch: Annotated[str | None, Query(max_length=80)] = None,
    as_of: Annotated[datetime | None, Query()] = None,
) -> Ctx:
    b = resolve_batch(batch)
    if as_of is None:
        if not b["demo_as_of"]:
            raise HTTPException(422, "as_of required: batch has no demo as_of")
        as_of = datetime.strptime(b["demo_as_of"], TS)
    if as_of.tzinfo is not None:
        raise HTTPException(422, "as_of is dataset local and must not carry a timezone")
    return Ctx(conn, load_principal(conn, who.subject, b["batch_id"]), b, as_of)


Context = Annotated[Ctx, Depends(ctx)]


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def _run(c: Ctx, tool: str, **payload):
    payload = {k: v for k, v in payload.items() if v is not None}
    return T.run_tool(c.conn, c.principal, tool, {"as_of": _iso(c.as_of), **payload})


# ---- endpoints -----------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@cache
def _ontology_meta() -> dict:
    defs = registry()
    return {
        "ontology_version": defs.version,
        "relationships": {k: v.model_dump() for k, v in defs.relationships.items()},
        "object_types": {k: v.model_dump() for k, v in defs.object_types.items()},
        "derived_functions": {k: v.semantics for k, v in defs.derived_functions.items()},
        "default_purchase_window": [DEMO_WINDOW[0].isoformat(), DEMO_WINDOW[1].isoformat()],
        "timestamps": "dataset local, no timezone",
    }


@app.get("/api/meta")
def meta(request: Request, response: Response,
         _: Annotated[Identity, Depends(identity)]) -> Response:
    with engine("api").connect() as conn:
        scenarios = conn.execute(text(
            "SELECT scenario_id, seed, description FROM synthetic_scenarios "
            "ORDER BY scenario_id")).all()
    body = {**_ontology_meta(), "batches": list(batches()),
            "scenarios": [dict(r._mapping) | {"is_synthetic": True} for r in scenarios]}
    raw = json.dumps(body, sort_keys=True, default=str)
    etag = '"' + hashlib.sha256(raw.encode()).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(raw, media_type="application/json", headers=headers)


@app.get("/api/me")
def me(c: Context) -> dict:
    p = c.principal
    granted = 0
    if p.provisioned:
        granted = c.conn.execute(text(
            "SELECT count(*) FROM seller_grants WHERE subject = :s AND batch_id = :b"),
            {"s": p.subject, "b": p.batch_id}).scalar_one()
    return {"subject": p.subject, "role": p.role if p.active else None,
            "provisioned": p.provisioned, "batch_id": p.batch_id,
            "granted_sellers": granted, "as_of": _iso(c.as_of)}


@app.get("/api/queue")
def queue(
    c: Context,
    purchase_from: str | None = Query(None, max_length=10),
    purchase_to: str | None = Query(None, max_length=10),
    seller_id: str | None = Query(None, max_length=32),
    customer_state: str | None = Query(None, max_length=2),
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = Query(None, max_length=200),
) -> dict:
    page = _run(c, "find_late_orders", purchase_from=purchase_from, purchase_to=purchase_to,
                seller_id=seller_id, customer_state=customer_state, limit=limit, cursor=cursor)
    return page.model_dump(mode="json")


@app.get("/api/orders/{order_id}")
def order(order_id: str, c: Context) -> dict:
    return _run(c, "get_order_snapshot", order_id=order_id).model_dump(mode="json")


@app.get("/api/sellers/{seller_id}/scope")
def seller_scope(seller_id: str, c: Context,
                 limit: int = Query(100, ge=1, le=100)) -> dict:
    return _run(c, "get_seller_exception_scope", seller_id=seller_id,
                limit=limit).model_dump(mode="json")


@app.get("/api/context")
def context(c: Context, target_type: Literal["Order", "Seller"], target_id: str,
            scenario_id: str | None = Query(None, max_length=63)) -> dict:
    payload = {"as_of": _iso(c.as_of), "target_type": target_type, "target_id": target_id,
               "scenario_id": scenario_id}
    return T.run_tool(c.conn, c.principal, "get_disruption_context",
                      payload).model_dump(mode="json")


@app.get("/api/graph")
def graph(c: Context, root_type: Literal["Order", "Seller"], root_id: str,
          scenario_id: str | None = Query(None, max_length=63)) -> dict:
    # Reuse the tool schemas for strict ID validation before building the projection.
    if root_type == "Order":
        T.OrderSnapshotInput.model_validate_json(json.dumps(
            {"order_id": root_id, "as_of": _iso(c.as_of)}))
    else:
        T.SellerScopeInput.model_validate_json(json.dumps(
            {"seller_id": root_id, "as_of": _iso(c.as_of)}))
    if scenario_id is not None:
        T.DisruptionContextInput.model_validate_json(json.dumps(
            {"as_of": _iso(c.as_of), "target_type": root_type, "target_id": root_id,
             "scenario_id": scenario_id}))
    return build_graph(c.conn, c.principal, root_type, root_id, c.as_of,
                       scenario_id).model_dump(mode="json")


@app.exception_handler(ValueError)
async def _value_error(_: Request, __: ValueError):
    return JSONResponse({"detail": "invalid request"}, status_code=422)


# ---- jobs (M3) -------------------------------------------------------------------------

from ops.jobs.outbox import JobRequest, SubmitError, submit_job  # noqa: E402

JOB_READ_SQL = text("""
SELECT job_id, subject, batch_id, scenario_id, as_of, state, input, result, scope_hash,
       evidence_hash, revision, created_at
FROM jobs WHERE job_id = CAST(:job_id AS uuid)
""")


class JobBody(JobRequest):
    as_of: datetime | None = None  # defaults to the batch demo as_of


@app.post("/api/jobs", status_code=202)
def create_job(
    body: JobBody,
    who: Annotated[Identity, Depends(identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", max_length=128)],
    batch: Annotated[str | None, Query(max_length=80)] = None,
) -> JSONResponse:
    b = resolve_batch(batch)
    as_of = body.as_of or datetime.strptime(b["demo_as_of"], TS)
    req = JobRequest(**{**body.model_dump(), "as_of": as_of})
    with engine("api").begin() as conn:
        principal = load_principal(conn, who.subject, b["batch_id"])
        try:
            job_id, created = submit_job(conn, principal, req, idempotency_key)
        except SubmitError as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status)
    return JSONResponse({"job_id": job_id, "created": created},
                        status_code=202 if created else 200)


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str, request: Request,
             who: Annotated[Identity, Depends(identity)]) -> Response:
    try:
        import uuid as _uuid

        _uuid.UUID(job_id)
    except ValueError:
        return JSONResponse(NOT_FOUND, status_code=404)
    with engine("api").connect() as conn:
        row = conn.execute(JOB_READ_SQL, {"job_id": job_id}).one_or_none()
        if row is None or row.subject != who.subject:
            return JSONResponse(NOT_FOUND, status_code=404)
        principal = load_principal(conn, who.subject, row.batch_id)
    etag = f'"{row.job_id}-{row.revision}-{principal.scope_hash[:12]}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    body = {"job_id": str(row.job_id), "state": row.state, "batch_id": row.batch_id,
            "scenario_id": row.scenario_id, "as_of": _iso(row.as_of), "input": row.input,
            "revision": row.revision, "evidence_hash": row.evidence_hash, "result": None}
    if not principal.provisioned or principal.scope_hash != row.scope_hash:
        # Saved results are re-authorized on read; a scope change withholds them.
        body["state"] = "blocked" if row.state == "ready" else row.state
        body["result"] = {"reason": "SCOPE_CHANGED", "detail": "regenerate the job"}
    else:
        body["result"] = row.result
    return Response(json.dumps(body, default=str), media_type="application/json",
                    headers=headers)


# ---- proposals and approval (M4) -------------------------------------------------------

from pydantic import BaseModel as _Body  # noqa: E402

from ops.commands import proposals as P  # noqa: E402


class Decision(_Body):
    decision: Literal["approve", "reject"]
    expected_revision: int
    reason: str = ""


def _uuid_or_404(value: str) -> None:
    import uuid as _uuid

    try:
        _uuid.UUID(value)
    except ValueError:
        raise HTTPException(404, NOT_FOUND["detail"]) from None


@app.post("/api/jobs/{job_id}/proposal")
def propose(job_id: str, who: Annotated[Identity, Depends(identity)],
            batch: Annotated[str | None, Query(max_length=80)] = None) -> JSONResponse:
    _uuid_or_404(job_id)
    b = resolve_batch(batch)
    error = None
    with engine("api").begin() as conn:
        principal = load_principal(conn, who.subject, b["batch_id"])
        try:
            proposal, created = P.create_proposal(conn, principal, job_id)
        except P.CommandError as exc:
            error = exc
    if error is not None:
        return JSONResponse({"detail": error.detail, "code": error.code},
                            status_code=error.status)
    return JSONResponse(proposal, status_code=201 if created else 200)


@app.get("/api/proposals")
def list_proposals(c: Context, state: str | None = Query(None, max_length=20)) -> dict:
    rows = c.conn.execute(text(
        f"SELECT {P.PROPOSAL_COLUMNS} FROM proposals WHERE payload->>'batch_id' = :b "
        "AND (CAST(:s AS text) IS NULL OR state = :s) ORDER BY created_at DESC LIMIT 200"),
        {"b": c.principal.batch_id, "s": state}).all()
    visible = [P.serialize(r) for r in rows if P.actor_can_see(c.conn, c.principal, r)][:50]
    return {"items": visible, "batch_id": c.principal.batch_id}


@app.get("/api/proposals/{proposal_id}")
def read_proposal(proposal_id: str, c: Context) -> dict:
    _uuid_or_404(proposal_id)
    row = P._proposal_row(c.conn, proposal_id)
    if row is None or not P.actor_can_see(c.conn, c.principal, row):
        raise HTTPException(404, NOT_FOUND["detail"])
    return P.serialize(row)


@app.post("/api/proposals/{proposal_id}/decision")
def decide(proposal_id: str, body: Decision, who: Annotated[Identity, Depends(identity)],
           batch: Annotated[str | None, Query(max_length=80)] = None) -> JSONResponse:
    _uuid_or_404(proposal_id)
    b = resolve_batch(batch)
    error = None
    with engine("api").begin() as conn:
        reviewer = load_principal(conn, who.subject, b["batch_id"])
        try:
            outcome = P.decide(conn, reviewer, proposal_id, body.decision,
                               body.expected_revision, body.reason)
        except P.CommandError as exc:
            error = exc  # stale transitions and audit rows still commit
    if error is not None:
        return JSONResponse({"detail": error.detail, "code": error.code},
                            status_code=error.status)
    return JSONResponse(outcome)


@app.get("/api/cases")
def list_cases(c: Context) -> dict:
    rows = c.conn.execute(text(
        "SELECT c.case_id, c.case_key, c.owner_subject, c.case_payload, c.created_at, "
        "p.proposal_id, p.created_by, p.kind, p.target_type, p.target_id, p.payload, p.state, "
        "p.revision, p.reviewed_by, p.review_reason, p.evidence_hash, p.proposal_hash, "
        "p.job_id, p.created_at AS p_created FROM cases c JOIN proposals p "
        "ON p.proposal_id = c.proposal_id WHERE c.case_payload->>'batch_id' = :b "
        "ORDER BY c.created_at DESC LIMIT 200"), {"b": c.principal.batch_id}).all()
    out = []
    for r in rows:
        if r.owner_subject == c.principal.subject or (
                c.principal.role == "reviewer" and P.actor_can_see(c.conn, c.principal, r)):
            out.append({"case_id": str(r.case_id), "owner": r.owner_subject,
                        "proposal_id": str(r.proposal_id), "payload": r.case_payload,
                        "created_at": r.created_at.isoformat()})
    return {"items": out[:50]}


# Keep the browser application on the API origin. Mount this last so no UI
# fallback can shadow an authenticated /api route. The directory is absent in
# source-only test environments and present in the production image.
UI_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if UI_DIST.is_dir():
    @app.get("/auth/callback", include_in_schema=False)
    def auth_callback() -> FileResponse:
        return FileResponse(UI_DIST / "index.html", headers={"Cache-Control": "no-store"})

    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="frontend")
