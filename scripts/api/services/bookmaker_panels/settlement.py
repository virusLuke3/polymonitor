"""Versioned rule evidence and payoff differences, never executable arbitrage.

Rule pages use the same durable evidence and env-only transport as odds. Each
recognized clause has its own state; a successful HTML request is not approval.
"""
from functools import partial
from bs4 import BeautifulSoup
from api.services.panel_evidence_store import SourceSpec, collect_sources, read_source
from .matching import decimal_line


def parse_rules(body, kind):
    text = ' '.join(BeautifulSoup(body, 'html.parser').stripped_strings).lower()
    facts = {}
    if kind == 'general' and 'push rule' in text and 'in all cases stakes are returned' in text:
        facts['equality'] = 'refund'
    if kind == 'basketball':
        if 'overtime counts for all markets except' in text:
            facts['overtime'] = 'included'
        if 'if any other match is postponed' in text and 'no action' in text:
            facts['postponed'] = 'refund_except_playoffs_48h'
        if 'nba games are official after 43 minutes' in text:
            facts['abandonment'] = '43_minutes'
    if kind == 'soccer':
        if 'at the end of 90 minutes' in text and 'does not include extra time' in text:
            facts['overtime'] = 'regulation'
        if 'if any match is postponed' in text and 'within 24 hours' in text:
            facts['postponed'] = 'refund_except_listed_24h'
    if not facts:
        raise ValueError('Rule clauses not recognized')
    return {'facts': facts}


RULES = tuple(SourceSpec('bookmakers:rules:bovada:'+kind+':v1', 'Bovada '+kind+' rules',
    'POLYDATA_ODDS_BOVADA_'+kind.upper()+'_RULES_URL', partial(parse_rules, kind=kind),
    cadence=86400, stale_after=172800, retain_for=7*86400, max_bytes=2*1024**2, timeout=30)
    for kind in ('general', 'basketball', 'soccer'))


def collect_rules(store):
    return collect_sources(store, RULES, budget=70)


def rule_snapshot(store):
    result = {}
    for spec in RULES:
        data, meta = read_source(store, spec)
        result[spec.key.split(':')[-2]] = {'facts': data.get('facts', {}), 'current': meta['usable'] and not meta['stale'] and not meta['error'],
                                         'checkedAt': meta['lastSuccessAt'], 'revision': meta['revision']}
    return result


def evaluate(q, m, rules, sport):
    """A known conflict is distinct from missing evidence, with no inferred DNP."""
    pm = m.get('ruleFacts', {})
    details, missing = [], []
    general, domain = rules.get('general', {}), rules.get({'nba': 'basketball', 'soccer': 'soccer'}.get(sport), {})
    if q['book'] != 'bovada' or not general.get('current') or not domain.get('current'):
        return {'status': 'unknown', 'reasons': ['bookmaker_rules_unavailable'], 'scenarios': [], 'arbitrageReady': False}
    facts = domain.get('facts', {})
    if facts.get('overtime') and pm.get('overtime') not in (None, 'unknown'):
        if facts['overtime'] != pm['overtime']:
            details.append({'case': 'overtime', 'bookmaker': facts['overtime'], 'polymarket': pm['overtime']})
    else:
        missing.append('overtime_unverified')
    # The book's postponed-event refund can coexist with a PM market which
    # remains open or redeems at 50 cents. Neither is a stake refund at any price.
    if facts.get('postponed') and pm.get('cancel') not in (None, 'unknown'):
        details.append({'case': 'postponement_or_no_result', 'bookmaker': facts['postponed'], 'polymarket': pm['cancel']})
    else:
        missing.append('no_result_unverified')
    line = decimal_line(m.get('line'))
    if line is not None and line % 1 == 0:
        eq = pm.get('equality', 'unknown')
        if general.get('facts', {}).get('equality') == 'refund' and eq != 'unknown':
            details.append({'case': 'equal_to_line', 'bookmaker': 'stake_refund', 'polymarket': eq})
        else:
            missing.append('push_payoff_unverified')
    if m['type'] == 'player_totals':
        missing.append('player_participation_unverified')
        if pm.get('dnp') == 'no':
            details.append({'case': 'did_not_play', 'bookmaker': 'unknown', 'polymarket': 'no'})
    return {'status': 'conflict' if any(d['bookmaker'] != 'unknown' for d in details) else 'unknown',
            'reasons': missing, 'scenarios': details, 'arbitrageReady': False,
            'checkedAt': domain.get('checkedAt')}


def push_pnl(stake, pm_shares, pm_entry, pm_redemption):
    """At a sportsbook push, its profit is zero; PM return depends on entry.

    Kept explicit for replay/risk consumers; never assume a 50/50 PM settlement
    returns the initial PM stake. Inputs are prices per $1 redeemable share.
    """
    values = [decimal_line(v) for v in (stake, pm_shares, pm_entry, pm_redemption)]
    if any(v is None for v in values):
        raise ValueError('Invalid payoff inputs')
    stake, shares, entry, redemption = values
    if stake < 0 or shares < 0 or not 0 <= entry <= 1 or not 0 <= redemption <= 1:
        raise ValueError('Invalid payoff bounds')
    return float(shares * (redemption - entry))
