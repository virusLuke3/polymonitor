import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import { MobileWorkspaceNav } from '@/components/MobileWorkspaceNav';
import { fetchAuthSession, type AuthSession } from '@/services/auth';
import {
  createBriefing,
  fetchBriefings,
  fetchPublicBriefing,
  revokeBriefing,
  type BriefingMarket,
  type BriefingRegistryItem,
  type PublicBriefing,
} from '@/services/product';
import { AuthFrame, LoadingAccess, SignInPanel, errorMessage } from '@/workspaces/auth/AuthWorkspace';

const percent = (value: number | null) => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
const compact = (value: number) => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value || 0);

function briefingPublicId() {
  if (typeof window === 'undefined') return null;
  const match = window.location.pathname.match(/^\/briefings\/([A-Za-z0-9_-]{32})(?:\/|$)/);
  return match?.[1] || null;
}

function MarketRows({ items, empty }: { items: BriefingMarket[]; empty: string }) {
  if (!items.length) return <div className="brief-empty">{empty}</div>;
  return (
    <div className="brief-market-list">
      {items.map((market) => (
        <a href={`/markets/${market.marketId}`} key={market.marketId}>
          <div>
            <span className={`brief-stage is-${market.oracleStage}`}>{market.oracleStage}</span>
            <strong>{market.title}</strong>
            <small>#{market.marketId} · {market.category || 'Uncategorized'} · {market.completionStatus}</small>
          </div>
          <div className="brief-price">
            <strong>{percent(market.latestPrice)}</strong>
            <span className={(market.change24h || 0) >= 0 ? 'is-positive' : 'is-negative'}>
              {market.change24h == null ? 'No 24h baseline' : `${market.change24h >= 0 ? '+' : ''}${percent(market.change24h)}`}
            </span>
            <small>${compact(market.volume24h)} volume</small>
          </div>
        </a>
      ))}
    </div>
  );
}

export function PublicBriefingWorkspace() {
  const publicId = briefingPublicId();
  const [briefing, setBriefing] = useState<PublicBriefing | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!publicId) {
      setError('This briefing URL is invalid.');
      return;
    }
    fetchPublicBriefing(publicId).then(setBriefing).catch((caught) => setError(errorMessage(caught)));
  }, [publicId]);

  if (!briefing && !error) {
    return <div className="brief-shell"><main className="brief-loading"><span>CANONICAL SNAPSHOT</span><h1>Opening prediction-market briefing…</h1></main></div>;
  }
  if (!briefing) {
    return <div className="brief-shell"><main className="brief-loading"><span>BRIEFING UNAVAILABLE</span><h1>{error}</h1><a href="/">Return to Atlas</a></main></div>;
  }
  const snapshot = briefing.snapshot;
  return (
    <div className="brief-shell">
      <header className="brief-topbar">
        <a href="/">◎ Atlas</a>
        <div>POLYDATA BRIEFING <span>READ-ONLY CANONICAL SNAPSHOT</span></div>
        <button type="button" onClick={() => void navigator.clipboard.writeText(window.location.href)}>Copy link</button>
      </header>
      <main className="brief-main">
        <section className="brief-hero">
          <div>
            <span>PREDICTION MARKET INTELLIGENCE / GENERATED {new Date(snapshot.generatedAt).toLocaleString()}</span>
            <h1>{briefing.title}</h1>
            <p>A point-in-time view of tracked markets, active liquidity and unresolved Oracle attention.</p>
          </div>
          <div className="brief-validity"><span>LINK VALID UNTIL</span><strong>{new Date(briefing.expiresAt).toLocaleDateString()}</strong><small>Revocable by its owner</small></div>
        </section>
        <section className="brief-metrics">
          <div><span>TRACKED</span><strong>{snapshot.summary.trackedMarkets}</strong></div>
          <div><span>LIQUID MARKETS</span><strong>{snapshot.summary.topMarkets}</strong></div>
          <div><span>ORACLE ATTENTION</span><strong>{snapshot.summary.oracleAttention}</strong></div>
          <div><span>WORKSPACE REV</span><strong>{snapshot.workspaceLens.revision || '—'}</strong></div>
        </section>
        <div className="brief-grid">
          <section className="brief-card brief-card-wide">
            <header><div><span>PERSONAL LENS</span><h2>Tracked markets</h2></div><em>{snapshot.trackedMarkets.length} observed</em></header>
            <MarketRows items={snapshot.trackedMarkets} empty="No tracked markets were present when this briefing was generated." />
          </section>
          <section className="brief-card">
            <header><div><span>ORACLE LIFECYCLE</span><h2>Attention ledger</h2></div><em>Unresolved</em></header>
            <MarketRows items={snapshot.oracleAttention} empty="No unresolved Oracle gaps or disputes were selected." />
          </section>
          <section className="brief-card">
            <header><div><span>MARKET ACTIVITY</span><h2>Highest 24h volume</h2></div><em>Canonical serving</em></header>
            <MarketRows items={snapshot.topMarkets} empty="No active market volume was available." />
          </section>
        </div>
        <section className="brief-provenance">
          <div><span>SOURCE CONTRACT</span><strong>{snapshot.source.kind}</strong></div>
          <p>{snapshot.source.markets}<br />{snapshot.source.oracle}</p>
          <p>{snapshot.source.warning}</p>
        </section>
      </main>
      <MobileWorkspaceNav />
    </div>
  );
}

export function BriefingManagerWorkspace() {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [items, setItems] = useState<BriefingRegistryItem[]>([]);
  const [title, setTitle] = useState('');
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const nextSession = await fetchAuthSession();
    setSession(nextSession);
    if (nextSession.authenticated && !nextSession.user?.forcePasswordChange) {
      setItems((await fetchBriefings()).items || []);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    refresh().catch((caught) => {
      setError(errorMessage(caught));
      setReady(true);
    });
  }, [refresh]);

  const activeCount = useMemo(() => items.filter((item) => item.active).length, [items]);
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
  if (!session?.authenticated) return <AuthFrame><SignInPanel next="/briefings" /></AuthFrame>;
  if (session.user?.forcePasswordChange) return <AuthFrame><main className="brief-manager-main brief-gate"><h1>Replace the bootstrap password first.</h1><a href="/account">Open access control</a></main></AuthFrame>;

  return (
    <AuthFrame>
      <main className="brief-manager-main">
        <section className="brief-manager-hero">
          <div><span>SNAPSHOT DESK / SHARE CONTROL</span><h1>Briefing Registry</h1><p>Create a revocable, 30-day snapshot from canonical market and Oracle facts. Shared readers never receive your alert rules, notes or credentials.</p></div>
          <div><strong>{activeCount}/20</strong><span>ACTIVE LINKS</span></div>
        </section>
        {error ? <div className="brief-alert is-error">{error}</div> : null}
        {notice ? <div className="brief-alert">{notice}</div> : null}
        <form className="brief-create" onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            const item = (await createBriefing(title)).item;
            const url = `${window.location.origin}/briefings/${item.publicId}`;
            await navigator.clipboard.writeText(url);
            setNotice('Briefing created and share URL copied.');
            setTitle('');
          });
        }}>
          <label><span>Briefing title</span><input value={title} maxLength={120} onInput={(event) => setTitle(event.currentTarget.value)} placeholder={`Prediction Market Brief · ${new Date().toLocaleDateString()}`} /></label>
          <button type="submit" disabled={busy || activeCount >= 20}>{busy ? 'Generating snapshot…' : 'Generate & copy link'}</button>
        </form>
        <section className="brief-registry">
          <header><div><span>CAPABILITY LINKS</span><h2>Recent briefings</h2></div><em>Newest first</em></header>
          {!items.length ? <div className="brief-empty">No briefings yet. Generate the first canonical snapshot above.</div> :
            <div className="brief-registry-list">{items.map((item) => {
              const url = `${window.location.origin}/briefings/${item.publicId}`;
              return <article key={item.id} className={item.active ? '' : 'is-inactive'}>
                <div><span>{item.active ? '● ACTIVE' : item.revokedAt ? '○ REVOKED' : '○ EXPIRED'}</span><strong>{item.title}</strong><small>Created {new Date(item.createdAt).toLocaleString()} · expires {new Date(item.expiresAt).toLocaleString()}</small></div>
                <div>{item.active ? <><a href={url} target="_blank" rel="noreferrer">Open</a><button type="button" onClick={() => void navigator.clipboard.writeText(url).then(() => setNotice('Share URL copied.'))}>Copy</button><button type="button" onClick={() => void run(() => revokeBriefing(item.id))}>Revoke</button></> : null}</div>
              </article>;
            })}</div>}
        </section>
      </main>
    </AuthFrame>
  );
}
