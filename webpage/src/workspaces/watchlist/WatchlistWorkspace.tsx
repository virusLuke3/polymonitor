import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import { fetchAuthSession, type AuthSession } from '@/services/auth';
import {
  addWatchlistMarket,
  createAlertRule,
  deleteAlertRule,
  fetchAlerts,
  fetchNotificationPreferences,
  fetchWatchlist,
  markAlertRead,
  markAllAlertsRead,
  removeWatchlistMarket,
  updateNotificationPreferences,
  type AlertEvent,
  type NotificationPreferences,
  type Watchlist,
} from '@/services/product';
import { AuthFrame, LoadingAccess, SignInPanel, errorMessage } from '@/workspaces/auth/AuthWorkspace';

const PRICE_KINDS = new Set(['price_above', 'price_below']);
const LABELS: Record<string, string> = {
  price_above: 'Price above',
  price_below: 'Price below',
  oracle_gap: 'Oracle gap',
  oracle_proposed: 'Oracle proposed',
  oracle_disputed: 'Oracle disputed',
  oracle_resolved: 'Oracle resolved',
  market_closed: 'Market closed',
};

const timeValue = (minute: number | null) =>
  minute == null ? '' : `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
const minuteValue = (value: string) => value ? Number(value.slice(0, 2)) * 60 + Number(value.slice(3, 5)) : null;
const percent = (value: number | null) => value == null ? '—' : `${(value * 100).toFixed(1)}%`;

export function WatchlistWorkspace() {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [watchlist, setWatchlist] = useState<Watchlist | null>(null);
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [marketId, setMarketId] = useState('');
  const [selectedMarketId, setSelectedMarketId] = useState<number | null>(null);
  const [kind, setKind] = useState('price_above');
  const [threshold, setThreshold] = useState('0.60');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const nextSession = await fetchAuthSession();
    setSession(nextSession);
    if (nextSession.authenticated && !nextSession.user?.forcePasswordChange) {
      const [nextWatchlist, nextAlerts, nextPreferences] = await Promise.all([
        fetchWatchlist(), fetchAlerts(), fetchNotificationPreferences(),
      ]);
      setWatchlist(nextWatchlist);
      setAlerts(nextAlerts.items);
      setPreferences(nextPreferences);
      setSelectedMarketId((current) => current || nextWatchlist.items[0]?.marketId || null);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    refresh().catch((caught) => {
      setError(errorMessage(caught));
      setReady(true);
    });
  }, [refresh]);

  const selected = useMemo(
    () => watchlist?.items.find((item) => item.marketId === selectedMarketId) || null,
    [watchlist, selectedMarketId],
  );

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  if (!ready) return <LoadingAccess />;
  if (!session?.authenticated) return <AuthFrame><SignInPanel next="/watchlist" /></AuthFrame>;
  if (session.user?.forcePasswordChange) {
    return <AuthFrame><main className="watchlist-main watchlist-gate"><span>ACCOUNT ACTION REQUIRED</span><h1>Replace the bootstrap password first.</h1><a href="/account">Open access control</a></main></AuthFrame>;
  }

  return (
    <AuthFrame>
      <main className="watchlist-main">
        <section className="watchlist-hero">
          <div>
            <span className="watchlist-kicker">PERSONAL MARKET INTELLIGENCE / ORACLE SIGNAL RAIL</span>
            <h1>Watchlist & Alerts</h1>
            <p>Track canonical Polymarket probabilities and Oracle lifecycle transitions without copying market facts into a second source of truth.</p>
          </div>
          <div className="watchlist-hero-actions">
            <a href="/">Open Atlas</a>
            <button type="button" disabled={busy} onClick={() => void refresh()}>{busy ? 'Working…' : 'Refresh now'}</button>
          </div>
        </section>

        {error ? <div className="watchlist-error" role="alert">{error}</div> : null}

        <section className="watchlist-metrics" aria-label="Watchlist status">
          <div><span>MARKETS</span><strong>{watchlist?.summary.markets || 0}</strong><small>Canonical local IDs</small></div>
          <div><span>ACTIVE RULES</span><strong>{watchlist?.summary.activeRules || 0}</strong><small>Crossing and state change</small></div>
          <div><span>ORACLE GAPS</span><strong>{watchlist?.summary.oracleGaps || 0}</strong><small>Ended, not final</small></div>
          <div><span>UNREAD</span><strong>{watchlist?.summary.unreadAlerts || 0}</strong><small>In-app events</small></div>
        </section>

        <div className="watchlist-grid">
          <section className="watchlist-panel watchlist-markets">
            <header><div><span>MARKET REGISTRY</span><h2>Tracked markets</h2></div><em>{watchlist?.items.length || 0} / 200</em></header>
            <form className="watchlist-add" onSubmit={(event) => {
              event.preventDefault();
              const parsed = Number(marketId);
              if (Number.isSafeInteger(parsed) && parsed > 0) void run(async () => {
                await addWatchlistMarket(parsed);
                setMarketId('');
                setSelectedMarketId(parsed);
              });
            }}>
              <label><span>Local market ID</span><input inputMode="numeric" value={marketId} onInput={(event) => setMarketId(event.currentTarget.value)} placeholder="2784982" required /></label>
              <button type="submit" disabled={busy}>Add market</button>
            </form>
            {!watchlist?.items.length ? (
              <div className="watchlist-empty"><strong>No markets tracked yet.</strong><p>Open a Market Dossier or paste a canonical local market ID above.</p></div>
            ) : (
              <div className="watchlist-market-list">
                {watchlist.items.map((item) => (
                  <article key={item.marketId} className={item.marketId === selectedMarketId ? 'is-selected' : ''}>
                    <button className="watchlist-market-select" type="button" onClick={() => setSelectedMarketId(item.marketId)}>
                      <span className={`watchlist-stage is-${item.oracleStage}`}>{item.oracleStage}</span>
                      <strong>{item.title}</strong>
                      <small>#{item.marketId} · {item.category || 'Uncategorized'}</small>
                    </button>
                    <div className="watchlist-market-price"><strong>{percent(item.latestPrice)}</strong><small>{item.change24h == null ? 'No 24h baseline' : `${item.change24h >= 0 ? '+' : ''}${percent(item.change24h)} / 24h`}</small></div>
                    <div className="watchlist-market-links"><a href={`/markets/${item.marketId}`}>Dossier ↗</a><button type="button" onClick={() => void run(() => removeWatchlistMarket(item.marketId))}>Remove</button></div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="watchlist-panel watchlist-rules">
            <header><div><span>RULE ENGINE</span><h2>Alert readiness</h2></div><em>{selected ? `#${selected.marketId}` : 'Select a market'}</em></header>
            {selected ? (
              <>
                <h3>{selected.title}</h3>
                <form className="watchlist-rule-form" onSubmit={(event) => {
                  event.preventDefault();
                  void run(() => createAlertRule(selected.marketId, kind, PRICE_KINDS.has(kind) ? Number(threshold) : null));
                }}>
                  <label><span>Condition</span><select value={kind} onChange={(event) => setKind(event.currentTarget.value)}>{(watchlist?.alertKinds || []).map((value) => <option value={value} key={value}>{LABELS[value] || value}</option>)}</select></label>
                  {PRICE_KINDS.has(kind) ? <label><span>Probability (0–1)</span><input type="number" min="0.01" max="0.99" step="0.01" value={threshold} onInput={(event) => setThreshold(event.currentTarget.value)} required /></label> : null}
                  <button type="submit" disabled={busy}>Arm rule</button>
                </form>
                <div className="watchlist-rule-list">
                  {selected.rules.map((rule) => (
                    <div key={rule.id}><span className={rule.conditionActive ? 'is-live' : ''}>{rule.conditionActive ? '● ACTIVE' : '○ ARMED'}</span><strong>{LABELS[rule.kind] || rule.kind}{rule.threshold == null ? '' : ` · ${percent(rule.threshold)}`}</strong><button type="button" onClick={() => void run(() => deleteAlertRule(rule.id))}>Delete</button></div>
                  ))}
                </div>
              </>
            ) : <div className="watchlist-empty"><strong>Choose a tracked market.</strong><p>Oracle gap and dispute rules are armed automatically on add.</p></div>}
          </section>
        </div>

        <section className="watchlist-panel watchlist-inbox">
          <header><div><span>EVENT INBOX</span><h2>Observed transitions</h2></div><button type="button" disabled={busy || !alerts.some((item) => !item.readAt)} onClick={() => void run(markAllAlertsRead)}>Mark all read</button></header>
          {!alerts.length ? <div className="watchlist-empty"><strong>No alert events yet.</strong><p>The production evaluator records only new threshold crossings and Oracle state transitions.</p></div> :
            <div className="watchlist-alert-list">{alerts.map((item) => <article key={item.id} className={`${item.readAt ? 'is-read' : ''} is-${item.severity}`}><span>{item.severity}</span><div><strong>{item.title}</strong><p>{item.detail}</p><small>{item.marketTitle || `Market #${item.marketId}`} · {new Date(item.occurredAt).toLocaleString()}</small></div>{item.readAt ? <em>READ</em> : <button type="button" onClick={() => void run(() => markAlertRead(item.id))}>Mark read</button>}</article>)}</div>}
        </section>

        {preferences ? <section className="watchlist-panel watchlist-preferences">
          <header><div><span>DELIVERY POLICY</span><h2>Notification preferences</h2></div><em>In-app channel</em></header>
          <form onSubmit={(event) => {
            event.preventDefault();
            void run(() => updateNotificationPreferences({
              inAppEnabled: preferences.inAppEnabled,
              digestMode: preferences.digestMode,
              quietStartMinute: preferences.quietStartMinute,
              quietEndMinute: preferences.quietEndMinute,
              timezone: preferences.timezone,
            }));
          }}>
            <label className="watchlist-switch"><input type="checkbox" checked={preferences.inAppEnabled} onChange={(event) => setPreferences({ ...preferences, inAppEnabled: event.currentTarget.checked })} /><span>Enable in-app alert evaluation</span></label>
            <label><span>Cadence</span><select value={preferences.digestMode} onChange={(event) => setPreferences({ ...preferences, digestMode: event.currentTarget.value as NotificationPreferences['digestMode'] })}><option value="realtime">Realtime</option><option value="hourly">Hourly digest</option><option value="daily">Daily digest</option><option value="off">Off</option></select></label>
            <label><span>Quiet from</span><input type="time" value={timeValue(preferences.quietStartMinute)} onInput={(event) => setPreferences({ ...preferences, quietStartMinute: minuteValue(event.currentTarget.value) })} /></label>
            <label><span>Quiet until</span><input type="time" value={timeValue(preferences.quietEndMinute)} onInput={(event) => setPreferences({ ...preferences, quietEndMinute: minuteValue(event.currentTarget.value) })} /></label>
            <label><span>Timezone</span><input value={preferences.timezone} onInput={(event) => setPreferences({ ...preferences, timezone: event.currentTarget.value })} /></label>
            <button type="submit" disabled={busy}>Save policy</button>
          </form>
          <p>Telegram remains isolated in its existing runtime. Email delivery is not configured; these settings govern the product's in-app evaluator.</p>
        </section> : null}
      </main>
    </AuthFrame>
  );
}

export default WatchlistWorkspace;
