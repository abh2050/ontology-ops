import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from ops.auth import issue_local_token
from ops.data.users import seed_users
from ops.settings import REPO_ROOT

pytestmark = pytest.mark.integration

LABELS = json.loads((REPO_ROOT / "data" / "fixtures" / "labels.json").read_text())
FX = {"batch": "fixtures-v1", "as_of": "2018-03-15T23:59:59"}
SPLIT = LABELS["split_ab_00"]


@pytest.fixture(scope="module")
def client(db):
    seed_users("local")
    from ops.api import app

    with TestClient(app) as c:
        yield c


def auth(subject: str, **kw) -> dict:
    return {"Authorization": f"Bearer {issue_local_token(subject, **kw)}"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic abc"},
    ],
)
def test_missing_or_malformed_token(client, headers):
    assert client.get("/api/queue", params=FX, headers=headers).status_code == 401


@pytest.mark.parametrize(
    "kw",
    [
        {"token_use": "id"},
        {"issuer": "https://evil.example/pool"},
        {"client_id": "another-client"},
        {"expires_at": int(time.time()) - 10},
    ],
    ids=["id-token", "issuer", "client", "expired"],
)
def test_token_claims_verified(client, kw):
    r = client.get("/api/queue", params=FX, headers=auth("reviewer", **kw))
    assert r.status_code == 401 and r.json() == {"detail": "authentication required"}


def test_valid_token_without_provisioned_user_sees_nothing(client):
    h = auth("someone-with-a-valid-token")
    q = client.get("/api/queue", params=FX, headers=h)
    assert q.status_code == 200 and q.json()["aggregates"]["late_open_orders"] == 0
    assert client.get(f"/api/orders/{LABELS['single_late_00']}", params=FX,
                      headers=h).status_code == 404
    assert client.get("/api/me", params=FX, headers=h).json()["provisioned"] is False


def test_viewer_sees_nothing(client):
    h = auth("viewer")
    q = client.get("/api/queue", params=FX, headers=h).json()
    assert q["items"] == [] and q["aggregates"]["line_value_centavos"] == 0
    me = client.get("/api/me", params=FX, headers=h).json()
    assert me["role"] == "viewer" and me["granted_sellers"] == 0


def test_hidden_and_missing_orders_are_indistinguishable(client, caplog):
    caplog.set_level("DEBUG")
    h = auth("operator_a")
    hidden = client.get(f"/api/orders/{SPLIT}", params=FX, headers=h)
    missing = client.get(f"/api/orders/{'f' * 32}", params=FX, headers=h)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json() == {"detail": "not found or not visible"}
    g = client.get("/api/graph", params={**FX, "root_type": "Order", "root_id": SPLIT},
                   headers=h)
    assert g.status_code == 404 and SPLIT not in g.text
    server_logs = "\n".join(r.getMessage() for r in caplog.records
                            if not r.name.startswith("httpx"))  # httpx is the test client
    assert SPLIT not in server_logs
    assert "route=/api/orders/{order_id}" in server_logs


def test_validation_errors_do_not_echo_input(client):
    probe = "zz" + SPLIT[2:]
    r = client.get(f"/api/orders/{probe}", params=FX, headers=auth("operator_a"))
    assert r.status_code == 422 and probe not in r.text
    r = client.get("/api/queue", params={**FX, "limit": 1000}, headers=auth("reviewer"))
    assert r.status_code == 422 and "1000" not in r.text


def test_reviewer_reads_and_headers(client):
    h = auth("reviewer")
    q = client.get("/api/queue", params={**FX, "limit": 5}, headers=h)
    assert q.status_code == 200 and q.headers["cache-control"] == "private, no-store"
    body = q.json()
    assert len(body["items"]) == 5 and body["next_cursor"]
    nxt = client.get("/api/queue", params={**FX, "limit": 5, "cursor": body["next_cursor"]},
                     headers=h).json()
    assert not {i["order_id"] for i in body["items"]} & {i["order_id"] for i in nxt["items"]}
    o = client.get(f"/api/orders/{SPLIT}", params=FX, headers=h)
    assert o.status_code == 200 and o.json()["metrics"]["seller_count"] == 2
    s = client.get(f"/api/sellers/{LABELS['seller_a01']}/scope", params=FX, headers=h)
    assert s.status_code == 200 and s.json()["aggregates"]["late_open_orders"] > 0
    g = client.get("/api/graph", params={**FX, "root_type": "Order",
                                         "root_id": LABELS["single_late_00"],
                                         "scenario_id": "base-v1"}, headers=h)
    assert g.status_code == 200 and len(g.json()["nodes"]) <= 50
    ctx = client.get("/api/context", params={**FX, "target_type": "Seller",
                                             "target_id": LABELS["seller_a01"]}, headers=h)
    assert ctx.status_code == 200 and ctx.json()["events"] == []


def test_meta_etag(client):
    h = auth("viewer")
    first = client.get("/api/meta", headers=h)
    assert first.status_code == 200 and first.json()["ontology_version"]
    again = client.get("/api/meta", headers={**h, "If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


def test_api_refuses_local_auth_outside_local():
    env = {**os.environ, "DEPLOY_ENV": "aws", "AUTH_MODE": "local"}
    r = subprocess.run([sys.executable, "-c", "import ops.api"], env=env, cwd=REPO_ROOT,
                       capture_output=True, text=True)
    assert r.returncode != 0 and "AUTH_MODE=local is refused" in r.stderr


def test_local_tokens_not_issued_outside_local(monkeypatch):
    from ops import auth as A
    from ops.settings import Settings

    monkeypatch.setattr(A, "get_settings", lambda: Settings(deploy_env="local",
                                                             auth_mode="cognito"))
    with pytest.raises(A.AuthError):
        A.issue_local_token("reviewer")


def test_job_submission_and_read(client, db):
    import uuid

    from sqlalchemy import text

    with db("admin").begin() as c:
        c.execute(text("UPDATE outbox SET sent_at = now() WHERE sent_at IS NULL"))
        c.execute(text("UPDATE jobs SET state = 'failed', lease_token = NULL, lease_until = NULL "
                       "WHERE state IN ('queued', 'running', 'validating') "
                       "AND NOT (input ? 'eval_run_id')"))  # never touch evaluation jobs
    key = str(uuid.uuid4())
    body = {"target_type": "Seller", "target_id": LABELS["seller_a01"], "scenario_id": None,
            "as_of": "2018-03-15T23:59:59"}
    h = {**auth("operator_a"), "Idempotency-Key": key}
    first = client.post("/api/jobs", params={"batch": "fixtures-v1"}, json=body, headers=h)
    assert first.status_code == 202 and first.json()["created"]
    job_id = first.json()["job_id"]
    again = client.post("/api/jobs", params={"batch": "fixtures-v1"}, json=body, headers=h)
    assert again.status_code == 200 and again.json()["job_id"] == job_id
    changed = client.post("/api/jobs", params={"batch": "fixtures-v1"},
                          json={**body, "target_id": LABELS["seller_a02"]}, headers=h)
    assert changed.status_code == 409
    read = client.get(f"/api/jobs/{job_id}", headers=auth("operator_a"))
    assert read.status_code == 200 and read.json()["state"] == "queued"
    etag = read.headers["etag"]
    assert client.get(f"/api/jobs/{job_id}", headers={**auth("operator_a"),
                                                       "If-None-Match": etag}).status_code == 304
    assert client.get(f"/api/jobs/{job_id}", headers=auth("operator_b")).status_code == 404
    assert client.get("/api/jobs/not-a-uuid", headers=auth("operator_a")).status_code == 404


@pytest.mark.parametrize(("subject", "target", "status"), [
    ("viewer", "seller_a01", 403),
    ("operator_a", "split_ab_00", 404),
])
def test_job_submission_rejections(client, subject, target, status):
    import uuid

    ttype = "Order" if target.startswith("split") else "Seller"
    r = client.post("/api/jobs", params={"batch": "fixtures-v1"},
                    json={"target_type": ttype, "target_id": LABELS[target], "scenario_id": None},
                    headers={**auth(subject), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == status
    assert LABELS[target] not in r.text
