"""Telegram messages for chain fills and source-backed radar stories."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
from math import isfinite
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from .models import MessageCandidate, source_clock

FLOW_PANEL = 'suspicious-flow'
RADAR_PANEL = 'breaking-event-radar'
EVIDENCE_PANELS = (FLOW_PANEL, RADAR_PANEL)
_BEIJING = timezone(timedelta(hours=8))
_PRIVATE_QUERY = re.compile(r'token|secret|password|auth|api[_-]?key|session|signature|cookie|email|phone', re.I)


def _time(stamp):
    return datetime.fromtimestamp(stamp, _BEIJING).strftime('%m-%d %H:%M:%S')


def _number(value):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if isfinite(number) else None


def _news_link(value):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        return ''
    try:
        parts = urlsplit(value)
        if (parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username is not None
                or any(_PRIVATE_QUERY.search(key) for key, _ in parse_qsl(parts.query))):
            return ''
    except ValueError:
        return ''
    return value


def _story_identity(url):
    parts = urlsplit(url)
    # Google News uses the path as the article identity. Other publishers can
    # identify the article in query parameters, such as an opaque article ID.
    query = '' if parts.hostname == 'news.google.com' else parts.query
    canonical = urlunsplit(('', parts.netloc.lower(), parts.path.rstrip('/'), query, ''))
    return sha256(canonical.encode()).hexdigest()[:24]


def _flow(row, *, topic, clean):
    title = clean(row.get('marketTitle'), limit=220)
    stamp = source_clock(row, 'timestamp')
    side = {'BUY': '买入', 'SELL': '卖出'}.get(str(row.get('side', '')).upper())
    notional, price, size = (_number(row.get(k)) for k in ('notional', 'price', 'size'))
    if not title or not stamp or not side or not row.get('id') or notional is None or notional <= 0:
        return None
    outcome = clean(row.get('sourceOutcomeLabel') or row.get('outcome'), limit=110) if row.get('outcomeSemanticsValid') is True else ''
    flow = f"{side} {outcome or '未核验结果'}"
    if size is not None and size > 0:
        flow += f' · {size:,.2f} 份'
    if price is not None and 0 <= price <= 1:
        flow += f' · {price * 100:.2f}¢/份'
    linked = row.get('observationType') == 'oracle-linked'
    lines = [f"🐳 Flow Watch · {'Oracle 事件前成交' if linked else '链上大额成交'}", title, flow, f'成交额 ${notional:,.2f}']
    if linked:
        oracle_at = source_clock(row, 'eventTime')
        if oracle_at and stamp <= oracle_at:
            lines.append(f'同盘口 Oracle 事件 · 北京时间 {_time(oracle_at)}')
    else:
        threshold = _number(row.get({'critical': 'criticalThresholdNotional', 'elevated': 'elevatedThresholdNotional'}.get(row.get('severity'), 'thresholdNotional')))
        share = _number(row.get('marketShare'))
        total = _number(row.get('marketWindowNotional'))
        facts = []
        if threshold and notional >= threshold:
            facts.append(f'大额门槛 ${threshold:,.0f}')
        if share is not None and 0 < share <= 1 and total and total >= notional:
            facts.append(f'占盘口统计窗口成交额 {share:.1%}（共 ${total:,.2f}）')
        if facts:
            lines.append(' · '.join(facts))
    lines.append(f'Polygon OrderFilled · 北京时间 {_time(stamp)}')
    tx = str(row.get('txHash') or '').removeprefix('0x')
    if re.fullmatch(r'[0-9a-fA-F]{64}', tx):
        lines.append(f'链上成交 · https://polygonscan.com/tx/0x{tx}')
    return MessageCandidate(topic=topic, dedupe_key=f"chain-trade:{row['id']}", text='\n'.join(lines),
                            priority='high' if row.get('severity') == 'critical' else 'normal', observed_at=stamp,
                            metadata={'panel': FLOW_PANEL, 'localMarketId': row.get('localMarketId') or row.get('marketId'),
                                      'fillTokenId': row.get('tokenId')})


def _headline(value, source):
    return re.sub(r'\W+', ' ', value.removesuffix(f' - {source}').removesuffix(f' {source}').casefold()).strip()


def _radar(row, *, topic, clean):
    source = clean(row.get('source'), limit=100)
    title = clean(row.get('title'), limit=250)
    url = _news_link(row.get('sourceUrl'))
    stamp = source_clock(row, 'eventTime')
    if row.get('evidenceType') != 'WIRE' or row.get('severity') not in {'watch', 'alert'} or not all((title, source, url, stamp)):
        return None
    lines = ['📰 突发事件雷达', title]
    summary = clean(unescape(re.sub(r'<[^>]*>', ' ', str(row.get('summary') or ''))), limit=310)
    if summary.casefold().startswith(title.casefold()):
        summary = summary[len(title):].lstrip(' ;:·–—-')
    if summary and _headline(summary, source) != _headline(title, source) and not re.search(r'\)\s*\(', summary):
        lines.append(f'报道摘要 · {summary}')
    if source == 'وكالة الانباء الاردنية':
        source = '约旦通讯社 Petra'
    lines.append(f'来源 · {source} · 北京时间 {_time(stamp)}')
    lines.append(url)
    return MessageCandidate(topic=topic, dedupe_key=f'radar-story:{_story_identity(url)}', text='\n'.join(lines),
                            priority='high' if row.get('severity') == 'alert' else 'normal', observed_at=stamp,
                            metadata={'panel': RADAR_PANEL})


def format_evidence_message(panel, row, *, topic, clean):
    formatter = _flow if panel == FLOW_PANEL else _radar
    return formatter(row, topic=topic, clean=clean)


def verified_market_url(market, local_id, fill_token):
    if str(market.get('localMarketId')) != str(local_id):
        return ''
    slug = market.get('slug') or ''
    if not re.fullmatch(r'[a-zA-Z0-9-]+', slug):
        return ''
    try:
        token = str(fill_token)
        token = int(token, 16 if token.startswith('0x') else 10)
    except (TypeError, ValueError):
        return ''
    tokens = {str(market.get('yesTokenId')), str(market.get('noTokenId'))}
    return f'https://polymarket.com/event/{slug}' if str(token) in tokens else ''
