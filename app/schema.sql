-- Recovery Agent schema
-- Loaded automatically by docker-compose (postgres init scripts) on first container creation.
-- If you change this after the db volume already exists, you must re-run manually:
--   docker exec -i recovery_agent_db psql -U recovery -d recovery_agent < app/schema.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS failure_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    failure_type TEXT NOT NULL CHECK (
        failure_type IN ('card_declined', 'expired_card', 'insufficient_funds', 'gateway_timeout')
    ),
    amount NUMERIC(12, 2) NOT NULL,
    attempt_number INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open' CHECK (
        status IN ('open', 'recovering', 'recovered', 'escalated', 'blocked')
    ),
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    failure_event_id UUID NOT NULL REFERENCES failure_events(id),
    node TEXT NOT NULL CHECK (
        node IN ('detector', 'diagnosis', 'strategy_agent', 'policy', 'safety', 'executor', 'promise_tracker', 'baseline')
    ),
    output JSONB,
    confidence NUMERIC(4, 3),
    decision TEXT CHECK (decision IN ('ALLOWED', 'BLOCKED', 'ESCALATED')),
    reasoning TEXT,
    idempotency_key TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_actions_event ON agent_actions(failure_event_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_idempotency ON agent_actions(idempotency_key);

CREATE TABLE IF NOT EXISTS commitments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    failure_event_id UUID NOT NULL REFERENCES failure_events(id),
    promised_date DATE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'kept', 'broken')),
    extracted_from_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recovery_outcomes (
    failure_event_id UUID NOT NULL REFERENCES failure_events(id),
    recovered_amount NUMERIC(12, 2),
    recovery_status TEXT NOT NULL CHECK (
        recovery_status IN ('recovered', 'failed', 'escalated', 'blocked')
    ),
    strategy TEXT,
    attempt_count INT NOT NULL DEFAULT 0,
    completed_at TIMESTAMP,
    PRIMARY KEY (failure_event_id, strategy)
);
