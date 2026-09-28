"""Shared, fail-closed identity policy for market serving paths.

The canonical ``core.markets`` registry intentionally contains provenance
shells as well as user-facing Gamma markets.  Consumers must therefore opt in
to the same binary identity contract instead of independently guessing from a
title or category.

The SQL emitted here assumes the immutable alias table and the source
semantics ledger have been installed.  Production deploys create the alias
table before enabling this policy; a missing governance table is deliberately
an error rather than an implicit allow-all fallback.
"""

from __future__ import annotations

import re


POLICY_VERSION = "market-binary-serving-identity-v2"
ALIAS_TABLE = "ops.market_identity_aliases_active_v1"
SOURCE_SEMANTICS_TABLE = "ops.market_source_semantics_reconciliation"
PLACEHOLDER_CATEGORY = "orderfilled-placeholder"
PLACEHOLDER_SLUG_PREFIX = "trade-indexer-placeholder-"
INVALID_IDENTITY_CATEGORY = "invalid-identity-shell"
PROTOCOL_STRUCTURAL_IDENTITY_KIND = "protocol_structural"
CANONICAL_GAMMA_IDENTITY_KIND = "canonical_gamma"
SYNTHETIC_CTF_V2_SLUG_PREFIX = "onchain-condition-v2-"
PROTOCOL_STRUCTURAL_SLUG_PREFIX = "protocol-structural-"
ZERO_CONDITION_ID = "0x" + ("0" * 64)

_SQL_ALIAS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _alias(value: str) -> str:
    text = str(value or "").strip()
    if not _SQL_ALIAS.fullmatch(text):
        raise ValueError(f"unsafe SQL alias: {value!r}")
    return text


def explicit_protocol_combo_sql(market_alias: str = "m") -> str:
    """Return the narrow marker contract for Data API combo shells.

    The missing Gamma/question checks are part of the predicate so an official
    Gamma market tagged as a combo is never reclassified as a protocol shell.
    """

    m = _alias(market_alias)
    return f"""(
        COALESCE(TRIM({m}.gamma_market_id), '') = ''
        AND COALESCE(TRIM({m}.question_id), '') = ''
        AND (
            LOWER(COALESCE(CAST({m}.tags AS TEXT), '')) LIKE '%%data-api-combo%%'
            OR (
                LOWER(COALESCE({m}.slug, '')) LIKE 'combo-%%'
                AND LOWER(COALESCE(CAST({m}.tags AS TEXT), '')) LIKE '%%combo%%'
            )
        )
    )"""


def explicit_protocol_ghost_sql(market_alias: str = "m") -> str:
    """Return the narrow marker contract for legacy ghost/orphan shells."""

    m = _alias(market_alias)
    return f"""(
        COALESCE(TRIM({m}.gamma_market_id), '') = ''
        AND COALESCE(TRIM({m}.question_id), '') = ''
        AND (
            LOWER(TRIM(COALESCE({m}.category, ''))) IN ('ghost', '[ghost]')
            OR LOWER(COALESCE({m}.slug, '')) LIKE 'ghost-market-%%'
            OR (
                LOWER(COALESCE(CAST({m}.tags AS TEXT), '')) LIKE '%%orphaned%%'
                AND LOWER(COALESCE(CAST({m}.tags AS TEXT), '')) LIKE '%%unknown%%'
            )
        )
    )"""


def explicit_invalid_registry_shell_sql(market_alias: str = "m") -> str:
    """Return the narrow marker for a historical zero-condition shell.

    An old registry lookup accepted ``bytes32(0)`` from ``getConditionId`` and
    repeatedly upserted unrelated token pairs into the same unique condition.
    The row remains as provenance, but must never be retried as a Gamma market
    or treated as a token owner.
    """

    m = _alias(market_alias)
    return f"""(
        COALESCE(TRIM({m}.gamma_market_id), '') = ''
        AND COALESCE(TRIM({m}.question_id), '') = ''
        AND LOWER(TRIM(COALESCE({m}.condition_id, ''))) = '{ZERO_CONDITION_ID}'
        AND (
            LOWER(TRIM(COALESCE({m}.category, ''))) = '{INVALID_IDENTITY_CATEGORY}'
            OR (
                LOWER(COALESCE({m}.slug, '')) LIKE 'onchain-%%'
                AND LOWER(COALESCE(CAST({m}.tags AS TEXT), ''))
                    LIKE '%%onchain-registry%%'
            )
        )
    )"""


def explicit_protocol_ctf_v2_sql(market_alias: str = "m") -> str:
    """Return the exact marker for unlabeled CTF Exchange V2 shells."""

    m = _alias(market_alias)
    return f"""(
        COALESCE(TRIM({m}.gamma_market_id), '') = ''
        AND COALESCE(TRIM({m}.question_id), '') = ''
        AND LOWER(TRIM(COALESCE({m}.slug, '')))
            LIKE '{SYNTHETIC_CTF_V2_SLUG_PREFIX}%%'
    )"""


def canonical_reconciliation_exclusion_sql(market_alias: str = "m") -> str:
    """Rows that must never be sent to Gamma canonical reconciliation."""

    m = _alias(market_alias)
    return f"""(
        LOWER(TRIM(COALESCE({m}.category, ''))) = '{PLACEHOLDER_CATEGORY}'
        OR LOWER(TRIM(COALESCE({m}.slug, ''))) LIKE '{PLACEHOLDER_SLUG_PREFIX}%%'
        OR {explicit_protocol_combo_sql(m)}
        OR {explicit_protocol_ghost_sql(m)}
        OR {explicit_protocol_ctf_v2_sql(m)}
        OR (
            COALESCE(TRIM({m}.gamma_market_id), '') = ''
            AND COALESCE(TRIM({m}.question_id), '') = ''
            AND LOWER(TRIM(COALESCE({m}.slug, '')))
                LIKE '{PROTOCOL_STRUCTURAL_SLUG_PREFIX}%%'
        )
        OR {explicit_invalid_registry_shell_sql(m)}
    )"""


def binary_serving_identity_sql(
    market_alias: str = "m",
    *,
    qualified_ops: bool = False,
) -> str:
    """Return the canonical binary-market serving predicate.

    Besides intrinsic identity fields, the policy excludes immutable alias
    sources and every terminal source-semantics residual.  Unknown protocol
    shells remain visible in governance/audit ledgers, but they cannot enter a
    binary serving read model merely because they happen to carry two strings
    that look like token ids.
    """

    m = _alias(market_alias)
    alias_table = ALIAS_TABLE if qualified_ops else ALIAS_TABLE.split(".", 1)[1]
    semantics_table = (
        SOURCE_SEMANTICS_TABLE
        if qualified_ops
        else SOURCE_SEMANTICS_TABLE.split(".", 1)[1]
    )
    return f"""(
        COALESCE(TRIM({m}.gamma_market_id), '') <> ''
        AND COALESCE(TRIM({m}.question_id), '') <> ''
        AND COALESCE(TRIM({m}.condition_id), '') <> ''
        AND COALESCE(TRIM({m}.yes_token_id), '') <> ''
        AND COALESCE(TRIM({m}.no_token_id), '') <> ''
        AND TRIM({m}.yes_token_id) <> TRIM({m}.no_token_id)
        AND LOWER(TRIM(COALESCE({m}.category, ''))) <> '{PLACEHOLDER_CATEGORY}'
        AND LOWER(TRIM(COALESCE({m}.slug, ''))) NOT LIKE '{PLACEHOLDER_SLUG_PREFIX}%%'
        AND NOT {explicit_protocol_combo_sql(m)}
        AND NOT {explicit_protocol_ghost_sql(m)}
        AND NOT {explicit_protocol_ctf_v2_sql(m)}
        AND NOT {explicit_invalid_registry_shell_sql(m)}
        AND NOT EXISTS (
            SELECT 1
            FROM {alias_table} identity_alias
            WHERE identity_alias.source_market_id = {m}.id
        )
        AND NOT EXISTS (
            SELECT 1
            FROM {semantics_table} semantics_residual
            WHERE semantics_residual.market_id = {m}.id
              AND TRIM(semantics_residual.source_gamma_market_id)
                  = TRIM({m}.gamma_market_id)
              AND LOWER(TRIM(semantics_residual.source_condition_id))
                  = LOWER(TRIM({m}.condition_id))
              AND semantics_residual.classification IN (
                  'source_clob_absent',
                  'source_identity_mismatch',
                  'source_not_found',
                  'ownership_conflict',
                  'superseded_duplicate'
              )
        )
    )"""


def classify_explicit_protocol_shell(
    *,
    gamma_market_id: object,
    question_id: object,
    slug: object,
    category: object,
    tags: object,
    condition_id: object = None,
    identity_kind: object = None,
) -> str | None:
    """Python mirror used before any Gamma request is attempted."""

    gamma = str(gamma_market_id or "").strip()
    question = str(question_id or "").strip()
    kind = str(identity_kind or "").strip().lower()
    if kind == PROTOCOL_STRUCTURAL_IDENTITY_KIND:
        return "protocol_structural_anchor"
    if gamma or question:
        return None
    slug_text = str(slug or "").strip().lower()
    category_text = str(category or "").strip().lower()
    tags_text = str(tags or "").strip().lower()
    condition_text = str(condition_id or "").strip().lower()
    if slug_text.startswith(PROTOCOL_STRUCTURAL_SLUG_PREFIX):
        return "protocol_structural_anchor"
    invalid_registry = condition_text == ZERO_CONDITION_ID and (
        category_text == INVALID_IDENTITY_CATEGORY
        or (slug_text.startswith("onchain-") and "onchain-registry" in tags_text)
    )
    if invalid_registry:
        return "protocol_invalid_registry_shell"
    combo = (
        "data-api-combo" in tags_text
        or (slug_text.startswith("combo-") and "combo" in tags_text)
    )
    if combo:
        return "protocol_combo_shell"
    if slug_text.startswith(SYNTHETIC_CTF_V2_SLUG_PREFIX):
        return "protocol_ctf_v2_shell"
    ghost = (
        category_text in {"ghost", "[ghost]"}
        or slug_text.startswith("ghost-market-")
        or ("orphaned" in tags_text and "unknown" in tags_text)
    )
    return "protocol_ghost_shell" if ghost else None
