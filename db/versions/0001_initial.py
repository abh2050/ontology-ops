"""Initial schema: source, synthetic, application, and cost tables (spec sections 7 and 9).

Revision ID: 0001_initial
Revises:
"""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

PROVENANCE = "provenance text NOT NULL CHECK (provenance IN ('olist','authored'))"
SYNTHETIC = "is_synthetic boolean NOT NULL DEFAULT true CHECK (is_synthetic)"

REASON_CODES = (
    "NEG_MONEY", "BAD_MONEY", "APPROVED_BEFORE_PURCHASE", "CARRIER_BEFORE_PURCHASE",
    "DELIVERED_BEFORE_CARRIER", "DELIVERED_BEFORE_PURCHASE", "MISSING_ESTIMATE",
    "BROKEN_FK", "ORDER_QUARANTINED", "CONFLICTING_DUPLICATE", "DUPLICATE_IDENTICAL",
    "BAD_ID", "BAD_TIMESTAMP", "BAD_VALUE",
)

STATEMENTS = [
    # ---- source data -------------------------------------------------------
    """
    CREATE TABLE source_batches (
        batch_id text PRIMARY KEY,
        manifest jsonb NOT NULL,
        imported_at timestamptz NOT NULL DEFAULT now()
    )""",
    """
    CREATE TABLE users (
        subject text PRIMARY KEY,
        role text NOT NULL CHECK (role IN ('operator','reviewer','viewer')),
        active boolean NOT NULL DEFAULT true
    )""",
    f"""
    CREATE TABLE sellers (
        batch_id text NOT NULL REFERENCES source_batches,
        seller_id text NOT NULL,
        state text NOT NULL,
        {PROVENANCE},
        PRIMARY KEY (batch_id, seller_id)
    )""",
    """
    CREATE TABLE seller_grants (
        subject text NOT NULL REFERENCES users,
        batch_id text NOT NULL,
        seller_id text NOT NULL,
        PRIMARY KEY (subject, batch_id, seller_id),
        FOREIGN KEY (batch_id, seller_id) REFERENCES sellers
    )""",
    f"""
    CREATE TABLE customers (
        batch_id text NOT NULL REFERENCES source_batches,
        customer_id text NOT NULL,
        customer_unique_id text NOT NULL,
        state text NOT NULL,
        {PROVENANCE},
        PRIMARY KEY (batch_id, customer_id)
    )""",
    f"""
    CREATE TABLE products (
        batch_id text NOT NULL REFERENCES source_batches,
        product_id text NOT NULL,
        category text NULL,
        {PROVENANCE},
        PRIMARY KEY (batch_id, product_id)
    )""",
    f"""
    CREATE TABLE orders (
        batch_id text NOT NULL REFERENCES source_batches,
        order_id text NOT NULL,
        customer_id text NOT NULL,
        purchased_at timestamp NOT NULL,
        approved_at timestamp NULL,
        carrier_at timestamp NULL,
        delivered_at timestamp NULL,
        estimated_at timestamp NOT NULL,
        order_status text,
        {PROVENANCE},
        PRIMARY KEY (batch_id, order_id),
        FOREIGN KEY (batch_id, customer_id) REFERENCES customers
    )""",
    "COMMENT ON COLUMN orders.order_status IS "
    "'Data quality reporting only. Never read by snapshot tools, queries, prompts, or UI.'",
    f"""
    CREATE TABLE order_items (
        batch_id text NOT NULL,
        order_id text NOT NULL,
        line_no integer NOT NULL CHECK (line_no >= 1),
        product_id text NOT NULL,
        seller_id text NOT NULL,
        shipping_limit_at timestamp NOT NULL,
        price_centavos bigint NOT NULL CHECK (price_centavos >= 0),
        freight_centavos bigint NOT NULL CHECK (freight_centavos >= 0),
        {PROVENANCE},
        PRIMARY KEY (batch_id, order_id, line_no),
        FOREIGN KEY (batch_id, order_id) REFERENCES orders,
        FOREIGN KEY (batch_id, product_id) REFERENCES products,
        FOREIGN KEY (batch_id, seller_id) REFERENCES sellers
    )""",
    f"""
    CREATE TABLE quarantine (
        quarantine_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        batch_id text NOT NULL REFERENCES source_batches,
        source_file text NOT NULL,
        source_row_number integer NOT NULL,
        reason_code text NOT NULL CHECK (reason_code IN ({", ".join(f"'{c}'" for c in REASON_CODES)})),
        raw_row jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    # ---- synthetic scenario layer -----------------------------------------
    f"""
    CREATE TABLE synthetic_scenarios (
        scenario_id text PRIMARY KEY,
        seed integer NOT NULL,
        generator_version text NOT NULL,
        description text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        {SYNTHETIC}
    )""",
    f"""
    CREATE TABLE carriers (
        scenario_id text NOT NULL REFERENCES synthetic_scenarios ON DELETE CASCADE,
        carrier_code text NOT NULL,
        display_name text NOT NULL,
        {SYNTHETIC},
        PRIMARY KEY (scenario_id, carrier_code)
    )""",
    f"""
    CREATE TABLE carrier_assignments (
        scenario_id text NOT NULL REFERENCES synthetic_scenarios ON DELETE CASCADE,
        batch_id text NOT NULL,
        order_id text NOT NULL,
        carrier_code text NOT NULL,
        assigned_at timestamp NOT NULL,
        {SYNTHETIC},
        PRIMARY KEY (scenario_id, batch_id, order_id),
        FOREIGN KEY (batch_id, order_id) REFERENCES orders,
        FOREIGN KEY (scenario_id, carrier_code) REFERENCES carriers ON DELETE CASCADE
    )""",
    f"""
    CREATE TABLE disruption_events (
        event_id uuid PRIMARY KEY,
        scenario_id text NOT NULL REFERENCES synthetic_scenarios ON DELETE CASCADE,
        kind text NOT NULL CHECK (kind IN
            ('carrier_backlog','seller_stockout','regional_weather','system_outage')),
        carrier_code text NULL,
        seller_id text NULL,
        affected_states text[] NOT NULL DEFAULT '{{}}',
        starts_at timestamp NOT NULL,
        ends_at timestamp NOT NULL CHECK (ends_at >= starts_at),
        summary text NOT NULL,
        {SYNTHETIC},
        FOREIGN KEY (scenario_id, carrier_code) REFERENCES carriers ON DELETE CASCADE
    )""",
    # ---- application tables ------------------------------------------------
    """
    CREATE TABLE jobs (
        job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        subject text NOT NULL REFERENCES users,
        idempotency_key text NOT NULL,
        request_hash text NOT NULL,
        batch_id text NOT NULL REFERENCES source_batches,
        scenario_id text NULL REFERENCES synthetic_scenarios,
        ontology_version text NOT NULL,
        as_of timestamp NOT NULL,
        state text NOT NULL CHECK (state IN
            ('queued','running','validating','ready','failed','unknown','blocked')),
        input jsonb NOT NULL,
        checkpoint jsonb NOT NULL DEFAULT '{}',
        result jsonb NULL,
        scope_hash text NOT NULL,
        evidence_hash text NULL,
        lease_token uuid NULL,
        lease_until timestamptz NULL,
        revision bigint NOT NULL DEFAULT 0,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (subject, idempotency_key)
    )""",
    """
    CREATE TABLE outbox (
        event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        job_id uuid NOT NULL REFERENCES jobs,
        created_at timestamptz NOT NULL DEFAULT now(),
        sent_at timestamptz NULL
    )""",
    """
    CREATE TABLE proposals (
        proposal_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        job_id uuid NOT NULL REFERENCES jobs,
        created_by text NOT NULL REFERENCES users,
        kind text NOT NULL CHECK (kind IN ('CreateInvestigation','DraftCustomerUpdate')),
        target_type text NOT NULL CHECK (target_type IN ('Order','Seller')),
        target_id text NOT NULL,
        payload jsonb NOT NULL,
        evidence_hash text NOT NULL,
        proposal_hash text NOT NULL,
        state text NOT NULL DEFAULT 'pending' CHECK (state IN
            ('pending','executed','rejected','stale','needs_review')),
        revision bigint NOT NULL DEFAULT 0,
        reviewed_by text NULL REFERENCES users,
        review_reason text NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    """
    CREATE TABLE cases (
        case_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        proposal_id uuid NOT NULL UNIQUE REFERENCES proposals,
        case_key text NOT NULL UNIQUE,
        owner_subject text NOT NULL REFERENCES users,
        case_payload jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    """
    CREATE TABLE internal_drafts (
        draft_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        proposal_id uuid NOT NULL UNIQUE REFERENCES proposals,
        body jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    "COMMENT ON TABLE internal_drafts IS "
    "'Internal drafts only. No recipient column; nothing is ever sent.'",
    """
    CREATE TABLE audit_events (
        event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        actor text NOT NULL,
        kind text NOT NULL,
        object_id text NOT NULL,
        safe_payload jsonb NOT NULL DEFAULT '{}',
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    """
    CREATE TABLE usage_days (
        day date PRIMARY KEY,
        admitted_calls integer NOT NULL DEFAULT 0 CHECK (admitted_calls >= 0)
    )""",
    """
    CREATE TABLE eval_runs (
        eval_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        planned_calls integer NOT NULL,
        admitted_calls integer NOT NULL DEFAULT 0,
        ceiling integer NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CHECK (planned_calls <= ceiling),
        CHECK (admitted_calls <= ceiling)
    )""",
    """
    CREATE TABLE model_calls (
        call_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        job_id uuid NOT NULL REFERENCES jobs,
        stage text NOT NULL CHECK (stage IN ('planner','analyst')),
        state text NOT NULL CHECK (state IN
            ('reserved','sent','complete','known_failure','unknown')),
        model_id text NOT NULL,
        price_snapshot jsonb NOT NULL,
        request_hash text NOT NULL,
        usage jsonb NULL,
        admitted_day date NULL REFERENCES usage_days,
        eval_run_id uuid NULL REFERENCES eval_runs,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (job_id, stage),
        CHECK ((admitted_day IS NULL) <> (eval_run_id IS NULL))
    )""",
    # ---- required indexes ----------------------------------------------------
    "CREATE INDEX order_items_batch_seller_order ON order_items (batch_id, seller_id, order_id)",
    "CREATE INDEX order_items_batch_product ON order_items (batch_id, product_id)",
    "CREATE INDEX orders_batch_estimated_order ON orders (batch_id, estimated_at, order_id)",
    "CREATE INDEX orders_batch_customer ON orders (batch_id, customer_id)",
    "CREATE INDEX outbox_unsent ON outbox (created_at) WHERE sent_at IS NULL",
    "CREATE INDEX audit_events_object_created ON audit_events (object_id, created_at)",
]

TABLES_REVERSE = [
    "model_calls", "eval_runs", "usage_days", "audit_events", "internal_drafts", "cases",
    "proposals", "outbox", "jobs", "disruption_events", "carrier_assignments", "carriers",
    "synthetic_scenarios", "quarantine", "order_items", "orders", "products", "customers",
    "seller_grants", "sellers", "users", "source_batches",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in TABLES_REVERSE:
        op.execute(f"DROP TABLE IF EXISTS {table}")
