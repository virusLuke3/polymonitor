"""Commodity alerts driven by quote, weekly release, and transit observations."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .models import MessageCandidate, source_clock

PANEL = 'commodity-equity-transmission'
OIL_STATE = PANEL + ':oil-events-v1'
FUTURES = {'brent': '布伦特', 'oil': 'WTI'}
OBSERVATIONS = {'inventory': ('商业原油库存', '百万桶'), 'spr': ('战略石油储备', '百万桶'),
                'production': ('原油日产量', '百万桶/日')}


def _time(stamp):
    return datetime.fromtimestamp(stamp, ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H:%M:%S')


def _markets(oil, benchmark):
    data = oil.get('markets') or {}
    if data.get('status') != 'ok':
        return []
    unique = {}
    for market in data.get('items') or ():
        if market.get('benchmark') == benchmark:
            unique.setdefault(market['eventTitle'], market)
    return [f"Polymarket · {m['source']} · {m['eventTitle']}\n{m['url']}" for m in list(unique.values())[:2]]


def _event(kind, key, lines, stamp):
    return MessageCandidate(topic='macro', dedupe_key=f'oil:{kind}:{key}', text='\n'.join(lines),
                            observed_at=stamp, metadata={'panel': PANEL, 'oilContext': True})


def _latest(series):
    points = series.get('points') or []
    return points[-1] if series.get('status') == 'ok' and points else None


def _release(oil):
    stocks = oil.get('inventory') or {}
    output = oil.get('production') or {}
    a, b = _latest(stocks), _latest(output)
    release = stocks.get('releaseOn')
    if not a or not b or not release or release != output.get('releaseOn') or a['period'] != b['period']:
        return None
    stamps = [source_clock(stocks, 'periodSeenAt'), source_clock(output, 'periodSeenAt')]
    return a['period'], release, max(stamps) if all(stamps) else None


def _weekly_lines(oil, period):
    for key, (label, unit) in OBSERVATIONS.items():
        series = oil.get(key) or {}
        current = _latest(series)
        if not current or current['period'] != period:
            continue
        points = series.get('points') or ()
        prior = points[-2] if len(points) >= 2 else None
        change = f" · 较上一观测周 {current['value'] - prior['value']:+.3f}" if prior else ''
        yield f"{label} {current['value']:.3f} {unit}{change}"


def _weekly_mean(points):
    if len(points) != 7 or (date.fromisoformat(points[-1]['period']) - date.fromisoformat(points[0]['period'])).days != 6:
        return None
    return sum(p['value'] for p in points) / 7


def plan_oil_alerts(oil, saved, *, now, prime, max_age):
    first = prime or saved is None
    after = now if first else saved['after']
    state = {} if first else dict(saved['observations'])
    candidates = []

    def fresh(stamp):
        return stamp is not None and max(after, now - max_age) < stamp <= now

    for quote in oil.get('futures') or ():
        key = quote.get('id')
        stamp = source_clock(quote, 'quoteAt')
        change, price = quote.get('changePercent'), quote.get('price')
        if (key not in FUTURES or quote.get('acquisitionState') != 'ok' or quote.get('changeBasis') != 'previous-close'
                or stamp is None or not 0 <= now - stamp <= max_age or change is None or price is None or price <= 0):
            continue
        old = state.get(key, {})
        if stamp <= old.get('at', 0):
            continue
        before = old.get('direction', 0)
        direction = (1 if change >= 2 else -1 if change <= -2 else 0 if abs(change) <= 1.5 else before)
        alert_at = old.get('alertAt', 0)
        if old and stamp - old['at'] <= max_age and direction and direction != before and stamp - alert_at >= 3600 and fresh(stamp):
            lines = [f"🛢 {FUTURES[key]}期货异动 · {quote['symbol']}", f'{price:.2f} 美元/桶 · 较前收 {change:+.2f}%',
                     f'Yahoo Finance 报价 · 北京时间 {_time(stamp)}']
            port = _latest(oil.get('hormuz') or {})
            if port:
                lines.append(f"霍尔木兹 {port['period']} · {port['value']} 艘次（IMF PortWatch）")
            lines += _markets(oil, 'brent' if key == 'brent' else 'wti')
            candidates.append(_event('futures', f'{key}:{int(stamp)}', lines, stamp))
            alert_at = stamp
        state[key] = {'at': stamp, 'direction': direction, 'alertAt': alert_at}

    if report := _release(oil):
        period, released, stamp = report
        old = state.get('eia', {})
        if period > old.get('period', ''):
            state['eia'] = {'period': period}
            local_day = datetime.fromtimestamp(now, ZoneInfo('America/New_York')).date().isoformat()
            if old and fresh(stamp) and released == local_day:
                lines = [f'🛢 EIA 美国石油周报 · 截至 {period}', *_weekly_lines(oil, period)]
                for key, label in (('brentSpot', '布伦特'), ('wtiSpot', 'WTI')):
                    series = oil.get(key) or {}
                    if series.get('releaseOn') == released and (spot := _latest(series)):
                        lines.append(f"{label}现货 {spot['value']:.2f} 美元/桶 · {spot['period']}")
                lines.append(f'EIA 发布日 {released} · 北京时间 {_time(stamp)} 首次读到新一周')
                lines += _markets(oil, 'eia')
                candidates.append(_event('eia', period, lines, stamp))

    transit = oil.get('hormuz') or {}
    if (latest := _latest(transit)) is not None:
        period = latest['period']
        old = state.get('hormuz', {})
        if period > old.get('period', ''):
            points = transit['points']
            stamp = source_clock(transit, 'periodSeenAt')
            current, before = _weekly_mean(points[-7:]), _weekly_mean(points[-14:-7])
            consecutive = len(points) >= 14 and (date.fromisoformat(period) - date.fromisoformat(points[-14]['period'])).days == 13
            change = current - before if current is not None and before is not None and consecutive else None
            trend = (1 if change > 0 else -1) if change is not None and abs(change) >= max(3, 0.25 * before) else 0
            prior = points[-2] if len(points) >= 2 else None
            consecutive_days = prior is not None and (date.fromisoformat(period) - date.fromisoformat(prior['period'])).days == 1
            zero = consecutive_days and latest['value'] == 0 and prior['value'] >= 3
            resumed = consecutive_days and latest['value'] >= 3 and prior['value'] == 0
            state['hormuz'] = {'period': period, 'trend': trend}
            age = (datetime.fromtimestamp(now, timezone.utc).date() - date.fromisoformat(period)).days
            if old and 0 <= age <= 7 and fresh(stamp) and (zero or resumed or trend and trend != old.get('trend')):
                label = '单日通行降至零' if zero else '从零恢复通行' if resumed else '7 日通行量明显变化'
                lines = [f'🚢 霍尔木兹 · {label}', f"{period} 共 {latest['value']} 艘次"]
                if latest.get('tankers') is not None:
                    lines[-1] += f" · 油轮 {latest['tankers']} 艘次"
                if change is not None:
                    lines.append(f'日均 {current:.1f} 艘次 · 前 7 日 {before:.1f} 艘次')
                lines.append(f'IMF PortWatch 观测日 {period} · 北京时间 {_time(stamp)} 首次读到该日')
                lines += _markets(oil, 'hormuz')
                candidates.append(_event('hormuz', period, lines, stamp))

    return candidates, {'after': after, 'observations': state}, first
