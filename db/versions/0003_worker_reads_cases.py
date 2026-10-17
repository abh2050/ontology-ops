"""Worker may read cases and proposals for the deterministic existing-case check.

It still cannot insert cases or change proposals.

Revision ID: 0003_worker_reads_cases
Revises: 0002_role_grants
"""

from alembic import op

revision = "0003_worker_reads_cases"
down_revision = "0002_role_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT SELECT ON cases, proposals, internal_drafts TO ops_worker")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON cases, proposals, internal_drafts FROM ops_worker")
