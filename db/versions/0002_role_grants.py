"""Database role privileges (spec 11.6).

import: writes source tables, quarantine, and synthetic tables.
api:    reads source and synthetic data; writes jobs, outbox, proposals, cases,
        internal drafts, and audit events.
worker: reads source and synthetic data; writes job results, checkpoints,
        outbox sent_at, and model call records. Cannot approve or insert cases.
No runtime role may modify users or seller_grants, or delete audit events.

Revision ID: 0002_role_grants
Revises: 0001_initial
"""

from alembic import op

revision = "0002_role_grants"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

SOURCE = "source_batches, sellers, customers, products, orders, order_items"
SYNTHETIC = "synthetic_scenarios, carriers, carrier_assignments, disruption_events"
IDENTITY = "users, seller_grants"
APP = (
    "jobs, outbox, proposals, cases, internal_drafts, audit_events, "
    "usage_days, eval_runs, model_calls"
)
RUNTIME = "ops_import, ops_api, ops_worker"

GRANTS = [
    f"GRANT USAGE ON SCHEMA public TO {RUNTIME}",
    # import
    f"GRANT SELECT, INSERT ON {SOURCE}, quarantine TO ops_import",
    "GRANT UPDATE (manifest) ON source_batches TO ops_import",
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SYNTHETIC} TO ops_import",
    # api
    f"GRANT SELECT ON {SOURCE}, {SYNTHETIC}, {IDENTITY} TO ops_api",
    f"GRANT SELECT ON {APP} TO ops_api",
    "GRANT INSERT ON jobs, outbox, proposals, cases, internal_drafts, audit_events TO ops_api",
    "GRANT UPDATE (state, revision, reviewed_by, review_reason) ON proposals TO ops_api",
    # worker
    f"GRANT SELECT ON {SOURCE}, {SYNTHETIC}, {IDENTITY} TO ops_worker",
    "GRANT SELECT ON jobs, outbox, model_calls, usage_days, eval_runs TO ops_worker",
    "GRANT UPDATE (state, checkpoint, result, evidence_hash, lease_token, lease_until, revision)"
    " ON jobs TO ops_worker",
    "GRANT UPDATE (sent_at) ON outbox TO ops_worker",
    "GRANT INSERT, UPDATE ON model_calls, usage_days TO ops_worker",
    "GRANT INSERT, UPDATE (admitted_calls) ON eval_runs TO ops_worker",
]


def upgrade() -> None:
    for statement in GRANTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {RUNTIME}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {RUNTIME}")
