-- CashPilot Postgres Schema
-- Run: psql -U cashpilot -d cashpilot -f db/schema.sql

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─────────────────────────────────────────────
-- USERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name       TEXT,
    phone           TEXT,
    kyc_status      TEXT NOT NULL DEFAULT 'pending' CHECK (kyc_status IN ('pending','verified','failed')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- PLAID
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS plaid_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plaid_item_id       TEXT UNIQUE NOT NULL,
    access_token_enc    BYTEA NOT NULL,
    institution_id      TEXT,
    institution_name    TEXT,
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','error','revoked')),
    error_code          TEXT,
    consent_expiry      TIMESTAMPTZ,
    last_synced_at      TIMESTAMPTZ,
    cursor              TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS accounts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),
    plaid_item_id       UUID NOT NULL REFERENCES plaid_items(id),
    plaid_account_id    TEXT UNIQUE NOT NULL,
    name                TEXT NOT NULL,
    official_name       TEXT,
    type                TEXT NOT NULL,
    subtype             TEXT,
    currency            TEXT NOT NULL DEFAULT 'USD',
    is_primary          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS account_balances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id),
    available       NUMERIC(15,2),
    current         NUMERIC(15,2) NOT NULL,
    limit_amount    NUMERIC(15,2),
    snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_balances_account_time ON account_balances(account_id, snapshot_at DESC);

-- ─────────────────────────────────────────────
-- TRANSACTIONS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES users(id),
    account_id              UUID NOT NULL REFERENCES accounts(id),
    plaid_transaction_id    TEXT UNIQUE NOT NULL,
    amount                  NUMERIC(15,2) NOT NULL,
    currency                TEXT NOT NULL DEFAULT 'USD',
    merchant_name           TEXT,
    raw_name                TEXT,
    category_primary        TEXT,
    category_detailed       TEXT,
    payment_channel         TEXT,
    pending                 BOOLEAN NOT NULL DEFAULT FALSE,
    authorized_at           TIMESTAMPTZ,
    posted_at               DATE NOT NULL,
    normalized_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata                JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_transactions_user_posted ON transactions(user_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_account     ON transactions(account_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_category    ON transactions(user_id, category_primary);

CREATE TABLE IF NOT EXISTS financial_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    event_type      TEXT NOT NULL,
    transaction_id  UUID REFERENCES transactions(id),
    account_id      UUID REFERENCES accounts(id),
    amount          NUMERIC(15,2),
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}',
    processed       BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_events_user_unprocessed ON financial_events(user_id, processed)
    WHERE processed = FALSE;

CREATE TABLE IF NOT EXISTS financial_state (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID UNIQUE NOT NULL REFERENCES users(id),
    total_liquid_balance    NUMERIC(15,2) NOT NULL DEFAULT 0,
    monthly_income_est      NUMERIC(15,2),
    monthly_expenses_est    NUMERIC(15,2),
    last_paycheck_amount    NUMERIC(15,2),
    last_paycheck_at        TIMESTAMPTZ,
    next_paycheck_est_at    TIMESTAMPTZ,
    pay_frequency           TEXT CHECK (pay_frequency IN ('weekly','biweekly','semimonthly','monthly')),
    emergency_fund_score    NUMERIC(4,2),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- INTENTS & APPROVALS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS intents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),
    triggering_event_id UUID REFERENCES financial_events(id),
    intent_type         TEXT NOT NULL CHECK (intent_type IN ('transfer_to_savings','pay_bill','invest','alert','suggestion')),
    status              TEXT NOT NULL DEFAULT 'pending_approval'
                            CHECK (status IN ('pending_approval','approved','rejected','expired','executed','failed','cancelled')),
    title               TEXT NOT NULL,
    explanation         TEXT NOT NULL,
    amount              NUMERIC(15,2),
    from_account_id     UUID REFERENCES accounts(id),
    to_account_id       UUID REFERENCES accounts(id),
    parameters          JSONB NOT NULL DEFAULT '{}',
    confidence_score    NUMERIC(4,3),
    generated_by        TEXT NOT NULL CHECK (generated_by IN ('rules_engine','llm','hybrid')),
    rule_ids_fired      JSONB,
    llm_model           TEXT,
    llm_prompt_hash     TEXT,
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_intents_user_pending ON intents(user_id, status)
    WHERE status = 'pending_approval';

CREATE TABLE IF NOT EXISTS approval_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_id       UUID NOT NULL REFERENCES intents(id),
    user_id         UUID NOT NULL REFERENCES users(id),
    action          TEXT NOT NULL CHECK (action IN ('approve','reject','modify')),
    reason          TEXT,
    device_info     JSONB NOT NULL DEFAULT '{}',
    actioned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_approval_intent ON approval_actions(intent_id);

-- ─────────────────────────────────────────────
-- EXECUTIONS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS executions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_id           UUID UNIQUE NOT NULL REFERENCES intents(id),
    idempotency_key     TEXT UNIQUE NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','submitted','settled','failed','reversed')),
    provider            TEXT NOT NULL,
    provider_txn_id     TEXT,
    amount              NUMERIC(15,2) NOT NULL,
    executed_at         TIMESTAMPTZ,
    settled_at          TIMESTAMPTZ,
    failure_reason      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- CHAT
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    title       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content         TEXT NOT NULL,
    intent_ids      JSONB,
    token_count     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at);

-- ─────────────────────────────────────────────
-- AUDIT LOG (append-only — never UPDATE or DELETE)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id),
    actor_type      TEXT NOT NULL,
    actor_id        TEXT,
    event_type      TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       UUID,
    before_state    JSONB,
    after_state     JSONB,
    metadata        JSONB NOT NULL DEFAULT '{}',
    ip_hash         TEXT,
    request_id      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity    ON audit_log(entity_type, entity_id);

-- App role: no UPDATE/DELETE on audit_log
-- Run as superuser after creating the app role:
-- REVOKE UPDATE, DELETE ON audit_log FROM cashpilot_app;
