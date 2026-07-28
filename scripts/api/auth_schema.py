"""Idempotent PostgreSQL schema for product identity and access control."""

from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "2026-07-28-auth-v1"

DDL = """
CREATE SCHEMA IF NOT EXISTS product;

CREATE TABLE IF NOT EXISTS product.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS product.users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    force_password_change BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS users_username_normalized_uq
    ON product.users (LOWER(username));

CREATE TABLE IF NOT EXISTS product.sessions (
    id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES product.users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    csrf_hash CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    user_agent_hash CHAR(64),
    ip_hash CHAR(64)
);
CREATE INDEX IF NOT EXISTS sessions_user_active_idx
    ON product.sessions (user_id, expires_at) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS product.api_keys (
    id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES product.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL UNIQUE,
    key_hash CHAR(64) NOT NULL UNIQUE,
    scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 60 CHECK (rate_limit_per_minute BETWEEN 1 AND 600),
    daily_quota INTEGER NOT NULL DEFAULT 5000 CHECK (daily_quota BETWEEN 1 AND 1000000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS api_keys_user_active_idx
    ON product.api_keys (user_id, created_at DESC) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS product.api_key_usage (
    api_key_id UUID NOT NULL REFERENCES product.api_keys(id) ON DELETE CASCADE,
    window_kind TEXT NOT NULL CHECK (window_kind IN ('minute', 'day')),
    window_start TIMESTAMPTZ NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (api_key_id, window_kind, window_start)
);
CREATE INDEX IF NOT EXISTS api_key_usage_retention_idx
    ON product.api_key_usage (window_start);

CREATE TABLE IF NOT EXISTS product.auth_rate_limits (
    scope TEXT NOT NULL,
    subject_hash CHAR(64) NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (scope, subject_hash, window_start)
);
CREATE INDEX IF NOT EXISTS auth_rate_limits_retention_idx
    ON product.auth_rate_limits (window_start);

CREATE TABLE IF NOT EXISTS product.audit_log (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_user_id BIGINT REFERENCES product.users(id) ON DELETE SET NULL,
    actor_kind TEXT NOT NULL CHECK (actor_kind IN ('anonymous', 'session', 'api_key', 'system')),
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    result TEXT NOT NULL CHECK (result IN ('success', 'denied', 'error')),
    request_id TEXT,
    ip_hash CHAR(64),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_log_occurred_idx
    ON product.audit_log (occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_log_actor_idx
    ON product.audit_log (actor_user_id, occurred_at DESC);

INSERT INTO product.schema_migrations (version)
VALUES ('2026-07-28-auth-v1')
ON CONFLICT (version) DO NOTHING;
"""


def apply_schema(connection: Any) -> None:
    try:
        connection.execute(DDL)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def schema_is_ready(connection: Any) -> bool:
    row = connection.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM product.schema_migrations
            WHERE version = ?
        ) AS ready
        """,
        (SCHEMA_VERSION,),
    ).fetchone()
    return bool(row and row[0])
