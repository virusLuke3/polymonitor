from copy import deepcopy
import json
import time
import zlib

import pytest
from api.services.bookmaker_panels.matching import (
    Aliases, assess, compatible_selection, event, identity, market_links, scheduled,
)
from api.services.bookmaker_panels.match_store import MatchStore
from api.services.bookmaker_panels.match_owner import attach_matches, NAMESPACE, SNAPSHOT, run_cycle


def fixture():
    return dict(id='source:one', provider='source', sport='cs2', home='FUT Esports', away='MOUZ',
                competition='CS2 - BLAST Rivals', startTime='2026-11-12T07:00:00Z', quotes=[])


def market(**changes):
    return dict(id=1, slug='cs2-fut-mouz-2026-11-12', event_id='100',
                title='Counter-Strike: FUT Esports vs MOUZ (BO3) - BLAST Rivals Group B',
                description='Initially scheduled for November 12, 2026 at 2:00 AM ET. If canceled, resolves 50-50.',
                condition_id='0x'+'1'*64, yes_token_id='11', no_token_id='22',
                quote_token_ids=['22', '11'], quote_labels=['MOUZ', 'FUT Esports'],
                quote_condition_id='0x'+'1'*64, quote_prices=['.6', '.4'],
                quote_observed_at='2026-11-12T06:00:00Z', quote_updated_at=None) | changes


def test_dst_and_rules_time_not_end_date():
    assert scheduled('scheduled for Wednesday, November 11, 2026 at 7:00 PM ET') == 1794441600
    assert scheduled('scheduled for July 1, 2026 at 7:00 PM ET') == 1782946800
    assert event(market(description='', end_date='2026-11-12T07:00:00Z')) is None


def test_exact_reverse_and_price_invariance():
    f = fixture()
    f.update(home='MOUZ', away='FUT Esports')
    d, e = assess(f, [market()], Aliases())
    assert d['state'] == 'linked'
    d2, _ = assess(f, [market(quote_prices=['.01', '.99'])], Aliases())
    assert d == d2
    m = market_links(e, [market()])[0]
    q = dict(category='sportsbook', market='h2h', period='full', outcomes=[{'name': 'FUT Esports'}, {'name': 'MOUZ'}])
    assert compatible_selection(f, q, m, Aliases()) == [dict(selection='FUT Esports', tokenId='11'), dict(selection='MOUZ', tokenId='22')]
    assert m['settlement'] == 'unknown'


@pytest.mark.parametrize('suffix', ['Academy', 'Women', 'U21', 'NXT', 'Junior'])
def test_never_strip_team_identity_qualifiers(suffix):
    f = fixture(); f['home'] += ' ' + suffix
    assert assess(f, [market()], Aliases())[0]['state'] != 'linked'


def test_namespace_ambiguity_and_time_conflicts():
    f = fixture()
    assert assess(f, [market(), market(event_id='101')], Aliases())[0]['reason'] == 'ambiguous_event'
    assert assess(f, [market()], Aliases(), truncated=True)[0]['state'] == 'incomplete'
    f['startTime'] = '2026-11-12T08:00:00Z'
    assert assess(f, [market()], Aliases())[0]['reason'] == 'kickoff_conflict'
    f = fixture(); f['sport'] = 'lol'
    assert assess(f, [market()], Aliases())[0]['state'] == 'unmatched'
    f = fixture(); f['competition'] = 'Different Tournament'
    assert assess(f, [market()], Aliases())[0]['reason'] == 'competition_unverified'


def test_alias_requires_evidence_and_is_scoped():
    with pytest.raises(ValueError):
        Aliases([dict(sport='nba', entity='pacers', names=['Pacers', 'Indiana Pacers'])])
    aliases = Aliases([dict(sport='nba', entity='pacers', names=['Pacers', 'Indiana Pacers'], evidence='official-team:11')])
    assert aliases.same('nba', 'Pacers', 'Indiana Pacers')
    assert not aliases.same('lol', 'Pacers', 'Indiana Pacers')


def test_totals_require_exact_half_line_metric_and_period():
    f = fixture(); e = event(market())
    total = market(slug=e['row']['slug']+'-total-games-2pt5', quote_labels=['Over', 'Under'], title='O/U 2.5 games')
    m = market_links(e, [total])[0]
    q = dict(category='sportsbook', market='totals', metric='maps', period='full',
             outcomes=[dict(name='Over', point=2.5), dict(name='Under', point=2.5)])
    assert compatible_selection(f, q, m, Aliases())
    for change in (dict(metric='rounds'), dict(period='map1'), dict(metric=None)):
        assert compatible_selection(f, q | change, m, Aliases()) is None
    q['outcomes'][1]['point'] = 3.5
    assert compatible_selection(f, q, m, Aliases()) is None
    assert market_links(e, [total | dict(slug=e['row']['slug']+'-total-games-2',title='O/U 2 games')])[0]['line'] == '2'
    assert not market_links(e, [total | dict(slug=e['row']['slug']+'-game1-total-2pt5')])


def test_spread_team_sign_is_not_home_position():
    f = fixture(); e = event(market())
    spread = market(slug=e['row']['slug']+'-map-handicap-home-1pt5', title='Map Handicap: MOUZ (-1.5) vs FUT Esports (+1.5)')
    m = market_links(e, [spread])[0]
    q = dict(category='sportsbook', market='spreads', metric='maps', period='full',
             outcomes=[dict(name='FUT Esports', point=1.5), dict(name='MOUZ', point=-1.5)])
    assert compatible_selection(f, q, m, Aliases())
    q['outcomes'][0]['point'] = -1.5
    q['outcomes'][1]['point'] = 1.5
    assert compatible_selection(f, q, m, Aliases()) is None


def test_wrong_token_condition_and_yes_no_never_link():
    e = event(market())
    for changes in (dict(quote_condition_id='0x'+'2'*64), dict(quote_token_ids=['22','22']), dict(quote_labels=['Yes','No'])):
        assert market_links(e, [market(**changes)]) == []


def test_restart_stable_event_and_evidence_retains_original_rules(tmp_path):
    a = MatchStore(tmp_path/'match.db'); a.initialize(); f = fixture(); k = identity(f)
    d, _ = assess(f, [market()], Aliases())
    first = a.save(k, f, d, [market()], 1000, 300)
    again = MatchStore(a.path).save(k, f, d, [market(description='changed')], 1300, 300)
    assert again['eventId'] == first['eventId']
    assert again['firstLinkedAt'] == 1000
    with a.connect() as db:
        saved = list(db.execute('SELECT body FROM evidence ORDER BY id'))
    assert json.loads(zlib.decompress(saved[0][0]))['evidence'][0]['description'] == market()['description']
    assert json.loads(zlib.decompress(saved[1][0]))['evidence'][0]['description'] == 'changed'


def test_unchanged_poll_does_not_duplicate_evidence_and_unavailability_keeps_event_id(tmp_path):
    a = MatchStore(tmp_path/'match.db'); a.initialize(); f = fixture(); k = identity(f)
    d, _ = assess(f, [market()], Aliases())
    first = a.save(k, f, d, [market()], 1000, 300)
    a.save(k, f, d, [market(quote_observed_at='2026-11-12T07:00:00Z')], 1300, 300)
    with a.connect() as db:
        assert db.execute('SELECT count(*) FROM evidence').fetchone()[0] == 1
    a.save(k, f, dict(state='unavailable'), {}, 1400, 120)
    a.prune(1500)
    assert a.save(k, f, d, [market()], 1500, 300)['eventId'] == first['eventId']


class Store:
    def __init__(self): self.value = {}; self.published = 0
    def get_stale(self, ns, k): return self.value if (ns,k) == (NAMESPACE,SNAPSHOT) else None
    def set(self, ns,k,v,ttl_seconds): self.value = deepcopy(v); self.published += 1; return True


def test_get_never_queries_and_changed_identity_invalidates(monkeypatch):
    f = fixture(); d,e = assess(f,[market()],Aliases()); m = market_links(e,[market()])
    s = Store(); s.value = dict(generatedAt=1000, decisions={identity(f):d | dict(checkedAt=1000,markets=m)}, aliases=[])
    out = attach_matches(s,[f],now=1001)[0]['polymarketMatch']
    assert out['state'] == 'linked' and not out['stale']
    assert out['markets'][0]['comparisonReady'] is False
    assert attach_matches(s,[f],now=1601)[0]['polymarketMatch']['stale']
    assert attach_matches(s,[f | dict(home='FUT Academy')],now=1001)[0]['polymarketMatch']['state'] == 'pending'


def test_worker_unavailable_not_unmatched_and_commit_precedes_publish(tmp_path,monkeypatch):
    from api.services.bookmaker_panels import snapshot_service
    monkeypatch.setattr(snapshot_service,'read_board',lambda *a,**kw: {'fixtures':[fixture()]})
    class Catalog:
        def candidates(self,f): raise TimeoutError('private diagnostic')
    a = MatchStore(tmp_path/'match.db');a.initialize();s=Store()
    counts = run_cycle(s,a,Catalog())
    assert counts['errors'] == 1 and s.published == 1
    assert a.decisions()[identity(fixture())]['state'] == 'unavailable'
    assert 'private diagnostic' not in json.dumps(s.value)
    monkeypatch.setattr(a,'save',lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):run_cycle(s,a,Catalog(),now=time.time()+300)
    assert s.published == 1


def test_catalog_failure_retains_previous_mapping_without_renewing_verification(tmp_path, monkeypatch):
    from api.services.bookmaker_panels import snapshot_service
    from api.services.bookmaker_panels.match_owner import aliases
    f = fixture(); k = identity(f)
    monkeypatch.setattr(snapshot_service, 'read_board', lambda *a, **kw: {'fixtures': [f]})
    a = MatchStore(tmp_path/'match.db'); a.initialize(); s = Store()
    d, e = assess(f, [market()], Aliases())
    verified = time.time() - 400
    d.update(verifiedAt=verified, aliasVersion=aliases().version, markets=market_links(e, [market()]))
    first = a.save(k, f, d, {}, verified, 300)
    class Catalog:
        def candidates(self, f): raise TimeoutError()
    run_cycle(s, a, Catalog())
    current = a.decisions()[k]
    assert current['state'] == 'unavailable' and current['verifiedAt'] == verified
    assert current['eventId'] == first['eventId'] and current['markets'] == first['markets']
    assert attach_matches(s, [f])[0]['polymarketMatch']['stale']


def test_soccer_three_way_binary_complement_and_regulation():
    r = market(slug='epl-one-two-2026-11-12-draw', event_slug='epl-one-two-2026-11-12',
               event_title='One FC vs. Two FC', title='Will One FC vs. Two FC end in a draw?',
               description='scheduled for November 12, 2026 at 2:00 AM ET. First 90 minutes plus stoppage time.', quote_labels=['No','Yes'])
    f = fixture() | dict(sport='soccer', home='Two FC', away='One FC', competition='Premier League')
    d, e = assess(f,[r],Aliases()); assert d['state'] == 'linked'
    m = market_links(e,[r])[0]
    q = dict(category='sportsbook',market='h2h',period='full',outcomes=[dict(name=n) for n in ('Two FC','Draw','One FC')])
    pairs = compatible_selection(f,q,m,Aliases())
    assert pairs == [dict(selection='Two FC',tokenId='22'),dict(selection='Draw',tokenId='11'),dict(selection='One FC',tokenId='22')]
    assert compatible_selection(f,q | dict(outcomes=q['outcomes'][::2]),m,Aliases()) is None
    assert market_links(e,[r | dict(description='First 45 minutes')]) == []


def test_player_identity_stat_threshold_and_binary_tokens():
    root = market(slug='nba-one-two-2026-11-12',title='One vs. Two')
    e = event(root)
    r = market(slug=root['slug']+'-points-alex-one-20',title='Alex One: Points O/U 20',quote_labels=['No','Yes'],
        description='Alex One scores more than 20 points. 20 points or fewer. The entire game including all overtime periods. If inactive or otherwise does not take the court at any point, resolve "No".')
    m = market_links(e,[r])[0]
    f = fixture() | dict(sport='nba')
    q = dict(category='sportsbook',market='player_totals',metric='points',period='full',player='Alex One',outcomes=[dict(name='Over',point=20),dict(name='Under',point=20)])
    assert compatible_selection(f,q,m,Aliases())[0]['tokenId'] == '11'
    assert m['ruleFacts']['equality'] == 'under'
    for change in (dict(player='Alex Two'),dict(metric='rebounds'),dict(period='half1')):
        assert compatible_selection(f,q | change,m,Aliases()) is None


def test_rule_documents_and_push_refund_are_not_pm_split():
    from api.services.bookmaker_panels.settlement import parse_rules, evaluate, push_pnl
    facts = parse_rules(b'<h1>Push Rule. In all cases stakes are returned.</h1>', 'general')
    assert facts['facts']['equality'] == 'refund'
    with pytest.raises(ValueError): parse_rules(b'<html>blocked</html>','general')
    rules = dict(general=dict(current=True,facts=facts['facts']),basketball=dict(current=True,facts=dict(overtime='included',postponed='refund_except_playoffs_48h')))
    m = dict(type='player_totals',line='20',ruleFacts=dict(overtime='included',cancel='split',dnp='no',equality='under'))
    check = evaluate(dict(book='bovada'),m,rules,'nba')
    assert check['status']=='conflict' and not check['arbitrageReady']
    assert any(x['case']=='equal_to_line' and x['polymarket']=='under' for x in check['scenarios'])
    assert push_pnl(100,100,.7,.5) == -20
    rules['general']['current']=False
    assert evaluate(dict(book='bovada'),m,rules,'nba')['status']=='unknown'


def test_quote_structure_changes_recheck_but_prices_do_not():
    from api.services.bookmaker_panels.match_owner import selection_shape
    q = dict(market='player_totals',period='full',player='Alex One',metric='points',outcomes=[dict(name='Over',point=20,decimal=1.9),dict(name='Under',point=20,decimal=1.9)])
    f = fixture() | dict(quotes=[q])
    initial=selection_shape(f)
    q['outcomes'][0]['decimal']=2.1
    assert selection_shape(f)==initial
    q['player']='Alex Two'
    assert selection_shape(f)!=initial


def test_conflicting_title_and_slug_lines_are_not_linked():
    e = event(market())
    assert not market_links(e,[market(slug=e['row']['slug']+'-total-games-2',title='O/U 2.5 games',quote_labels=['Over','Under'])])
    assert not market_links(e,[market(slug=e['row']['slug']+'-map-handicap-home-1pt5',title='Map Handicap: MOUZ (-2.5) vs FUT Esports (+2.5)')])
