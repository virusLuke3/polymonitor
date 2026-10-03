"""Response values shared by HTTP handlers and background consumers."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from api.commodity_symbols import COMMODITY_SYMBOLS

try:
    from eth_utils import to_checksum_address
except ImportError:
    to_checksum_address = None
from db.trade_v2 import compat_maker_asset_id_sql, compat_taker_asset_id_sql, uint256_storage_to_text
from oracle.settlement_parser import parse_oracle_settlement_event

CRYPTO_SYMBOLS = [
    ("btc", "BTC", "BTC-USD"),
    ("eth", "ETH", "ETH-USD"),
    ("sol", "SOL", "SOL-USD"),
    ("doge", "DOGE", "DOGE-USD"),
    ("bnb", "BNB", "BNB-USD"),
    ("xrp", "XRP", "XRP-USD"),
    ("ada", "ADA", "ADA-USD"),
    ("avax", "AVAX", "AVAX-USD"),
    ("link", "LINK", "LINK-USD"),
    ("ltc", "LTC", "LTC-USD"),
    ("dot", "DOT", "DOT-USD"),
    ("trx", "TRX", "TRX-USD"),
    ("bch", "BCH", "BCH-USD"),
]
CRYPTO_COINGECKO_IDS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "DOGE-USD": "dogecoin",
    "BNB-USD": "binancecoin",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "AVAX-USD": "avalanche-2",
    "LINK-USD": "chainlink",
    "LTC-USD": "litecoin",
    "DOT-USD": "polkadot",
    "TRX-USD": "tron",
    "BCH-USD": "bitcoin-cash",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    text = value.strip()
    if not text:
        return None
    normalized = text.replace(" UTC", "Z").replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def iso_days_before(anchor: Optional[str], days: int) -> Optional[str]:
    parsed = parse_iso_datetime(anchor)
    if parsed is None:
        return None
    return (parsed - timedelta(days=days)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except Exception:
            return [item.strip() for item in text.split(",") if item.strip()]
    return [value]


def normalize_address(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def format_trade_decimal(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return ""
    try:
        normalized = format(Decimal(text), "f")
    except (InvalidOperation, ValueError, TypeError):
        return value
    if "." not in normalized:
        return normalized
    return normalized.rstrip("0").rstrip(".")


def format_trade_address(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) == 20:
            text = "0x" + raw.hex()
        else:
            return value
    else:
        text = str(value or "").strip()
    if not text.startswith("0x") or len(text) != 42:
        return value
    lowered = "0x" + text[2:].lower()
    if to_checksum_address is None:
        return lowered
    try:
        return to_checksum_address(lowered)
    except Exception:
        return lowered


def utc_date_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


def parse_interval_minutes(interval: str) -> int:
    text = str(interval or "5m").strip().lower()
    match = re.fullmatch("(\\d+)(m|h|d)", text)
    if not match:
        return 5
    value = max(1, int(match.group(1)))
    unit = match.group(2)
    if unit == "m":
        return value
    if unit == "h":
        return value * 60
    return value * 1440


def range_to_seconds(range_name: str) -> int:
    normalized = str(range_name or "1d").strip().lower()
    mapping = {"1h": 3600, "6h": 21600, "12h": 43200, "1d": 86400, "3d": 259200, "7d": 604800, "30d": 2592000}
    return mapping.get(normalized, 86400)


def _safe_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_percent_text(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return format_trade_decimal(value)


def build_market_status_case(now_iso: str) -> str:
    return "CASE WHEN EXISTS (SELECT 1 FROM market_status_snapshot mss WHERE mss.market_id = m.id AND COALESCE(mss.is_final, FALSE) = TRUE) THEN 'Settled' WHEN EXISTS (SELECT 1 FROM market_status_snapshot mss WHERE mss.market_id = m.id AND COALESCE(mss.completion_status, '') = 'DISPUTED') THEN 'Disputed' WHEN EXISTS (SELECT 1 FROM market_status_snapshot mss WHERE mss.market_id = m.id AND (COALESCE(mss.has_settle, FALSE) = TRUE OR mss.settlement_code IN (1, 2, 3))) THEN 'Settled' WHEN EXISTS (SELECT 1 FROM market_status_snapshot mss WHERE mss.market_id = m.id AND COALESCE(mss.has_propose, FALSE) = TRUE) THEN 'Proposed' WHEN EXISTS (SELECT 1 FROM market_status_snapshot mss WHERE mss.market_id = m.id AND COALESCE(mss.is_trading_closed, FALSE) = TRUE) THEN 'Closed' WHEN m.end_date IS NOT NULL AND m.end_date < ? THEN 'Closed' ELSE 'Active' END"


def normalize_market(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "localMarketId": row.get("id"),
        "slug": row.get("slug"),
        "title": row.get("title"),
        "conditionId": row.get("condition_id"),
        "questionId": row.get("question_id"),
        "oracle": row.get("oracle"),
        "yesTokenId": row.get("yes_token_id"),
        "noTokenId": row.get("no_token_id"),
        "description": row.get("description") or "",
        "status": row.get("status") or "Unknown",
        "latestPrice": row.get("latest_price"),
        "latestYesPrice": row.get("latest_yes_price"),
        "latestNoPrice": row.get("latest_no_price"),
        "enableNegRisk": bool(row.get("enable_neg_risk")),
        "endDate": row.get("end_date"),
        "createdAt": row.get("created_at"),
        "category": row.get("category") or "Uncategorized",
        "tags": parse_json_list(row.get("tags")),
        "gammaMarketId": row.get("gamma_market_id"),
        "superseded": bool(row.get("superseded")),
        "canonicalMarketId": row.get("canonicalMarketId") or row.get("canonical_market_id"),
        "settlementCode": row.get("settlement_code") or 0,
        "settlementOutcome": row.get("settlement_outcome") or "UNKNOWN",
        "settlementSource": row.get("settlement_source"),
        "settlementRaw": row.get("settlement_raw"),
        "settlementEventId": row.get("settlement_event_id"),
        "settlementEventTime": row.get("settlement_event_time"),
        "settlementTransaction": row.get("settlement_transaction"),
        "completionStatus": row.get("completion_status") or "OPEN",
        "completionSource": row.get("completion_source"),
        "completionTime": row.get("completion_time"),
        "isTradingClosed": bool(row.get("is_trading_closed")),
        "isResolved": bool(row.get("is_resolved")),
        "isFinal": bool(row.get("is_final")),
        "gammaClosed": bool(row.get("gamma_closed")),
        "gammaClosedTime": row.get("gamma_closed_time"),
    }


def normalize_trade(row: Dict[str, Any]) -> Dict[str, Any]:
    token_id_text = uint256_storage_to_text(row.get("token_id"))
    maker_asset_id = uint256_storage_to_text(row.get("maker_asset_id"))
    taker_asset_id = uint256_storage_to_text(row.get("taker_asset_id"))
    side_text = row.get("side")
    if maker_asset_id is None and token_id_text is not None:
        if side_text == "BUY":
            maker_asset_id = "0"
            taker_asset_id = token_id_text
        elif side_text == "SELL":
            maker_asset_id = token_id_text
            taker_asset_id = "0"
    return {
        "txHash": row.get("tx_hash").hex()
        if isinstance(row.get("tx_hash"), (bytes, bytearray, memoryview))
        else row.get("tx_hash"),
        "logIndex": row.get("log_index"),
        "blockNumber": row.get("block_number"),
        "timestamp": row.get("timestamp"),
        "maker": format_trade_address(row.get("maker")),
        "taker": format_trade_address(row.get("taker")),
        "price": format_trade_decimal(row.get("price")),
        "size": format_trade_decimal(row.get("size")),
        "side": row.get("side"),
        "outcome": row.get("outcome"),
        "tokenId": token_id_text,
        "marketId": row.get("market_id"),
        "localMarketId": row.get("market_id"),
        "marketTitle": row.get("market_title"),
        "orderHash": row.get("order_hash").hex()
        if isinstance(row.get("order_hash"), (bytes, bytearray, memoryview))
        else row.get("order_hash"),
        "makerAssetId": maker_asset_id,
        "takerAssetId": taker_asset_id,
        "makerAmount": row.get("maker_amount"),
        "takerAmount": row.get("taker_amount"),
        "fee": row.get("fee"),
        "contract": format_trade_address(row.get("contract")),
    }


def normalize_oracle_event(row: Dict[str, Any]) -> Dict[str, Any]:
    settlement = parse_oracle_settlement_event(row)
    snapshot_code = row.get("snapshot_settlement_code")
    snapshot_outcome = row.get("snapshot_settlement_outcome")
    snapshot_source = row.get("snapshot_settlement_source")
    if settlement.settlement_code == 0 and snapshot_code not in (None, "", 0, "0"):
        effective_code = snapshot_code
        effective_outcome = snapshot_outcome
        effective_source = snapshot_source
    else:
        effective_code = settlement.settlement_code
        effective_outcome = settlement.settlement_outcome
        effective_source = settlement.settlement_source
    return {
        "id": row.get("id"),
        "txHash": row.get("tx_hash"),
        "logIndex": row.get("log_index"),
        "blockNumber": row.get("block_number"),
        "eventTime": row.get("event_time"),
        "eventStatus": row.get("event_status"),
        "externalMarketId": row.get("external_market_id"),
        "marketId": row.get("market_id"),
        "localMarketId": row.get("market_id"),
        "gammaMarketId": row.get("external_market_id"),
        "marketTitle": row.get("market_title"),
        "marketSlug": row.get("market_slug"),
        "marketCategory": row.get("market_category"),
        "isBound": row.get("market_id") is not None,
        "matchedBy": row.get("matched_by"),
        "questionId": row.get("question_id"),
        "conditionId": row.get("condition_id"),
        "proposedPrice": row.get("proposed_price"),
        "settledPrice": row.get("settled_price"),
        "payout": row.get("payout"),
        "settlementCode": settlement.settlement_code,
        "settlementOutcome": settlement.settlement_outcome,
        "settlementSource": settlement.settlement_source,
        "settlementRaw": settlement.settlement_raw,
        "effectiveSettlementCode": effective_code,
        "effectiveSettlementOutcome": effective_outcome,
        "effectiveSettlementSource": effective_source,
        "completionStatus": row.get("completion_status") or "OPEN",
        "isTradingClosed": bool(row.get("is_trading_closed")),
        "isResolved": bool(row.get("is_resolved")),
        "isFinal": bool(row.get("is_final")),
        "requester": row.get("requester"),
        "proposer": row.get("proposer"),
        "disputer": row.get("disputer"),
        "proposalTransaction": row.get("proposal_transaction"),
        "settlementTransaction": row.get("settlement_transaction"),
        "sourceAdapter": row.get("source_adapter"),
        "sourceOracle": row.get("source_oracle"),
    }


def get_trade_market_projection_sql(alias: str) -> str:
    return f"\n        {alias}.tx_hash AS tx_hash,\n        {alias}.log_index AS log_index,\n        {alias}.market_id AS market_id,\n        {alias}.maker AS maker,\n        {alias}.taker AS taker,\n        {alias}.price AS price,\n        {alias}.size AS size,\n        CASE {alias}.side_code\n            WHEN 1 THEN 'BUY'\n            WHEN 2 THEN 'SELL'\n            ELSE 'UNKNOWN'\n        END AS side,\n        CASE {alias}.outcome_code\n            WHEN 1 THEN 'YES'\n            WHEN 2 THEN 'NO'\n            ELSE 'UNKNOWN'\n        END AS outcome,\n        {alias}.token_id AS token_id,\n        DATE_FORMAT({alias}.block_time, '%%Y-%%m-%%dT%%H:%%i:%%sZ') AS timestamp,\n        {alias}.block_number AS block_number,\n        {alias}.order_hash AS order_hash,\n        {compat_maker_asset_id_sql(alias)} AS maker_asset_id,\n        {compat_taker_asset_id_sql(alias)} AS taker_asset_id,\n        {alias}.maker_amount AS maker_amount,\n        {alias}.taker_amount AS taker_amount,\n        {alias}.fee AS fee,\n        {alias}.contract AS contract\n    "
