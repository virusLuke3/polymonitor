from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover - watcher validates dependency.
    requests = None

from api.services.finance_watch.common import (
    FINANCE_WATCH_CACHE_KEY,
    FinanceWatchContext,
    _dependencies,
    _fetch_yahoo_snapshot,
    _format_pct,
    _format_price,
    _http_json_get,
    _http_text_get,
    _payload,
    _safe_float,
    _setting,
    _tone,
    finance_watch_namespace,
)

FNG_WEIGHTS = {
    "sentiment": 0.10,
    "volatility": 0.10,
    "positioning": 0.15,
    "trend": 0.10,
    "breadth": 0.10,
    "momentum": 0.10,
    "liquidity": 0.15,
    "credit": 0.10,
    "macro": 0.05,
    "crossAsset": 0.05,
}


def _fetch_yahoo_closes(
    ctx: FinanceWatchContext,
    symbol: str,
    *,
    range_name: str = "1y",
) -> Dict[str, Any]:
    snapshot = _fetch_yahoo_snapshot(ctx, symbol, interval="1d", range_name=range_name)
    points = [point for point in (snapshot or {}).get("points", []) if isinstance(point, dict)]
    closes = [_safe_float(point.get("value")) for point in points]
    return {**(snapshot or {}), "closes": [value for value in closes if value is not None]}


def _fetch_fred_observations(
    ctx: FinanceWatchContext,
    series_id: str,
) -> List[Dict[str, Any]]:
    try:
        text = _http_text_get(ctx, _setting(ctx, "finance_fred_csv_url_template").format(series_id=series_id), timeout=10)
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in text.splitlines()[1:]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2 or parts[1] in {"", "."}:
            continue
        value = _safe_float(parts[1])
        if value is not None:
            rows.append({"date": parts[0], "value": value})
    return rows


def _fred_latest(rows: List[Dict[str, Any]]) -> Optional[float]:
    return _safe_float(rows[-1].get("value")) if rows else None


def _fred_back(rows: List[Dict[str, Any]], periods: int) -> Optional[float]:
    if not rows:
        return None
    index = max(0, len(rows) - 1 - periods)
    return _safe_float(rows[index].get("value"))


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _roc(values: List[float], period: int) -> Optional[float]:
    if len(values) < period + 1:
        return None
    previous = values[-period - 1]
    current = values[-1]
    return ((current - previous) / previous) * 100 if previous else None


def _sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / len(window)


def _rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for idx in range(len(values) - period, len(values)):
        delta = values[idx] - values[idx - 1]
        if delta > 0:
            gains += delta
        else:
            losses += abs(delta)
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - (100 / (1 + rs))


def _score_label(score: Any) -> str:
    value = _safe_float(score)
    if value is None:
        return "Neutral"
    if value <= 20:
        return "Extreme Fear"
    if value <= 40:
        return "Fear"
    if value <= 60:
        return "Neutral"
    if value <= 80:
        return "Greed"
    return "Extreme Greed"


def _score_tone(score: Any) -> str:
    value = _safe_float(score)
    if value is None:
        return "neutral"
    if value >= 60:
        return "up"
    if value <= 40:
        return "down"
    return "watch"


def _fetch_barchart_last_price(
    ctx: FinanceWatchContext,
    symbol: str,
) -> Optional[float]:
    try:
        html = _http_text_get(ctx, _setting(ctx, "finance_barchart_quote_url_template").format(symbol=symbol), timeout=10)
    except Exception:
        return None
    block_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html)
    block = block_match.group(1) if block_match else html
    match = re.search(r'"lastPrice"\s*:\s*"?([\d.]+)"?', block)
    return _safe_float(match.group(1)) if match else None


def _fetch_cnn_fng(
    ctx: FinanceWatchContext,
) -> Optional[Dict[str, Any]]:
    if requests is None:
        return None
    session = requests.Session()
    session.trust_env = True
    try:
        response = session.get(
            _setting(ctx, "finance_cnn_fng_url"),
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Referer": _setting(ctx, "finance_cnn_fng_referer_url"),
            },
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None
    finally:
        session.close()
    score = _safe_float(data.get("score") or (data.get("fear_and_greed") or {}).get("score"))
    label = data.get("rating") or (data.get("fear_and_greed") or {}).get("rating")
    return {"score": round(score), "label": str(label or _score_label(score))} if score is not None else None


def _fetch_aaii_sentiment(
    ctx: FinanceWatchContext,
) -> Optional[Dict[str, float]]:
    try:
        html = _http_text_get(ctx, _setting(ctx, "finance_aaii_sentiment_url"), timeout=10)
    except Exception:
        return None
    values = [_safe_float(match.group(1)) for match in re.finditer(r'<td[^>]*class="tableTxt"[^>]*>([\d.]+)%', html)]
    values = [value for value in values if value is not None]
    if len(values) < 3:
        return None
    return {"bull": float(values[0]), "bear": float(values[2])}


def build_fear_greed_payload(
    ctx: FinanceWatchContext,
    limit: int,
) -> Dict[str, Any]:
    raw = _http_json_get(ctx, _setting(ctx, "finance_alternative_fng_url"), params={"limit": 2, "format": "json"}, timeout=12)
    data = (raw.get("data") or []) if isinstance(raw, dict) else []
    item = data[0] if data and isinstance(data[0], dict) else {}
    previous = data[1] if len(data) > 1 and isinstance(data[1], dict) else {}
    crypto_score = _safe_float(item.get("value"))
    crypto_prev_score = _safe_float(previous.get("value"))
    cnn = _fetch_cnn_fng(ctx)
    aaii = _fetch_aaii_sentiment(ctx)
    put_call = _fetch_barchart_last_price(ctx, "%24CPC")
    pct_above_200d = _fetch_barchart_last_price(ctx, "%24S5TH")
    yahoo = {symbol: _fetch_yahoo_closes(ctx, symbol, range_name="1y") for symbol in ("^GSPC", "^VIX", "^VIX3M", "^SKEW", "GLD", "TLT", "HYG", "SPY", "RSP", "DX-Y.NYB")}
    fred = {series: _fetch_fred_observations(ctx, series) for series in ("BAMLH0A0HYM2", "BAMLC0A0CM", "DGS10", "FEDFUNDS", "T10Y2Y", "UNRATE", "M2SL", "WALCL", "SOFR")}
    vix = _safe_float(yahoo.get("^VIX", {}).get("price")) or _fred_latest(_fetch_fred_observations(ctx, "VIXCLS"))
    vix3m = _safe_float(yahoo.get("^VIX3M", {}).get("price"))
    skew = _safe_float(yahoo.get("^SKEW", {}).get("price"))
    spx_closes = [float(value) for value in yahoo.get("^GSPC", {}).get("closes", [])]
    spy_closes = [float(value) for value in yahoo.get("SPY", {}).get("closes", [])]
    rsp_closes = [float(value) for value in yahoo.get("RSP", {}).get("closes", [])]
    hyg_closes = [float(value) for value in yahoo.get("HYG", {}).get("closes", [])]
    tlt_closes = [float(value) for value in yahoo.get("TLT", {}).get("closes", [])]
    gld_closes = [float(value) for value in yahoo.get("GLD", {}).get("closes", [])]
    dxy_closes = [float(value) for value in yahoo.get("DX-Y.NYB", {}).get("closes", [])]

    def category(name: str, score_value: float, weight: float, degraded: bool = False) -> Dict[str, Any]:
        rounded = round(_clamp(score_value))
        return {
            "id": name,
            "label": _category_label(name),
            "score": rounded,
            "weight": weight,
            "contribution": round(rounded * weight, 1),
            "tone": _score_tone(rounded),
            "degraded": degraded,
        }

    sentiment_score = cnn.get("score") if cnn else crypto_score if crypto_score is not None else 50
    if aaii and cnn:
        bull_score = _clamp((aaii["bull"] / 60.0) * 100)
        bear_score = 100 - _clamp((aaii["bear"] / 55.0) * 100)
        sentiment_score = float(cnn["score"]) * 0.4 + bull_score * 0.3 + bear_score * 0.3
    vix_score = 50 if vix is None else _clamp(100 - ((float(vix) - 12) / 23) * 100)
    term_score = 50 if not vix or not vix3m else (70 if float(vix) / float(vix3m) < 1 else 30)
    positioning_score = 50
    if put_call is not None or skew is not None:
        pc_score = _clamp(100 - (((put_call or 0.9) - 0.7) / 0.6) * 100)
        skew_score = _clamp(100 - (((skew or 125) - 100) / 50) * 100)
        positioning_score = pc_score * 0.6 + skew_score * 0.4
    trend_score = 50
    if spx_closes:
        price = spx_closes[-1]
        above = sum(1 for avg in (_sma(spx_closes, 20), _sma(spx_closes, 50), _sma(spx_closes, 200)) if avg is not None and price > avg)
        dist_200 = ((price - _sma(spx_closes, 200)) / _sma(spx_closes, 200)) if _sma(spx_closes, 200) else 0
        trend_score = (above / 3) * 50 + _clamp(dist_200 * 500 + 50) * 0.5
    rsp_spy = ((_roc(rsp_closes, 30) or 0) - (_roc(spy_closes, 30) or 0)) if rsp_closes and spy_closes else None
    breadth_score = pct_above_200d if pct_above_200d is not None else _clamp((rsp_spy or 0) * 10 + 50)
    momentum_score = _clamp((_roc(spx_closes, 20) or 0) * 10 + 50) * 0.5 + _clamp(((_rsi(spx_closes) or 50) - 30) / 40 * 100) * 0.5
    m2_latest, m2_back = _fred_latest(fred["M2SL"]), _fred_back(fred["M2SL"], 52)
    walcl_latest, walcl_back = _fred_latest(fred["WALCL"]), _fred_back(fred["WALCL"], 4)
    m2_yoy = ((m2_latest - m2_back) / m2_back * 100) if m2_latest and m2_back else None
    fed_bs_mom = ((walcl_latest - walcl_back) / walcl_back * 100) if walcl_latest and walcl_back else None
    sofr = _fred_latest(fred["SOFR"])
    liquidity_score = (_clamp((m2_yoy or 0) * 5 + 50) * 0.4) + (_clamp((fed_bs_mom or 0) * 20 + 50) * 0.3) + (_clamp(100 - (sofr or 4.0) * 15) * 0.3)
    hy_spread = _fred_latest(fred["BAMLH0A0HYM2"])
    ig_spread = _fred_latest(fred["BAMLC0A0CM"])
    hy_score = 50 if hy_spread is None else _clamp(100 - ((hy_spread - 2.0) / 8.0) * 100)
    ig_score = 50 if ig_spread is None else _clamp(100 - ((ig_spread - 0.4) / 2.6) * 100)
    credit_score = hy_score * 0.55 + ig_score * 0.45
    fed_rate = _fred_latest(fred["FEDFUNDS"])
    curve = _fred_latest(fred["T10Y2Y"])
    unrate = _fred_latest(fred["UNRATE"])
    macro_score = (_clamp(100 - (fed_rate or 4.0) * 15) * 0.3) + ((60 + (curve or 0) * 20 if (curve or 0) > 0 else 40 + (curve or 0) * 40) * 0.4) + (_clamp(100 - ((unrate or 4.0) - 3.5) * 20) * 0.3)
    gold_signal = 30 if (_roc(gld_closes, 30) or 0) > (_roc(spy_closes, 30) or 0) else 70
    bond_signal = 30 if (_roc(tlt_closes, 30) or 0) > (_roc(spy_closes, 30) or 0) else 70
    dxy_signal = 40 if (_roc(dxy_closes, 30) or 0) > 0 else 60
    cross_asset_score = (gold_signal + bond_signal + dxy_signal) / 3
    category_rows = [
        category("sentiment", float(sentiment_score), FNG_WEIGHTS["sentiment"], degraded=not bool(aaii)),
        category("volatility", vix_score * 0.7 + term_score * 0.3, FNG_WEIGHTS["volatility"], degraded=vix is None),
        category("positioning", positioning_score, FNG_WEIGHTS["positioning"], degraded=put_call is None),
        category("trend", trend_score, FNG_WEIGHTS["trend"], degraded=not bool(spx_closes)),
        category("breadth", float(breadth_score), FNG_WEIGHTS["breadth"], degraded=pct_above_200d is None),
        category("momentum", momentum_score, FNG_WEIGHTS["momentum"], degraded=not bool(spx_closes)),
        category("liquidity", liquidity_score, FNG_WEIGHTS["liquidity"], degraded=m2_yoy is None),
        category("credit", credit_score, FNG_WEIGHTS["credit"], degraded=hy_spread is None),
        category("macro", _clamp(macro_score), FNG_WEIGHTS["macro"], degraded=fed_rate is None),
        category("crossAsset", cross_asset_score, FNG_WEIGHTS["crossAsset"], degraded=not bool(spy_closes)),
    ]
    score = round(sum(float(row["score"]) * float(row["weight"]) for row in category_rows), 1)
    if not any(not row.get("degraded") for row in category_rows):
        score = crypto_score
    previous_score = None
    dependencies = _dependencies(ctx)
    if dependencies.snapshot_store is not None:
        prior = dependencies.snapshot_store.get_stale(
            finance_watch_namespace("crypto-fear-greed"),
            FINANCE_WATCH_CACHE_KEY,
        )
        if isinstance(prior, dict) and (prior.get("summary") or {}).get("categories"):
            previous_score = _safe_float((prior.get("headline") or {}).get("score"))
    delta = score - previous_score if score is not None and previous_score is not None else None
    label = _score_label(score).upper()
    regime = _fear_greed_regime(score)
    drivers = []
    crypto_drivers = (
        ("BTC", "BTC-USD", "MOMENTUM", False),
        ("ETH", "ETH-USD", "MOMENTUM", False),
        ("SOL", "SOL-USD", "MOMENTUM", False),
        ("BNB", "BNB-USD", "MOMENTUM", False),
    )
    macro_drivers = (
        ("SPX", "^GSPC", "TREND", False),
        ("VIX", "^VIX", "VOL", True),
        ("HYG", "HYG", "CREDIT", False),
        ("TLT", "TLT", "RATES", True),
        ("GLD", "GLD", "HAVEN", True),
        ("DXY", "DX-Y.NYB", "USD", True),
        ("RSP", "RSP", "BREADTH", False),
        ("SPY", "SPY", "EQUITY", False),
    )
    for label_name, symbol, tag, inverted in crypto_drivers + macro_drivers:
        quote = yahoo.get(symbol) if symbol in yahoo else _fetch_yahoo_snapshot(ctx, symbol, interval="5m", range_name="1d")
        if isinstance(quote, dict):
            change = _safe_float(quote.get("changePercent"))
            tone_value = _tone((-change if inverted and change is not None else change))
            drivers.append(
                {
                    "id": symbol,
                    "label": label_name,
                    "symbol": tag,
                    "metricLabel": _format_price(quote.get("price")),
                    "change": change,
                    "changeLabel": _format_pct(change),
                    "tags": [tag],
                    "tone": tone_value,
                }
            )
    header_metrics = [
        {"label": "VIX", "value": _format_plain(vix, digits=2), "tone": "down" if vix and vix >= 25 else "up" if vix and vix <= 16 else "watch"},
        {"label": "HY Spread", "value": f"{hy_spread:.2f}%" if hy_spread is not None else "--", "tone": "down" if hy_spread and hy_spread >= 5 else "up"},
        {"label": "10Y Yield", "value": f"{_fred_latest(fred['DGS10']):.2f}%" if _fred_latest(fred["DGS10"]) is not None else "--", "tone": "neutral"},
        {"label": "P/C Ratio", "value": _format_plain(put_call, digits=2), "tone": "down" if put_call and put_call >= 1 else "up" if put_call else "neutral"},
        {"label": "% > 200d", "value": f"{pct_above_200d:.1f}%" if pct_above_200d is not None else "--", "tone": "up" if pct_above_200d and pct_above_200d >= 50 else "down"},
        {"label": "CNN F&G", "value": str(cnn.get("score")) if cnn else "--", "tone": _score_tone(cnn.get("score") if cnn else None)},
        {"label": "AAII Bull", "value": f"{aaii['bull']:.1f}%" if aaii else "--", "tone": "up" if aaii and aaii["bull"] >= 35 else "down" if aaii else "neutral"},
        {"label": "AAII Bear", "value": f"{aaii['bear']:.1f}%" if aaii else "--", "tone": "down" if aaii and aaii["bear"] >= 35 else "up" if aaii else "neutral"},
        {"label": "Fed Rate", "value": f"{fed_rate:.2f}%" if fed_rate is not None else "--", "tone": "neutral"},
    ]
    payload = _payload(
        "crypto-fear-greed",
        title="FEAR & GREED",
        items=drivers[:limit],
        summary={"score": score, "classification": label, "headerMetrics": header_metrics, "categories": category_rows, "cryptoScore": crypto_score, "cryptoPreviousScore": crypto_prev_score},
        sources={"alternativeMe": "ok" if crypto_score is not None else "empty", "cnn": "ok" if cnn else "empty", "aaii": "ok" if aaii else "empty", "fred": "ok" if hy_spread is not None else "empty"},
        status="ok" if score is not None else "empty",
    )
    payload["headline"] = {"label": label, "score": score, "previousScore": previous_score, "delta": delta, "regime": regime, "tone": "up" if score and score >= 55 else ("down" if score and score <= 45 else "neutral")}
    return payload


def _format_plain(value: Any, digits: int = 2) -> str:
    number = _safe_float(value)
    if number is None:
        return "--"
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _fear_greed_regime(score: Any) -> str:
    value = _safe_float(score)
    if value is None:
        return "NEUTRAL"
    if value <= 20:
        return "CRISIS / RISK-OFF"
    if value <= 35:
        return "STRESSED / DEFENSIVE"
    if value <= 50:
        return "FRAGILE / HEDGED"
    if value <= 65:
        return "STABLE / NORMAL"
    return "STRONG / RISK-ON"


def _category_label(value: str) -> str:
    labels = {
        "sentiment": "Sentiment",
        "volatility": "Volatility",
        "positioning": "Positioning",
        "trend": "Trend",
        "breadth": "Breadth",
        "momentum": "Momentum",
        "liquidity": "Liquidity",
        "credit": "Credit",
        "macro": "Macro",
        "crossAsset": "Cross-Asset",
    }
    return labels.get(value, value)
