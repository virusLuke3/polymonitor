"""Explicit projection ownership. Public reads do not start acquisition."""
from importlib import import_module

OWNERS = {
    'geo-conflict-watch': 'geopolitics_expansion',
    'geo-ceasefire-watch': 'geopolitics_expansion',
    'geo-territory-control': 'geopolitics_expansion',
    'geo-diplomacy-calendar': 'geopolitics_expansion',
    'geo-treaty-tracker': 'geopolitics_expansion',
    'weather-precipitation': 'weather_expansion',
    'weather-drought': 'weather_expansion',
    'weather-extremes': 'weather_expansion',
    'weather-storm-advisory': 'weather_expansion',
    'sports-spread-monitor': 'sports_expansion.snapshot_service',
    'sports-total-monitor': 'sports_expansion.snapshot_service',
    'sports-player-props': 'sports_expansion.snapshot_service',
    'sports-tournament-path': 'sports_expansion.snapshot_service',
    'sports-season-race': 'sports_expansion.snapshot_service',
    'sports-awards-watch': 'sports_expansion.snapshot_service',
    'esports-map-state': 'sports_expansion.snapshot_service',
    'esports-tournament-path': 'sports_expansion.snapshot_service',
    'crypto-listing-watch': 'finance_expansion',
    'crypto-project-milestones': 'finance_expansion',
    'chain-metrics-monitor': 'finance_expansion',
    'fiscal-tax-monitor': 'finance_expansion',
    'merger-progress': 'finance_expansion',
    'private-valuation-watch': 'finance_expansion',
    'ai-leaderboard-watch': 'culture_tech',
    'art-auction-watch': 'culture_tech',
    'culture-box-office': 'culture_tech',
    'culture-awards-race': 'culture_tech',
    'culture-music-charts': 'culture_tech',
    'product-release-watch': 'culture_tech',
    'public-figure-events': 'culture_tech',
    'reality-show-progress': 'culture_tech',
    'research-evidence-watch': 'culture_tech',
    'social-window-monitor': 'culture_tech',
    'space-mission-watch': 'culture_tech',
    'mentions-evidence': 'culture_tech',
}

def get_snapshot(store, panel_id, *, limit=100):
    owner = OWNERS.get(panel_id)
    if owner is None:
        raise KeyError(panel_id)
    return import_module("api.services." + owner).get_snapshot(store, panel_id, limit=limit)


def service_name(owner):
    names = {'geopolitics_expansion':'geopolitics','weather_expansion':'weather',
             'sports_expansion.snapshot_service':'sports','finance_expansion':'finance','culture_tech':'culture-tech'}
    return 'polymonitor-external-panels@'+names[owner]+'.service'


def health_specs():
    return [{'panelId': panel, 'namespace':'seed-meta:external', 'cacheKey':panel,
             'serviceName':service_name(owner), 'intervalEnv':'POLYMONITOR_EXTERNAL_HEALTH_INTERVAL_SECONDS',
             'defaultIntervalSeconds':3600} for panel, owner in OWNERS.items()]


def publish_health(store, owner):
    from runtime.seed_meta import build_seed_meta_payload, SeedMetaStore
    meta = SeedMetaStore(redis_client=None, redis_prefix='', snapshot_store=store)
    for panel, family in OWNERS.items():
        if family != owner:
            continue
        projection = get_snapshot(store, panel)
        sources = projection['sources']
        success = [s['lastSuccessAt'] for s in sources if s.get('usable') and s.get('lastSuccessAt')]
        attempts = [s['lastAttemptAt'] for s in sources if s.get('lastAttemptAt')]
        body = build_seed_meta_payload(panel_id=panel, namespace='source:external-panels:v1', cache_key=panel,
            service_name=service_name(owner), expected_interval_seconds=max([s.get('expectedIntervalSeconds', 3600) for s in sources] or [3600]),
            status=projection['status'], last_attempt_at=max(attempts) if attempts else None,
            last_success_at=min(success) if success else None,
            record_count=max([len(v) for k,v in projection.items() if isinstance(v,list) and k!='sources'] or [0]),
            source_states={s['id']: {'usable':s['usable'],'stale':s['stale'],'error':s.get('error'),
                          'lastSuccessAt':s.get('lastSuccessAt')} for s in sources},
            payload_status=projection['status'], metadata={'scope':'Acquisition health, not full strategy-field coverage'})
        meta.store('seed-meta:external', panel, body)
