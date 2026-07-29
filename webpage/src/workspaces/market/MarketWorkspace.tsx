import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import {
  MetricCard,
  operationalTone,
  StatusBadge,
  type OperationalTone,
} from '@/components/design-system/StatusPrimitives';
import {
  formatCompact,
  formatCurrencyCompact,
  formatDate,
  formatPercent,
  formatRelative,
  formatSignedPercent,
  shortHash,
  signedClass,
} from '@/panels/shared/formatters';
import { fetchMarketLobByToken, fetchWorkspaceBundle } from '@/services/api';
import { fetchAuthSession } from '@/services/auth';
import { addWatchlistMarket } from '@/services/product';
import type {
  ChartPoint,
  ContentItem,
  L2Level,
  LobPayload,
  MarketEvidenceClaim,
  MarketGroupOutcome,
  OracleEvent,
  TradeRow,
  WorkspaceBundle,
} from '@/types';

const REFRESH_INTERVAL_MS = 30_000;
const MAX_VISIBLE_TRADES = 16;
const MAX_VISIBLE_CONTENT = 8;
const MAX_BOOK_LEVELS = 8;

type BookSide = 'yes' | 'no';

function readMarketId(): number | null {
  if (typeof window === 'undefined') return null;
  const match = window.location.pathname.match(/^\/markets\/(\d+)(?:\/|$)/);
  const marketId = Number(match?.[1]);
  return Number.isSafeInteger(marketId) && marketId > 0 ? marketId : null;
}

function parseTimestamp(value?: string | null): number | null {
  const parsed = Date.parse(String(value || ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function ageSeconds(value?: string | null): number | null {
  const parsed = parseTimestamp(value);
  return parsed == null ? null : Math.max(0, Math.round((Date.now() - parsed) / 1_000));
}

function freshnessFromTimestamp(value?: string | null, staleAfterSeconds = 300): string {
  const age = ageSeconds(value);
  if (age == null) return 'unknown';
  if (age <= staleAfterSeconds) return 'fresh';
  if (age <= staleAfterSeconds * 6) return 'aging';
  return 'stale';
}

function longAge(value?: string | null): string {
  const age = ageSeconds(value);
  if (age == null) return 'No timestamp';
  if (age < 60) return `${age}s ago`;
  if (age < 3_600) return `${Math.round(age / 60)}m ago`;
  if (age < 86_400) return `${Math.round(age / 3_600)}h ago`;
  return `${Math.round(age / 86_400)}d ago`;
}

function statusTone(status?: string | null): OperationalTone {
  const normalized = String(status || '').toLowerCase();
  if (normalized.includes('mismatch') || normalized.includes('missing') || normalized === 'error') return 'critical';
  if (
    normalized.includes('partial')
    || normalized.includes('stale')
    || normalized.includes('aging')
    || normalized.includes('snapshot')
    || normalized.includes('open-no-events')
    || normalized.includes('single-market')
    || normalized.includes('not-loaded')
  ) return 'warning';
  return operationalTone(normalized);
}

function formatProbabilityCents(value?: string | number | null): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '--';
  return `${Math.round(numeric * 100)}¢`;
}

function formatShares(value?: string | number | null): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '--';
  return numeric.toLocaleString('en-US', {
    maximumFractionDigits: numeric >= 100 ? 0 : 2,
  });
}

function formatNotional(price?: string | number | null, size?: string | number | null): string {
  const numericPrice = Number(price);
  const numericSize = Number(size);
  if (!Number.isFinite(numericPrice) || !Number.isFinite(numericSize)) return '--';
  return `$${(numericPrice * numericSize).toLocaleString('en-US', {
    maximumFractionDigits: numericPrice * numericSize >= 100 ? 0 : 2,
  })}`;
}

function cleanSource(value?: string | null): string {
  return String(value || 'unknown')
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (character: string) => character.toUpperCase());
}

function selectedOutcome(bundle: WorkspaceBundle | null): MarketGroupOutcome | null {
  if (!bundle) return null;
  if (bundle.selectedOutcome) return bundle.selectedOutcome;
  const marketId = bundle.market?.id || bundle.identity?.localMarketId;
  return (bundle.group?.outcomes || []).find((outcome) => Number(outcome.marketId) === Number(marketId)) || null;
}

function probabilityPoint(point: ChartPoint): number | null {
  const value = Number(point.yesPrice ?? point.value);
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : null;
}

function chartGeometry(points: ChartPoint[]) {
  const clean = points
    .map((point, index) => ({ index, value: probabilityPoint(point) }))
    .filter((point): point is { index: number; value: number } => point.value != null);
  if (!clean.length) return null;
  const width = 760;
  const height = 250;
  const left = 14;
  const right = 14;
  const top = 18;
  const bottom = 24;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const project = (point: { index: number; value: number }) => {
    const x = left + (point.index / Math.max(points.length - 1, 1)) * plotWidth;
    const y = top + (1 - point.value) * plotHeight;
    return { x, y };
  };
  const projected = clean.map(project);
  const linePath = projected.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(' ');
  const first = projected[0];
  const last = projected[projected.length - 1];
  const areaPath = first && last
    ? `${linePath} L${last.x.toFixed(2)},${(height - bottom).toFixed(2)} L${first.x.toFixed(2)},${(height - bottom).toFixed(2)} Z`
    : '';
  return {
    width,
    height,
    linePath,
    areaPath,
    last,
    latest: clean[clean.length - 1]?.value ?? null,
  };
}

function ProbabilityChart({ bundle }: { bundle: WorkspaceBundle }) {
  const points = bundle.chart?.points || [];
  const geometry = chartGeometry(points);
  if (!geometry || points.length < 2) {
    return (
      <div className="market-empty-state">
        <strong>No probability curve</strong>
        <span>The latest quote remains visible, but local history is not available.</span>
      </div>
    );
  }
  const firstTimestamp = points.find((point) => point.timestamp)?.timestamp || null;
  const lastTimestamp = [...points].reverse().find((point) => point.timestamp)?.timestamp || null;
  return (
    <div className="market-chart-shell">
      <div className="market-chart-meta">
        <span>{cleanSource(bundle.chart?.priceSource || 'market history')}</span>
        <span>{points.length} observations</span>
        <span>{bundle.chart?.range || '--'} / {bundle.chart?.interval || '--'}</span>
      </div>
      <svg
        className="market-probability-chart"
        viewBox={`0 0 ${geometry.width} ${geometry.height}`}
        role="img"
        aria-label={`YES probability history with ${points.length} observations`}
      >
        <defs>
          <linearGradient id="marketProbabilityArea" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stop-color="rgba(57, 255, 115, 0.28)" />
            <stop offset="100%" stop-color="rgba(57, 255, 115, 0)" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((value) => {
          const y = 18 + (1 - value) * (geometry.height - 42);
          return (
            <g key={value}>
              <line x1="14" x2={geometry.width - 14} y1={y} y2={y} className="market-chart-gridline" />
              <text x={geometry.width - 18} y={y - 5} className="market-chart-grid-label">{Math.round(value * 100)}%</text>
            </g>
          );
        })}
        <path d={geometry.areaPath} fill="url(#marketProbabilityArea)" />
        <path d={geometry.linePath} className="market-chart-line" />
        {geometry.last ? <circle cx={geometry.last.x} cy={geometry.last.y} r="5" className="market-chart-endpoint" /> : null}
      </svg>
      <div className="market-chart-axis">
        <span>{formatDate(firstTimestamp)}</span>
        <strong>{formatPercent(geometry.latest)} YES</strong>
        <span>{formatDate(lastTimestamp)}</span>
      </div>
    </div>
  );
}

function topLevels(levels?: L2Level[], side: 'bid' | 'ask' = 'bid') {
  return [...(levels || [])]
    .sort((left, right) => (
      side === 'bid'
        ? Number(right.price || 0) - Number(left.price || 0)
        : Number(left.price || 0) - Number(right.price || 0)
    ))
    .slice(0, MAX_BOOK_LEVELS);
}

function BookTable({ title, levels, side }: { title: string; levels?: L2Level[]; side: 'bid' | 'ask' }) {
  const visible = topLevels(levels, side);
  return (
    <div className={`market-book-side is-${side}`}>
      <div className="market-book-side-title">
        <strong>{title}</strong>
        <span>{visible.length} levels</span>
      </div>
      <div className="market-table market-book-table" role="table">
        <div className="market-table-head" role="row">
          <span>Price</span><span>Shares</span><span>Notional</span>
        </div>
        {visible.map((level, index) => (
          <div className="market-table-row" role="row" key={`${side}-${index}-${level.price}-${level.size}`}>
            <strong>{formatProbabilityCents(level.price)}</strong>
            <span>{formatShares(level.size)}</span>
            <span>{formatNotional(level.price, level.size)}</span>
          </div>
        ))}
        {!visible.length ? <div className="market-table-empty">No {side} levels observed</div> : null}
      </div>
    </div>
  );
}

function OrderBook({ lob }: { lob?: LobPayload | null }) {
  const [side, setSide] = useState<BookSide>('yes');
  const active = side === 'yes' ? lob?.yes : lob?.no;
  return (
    <section className="market-card market-orderbook-card">
      <div className="market-section-heading">
        <div>
          <span>Execution Evidence</span>
          <h2>Live order book</h2>
        </div>
        <div className="market-segmented-control" role="tablist" aria-label="Order book outcome">
          <button type="button" className={side === 'yes' ? 'active' : ''} onClick={() => setSide('yes')}>YES</button>
          <button type="button" className={side === 'no' ? 'active' : ''} onClick={() => setSide('no')}>NO</button>
        </div>
      </div>
      <div className="market-quote-strip">
        <span><em>Best bid</em><strong>{formatProbabilityCents(active?.bestBid)}</strong></span>
        <span><em>Best ask</em><strong>{formatProbabilityCents(active?.bestAsk)}</strong></span>
        <span><em>Spread</em><strong>{formatProbabilityCents(active?.spread)}</strong></span>
        <span><em>Observed</em><strong>{longAge(lob?.fetchedAt)}</strong></span>
      </div>
      <div className="market-book-grid">
        <BookTable title={`${side.toUpperCase()} bids`} levels={active?.bids} side="bid" />
        <BookTable title={`${side.toUpperCase()} asks`} levels={active?.asks} side="ask" />
      </div>
      {!lob ? (
        <div className="market-inline-notice">
          No CLOB snapshot is available. The identity and probability evidence remain usable.
        </div>
      ) : null}
    </section>
  );
}

function evidenceClaims(bundle: WorkspaceBundle): MarketEvidenceClaim[] {
  const claims = [...(bundle.evidence?.claims || [])];
  const contentItems = bundle.content?.items || [];
  const latestContent = contentItems
    .map((item) => item.publishedAt)
    .filter((value): value is string => Boolean(value))
    .sort()
    .reverse()[0] || null;
  claims.push({
    id: 'lob',
    label: 'CLOB liquidity',
    status: bundle.lob?.bookStatus || (bundle.lob ? 'ok' : 'missing'),
    source: bundle.lob?.source || 'clob-book',
    observedAt: bundle.lob?.fetchedAt || null,
    recordCount: (bundle.lob?.yes?.bids?.length || 0)
      + (bundle.lob?.yes?.asks?.length || 0)
      + (bundle.lob?.no?.bids?.length || 0)
      + (bundle.lob?.no?.asks?.length || 0),
    detail: 'Best bid, best ask and visible depth levels',
  });
  claims.push({
    id: 'content',
    label: 'Linked intelligence',
    status: contentItems.length ? 'ok' : 'missing',
    source: bundle.content?.sourceMode || 'content-index',
    observedAt: latestContent,
    recordCount: contentItems.length,
    detail: 'Market-linked reporting and primary-source context',
  });
  return claims;
}

function EvidenceChain({ bundle }: { bundle: WorkspaceBundle }) {
  const claims = evidenceClaims(bundle);
  return (
    <section className="market-card market-evidence-card">
      <div className="market-section-heading">
        <div>
          <span>Audit Trail</span>
          <h2>Evidence chain</h2>
        </div>
        <StatusBadge
          label={bundle.evidence?.contractVersion || 'CLIENT DERIVED'}
          tone={bundle.evidence ? 'positive' : 'warning'}
          compact
        />
      </div>
      <p className="market-section-intro">
        Every headline number is paired with its source, observation time and local coverage.
      </p>
      <div className="market-evidence-list">
        {claims.map((claim, index) => (
          <article className="market-evidence-row" key={`${claim.id}-${index}`}>
            <span className="market-evidence-step">{String(index + 1).padStart(2, '0')}</span>
            <div className="market-evidence-copy">
              <strong>{claim.label}</strong>
              <span>{claim.detail || 'No additional source detail'}</span>
              <em>{cleanSource(claim.source)} · {longAge(claim.observedAt)}</em>
            </div>
            <div className="market-evidence-result">
              <StatusBadge label={claim.status.toUpperCase()} tone={statusTone(claim.status)} compact />
              <strong>{claim.recordCount ?? '--'}</strong>
              <span>records</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function IdentifierRow({ label, value }: { label: string; value?: string | number | null }) {
  const stringValue = String(value || '');
  return (
    <div className="market-identifier-row">
      <span>{label}</span>
      <code title={stringValue || undefined}>{stringValue ? shortHash(stringValue, 14, 8) : '--'}</code>
      {stringValue ? (
        <button
          type="button"
          onClick={() => void navigator.clipboard.writeText(stringValue)}
          aria-label={`Copy ${label}`}
        >
          Copy
        </button>
      ) : null}
    </div>
  );
}

function ResolutionContract({ bundle }: { bundle: WorkspaceBundle }) {
  const market = bundle.market;
  const oracleSummary = bundle.oracle?.summary;
  return (
    <section className="market-card market-resolution-card">
      <div className="market-section-heading">
        <div>
          <span>Resolution Contract</span>
          <h2>What decides this market</h2>
        </div>
        <StatusBadge
          label={String(oracleSummary?.completionStatus || bundle.oracle?.completionStatus || market?.status || 'unknown').toUpperCase()}
          tone={statusTone(oracleSummary?.completionStatus || bundle.oracle?.completionStatus || market?.status)}
        />
      </div>
      <div className="market-resolution-copy">
        {market?.description || 'No resolution criteria were included in the local market registry.'}
      </div>
      <div className="market-identifier-grid">
        <IdentifierRow label="Local market" value={bundle.identity?.localMarketId || market?.id} />
        <IdentifierRow label="Gamma market" value={bundle.identity?.gammaMarketId || market?.gammaMarketId} />
        <IdentifierRow label="Condition ID" value={bundle.identity?.conditionId || market?.conditionId} />
        <IdentifierRow label="Question ID" value={bundle.identity?.questionId || market?.questionId} />
        <IdentifierRow label="YES token" value={bundle.identity?.yesTokenId || market?.yesTokenId} />
        <IdentifierRow label="NO token" value={bundle.identity?.noTokenId || market?.noTokenId} />
      </div>
    </section>
  );
}

function TradeTable({ trades }: { trades: TradeRow[] }) {
  return (
    <section className="market-card market-trades-card">
      <div className="market-section-heading">
        <div>
          <span>On-chain Execution</span>
          <h2>OrderFilled tape</h2>
        </div>
        <StatusBadge label={`${trades.length} ROWS`} tone={trades.length ? 'positive' : 'warning'} compact />
      </div>
      <div className="market-data-table-wrap">
        <table className="market-data-table">
          <thead>
            <tr>
              <th>Observed</th>
              <th>Side / outcome</th>
              <th>Price</th>
              <th>Size</th>
              <th>Maker → taker</th>
              <th>Event key</th>
            </tr>
          </thead>
          <tbody>
            {trades.slice(0, MAX_VISIBLE_TRADES).map((trade, index) => (
              <tr key={`${trade.txHash || 'trade'}-${trade.logIndex ?? index}`}>
                <td><time>{formatDate(trade.timestamp)}</time><small>{formatRelative(trade.timestamp)}</small></td>
                <td><strong className={String(trade.side || '').toLowerCase()}>{trade.side || '--'}</strong><small>{trade.outcome || 'Outcome unknown'}</small></td>
                <td>{formatProbabilityCents(trade.price)}</td>
                <td>{formatShares(trade.size)}</td>
                <td><code>{shortHash(trade.maker, 7, 4)}</code><small>→ {shortHash(trade.taker, 7, 4)}</small></td>
                <td><code>{shortHash(trade.txHash, 8, 5)}</code><small>log {trade.logIndex ?? '--'}</small></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!trades.length ? <div className="market-table-empty">No local OrderFilled rows are available for this market.</div> : null}
      </div>
    </section>
  );
}

function OracleTimeline({ events, bundle }: { events: OracleEvent[]; bundle: WorkspaceBundle }) {
  const current = bundle.oracle?.summary?.completionStatus || bundle.oracle?.completionStatus || 'OPEN';
  const oracleStages = [
    { id: 'request', label: 'Request', matcher: /request/i },
    { id: 'propose', label: 'Propose', matcher: /propos/i },
    { id: 'dispute', label: 'Dispute', matcher: /disput/i },
    { id: 'settle', label: 'Settle', matcher: /settle|resolve/i },
  ].map((stage) => ({
    ...stage,
    event: events.find((event) => stage.matcher.test(String(event.eventStatus || event.completionStatus || ''))),
  }));
  return (
    <section className="market-card market-oracle-card">
      <div className="market-section-heading">
        <div>
          <span>Resolution Lifecycle</span>
          <h2>Oracle timeline</h2>
        </div>
        <StatusBadge label={String(current).toUpperCase()} tone={statusTone(current)} />
      </div>
      <div className="market-oracle-phase-rail" aria-label="Oracle lifecycle phases">
        {oracleStages.map((stage, index) => (
          <article className={stage.event ? 'is-observed' : 'is-pending'} key={stage.id}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <div>
              <strong>{stage.label}</strong>
              <em>{stage.event ? formatRelative(stage.event.eventTime) : 'Not observed'}</em>
            </div>
          </article>
        ))}
      </div>
      <div className="market-timeline">
        {events.map((event, index) => (
          <article className="market-timeline-row" key={`${event.txHash || event.id || 'oracle'}-${event.logIndex ?? index}`}>
            <span className="market-timeline-node" />
            <div>
              <strong>{event.eventStatus || event.completionStatus || 'Oracle observation'}</strong>
              <span>{event.settlementOutcome || event.proposedPrice || event.settledPrice || 'No outcome value published'}</span>
              <em>{formatDate(event.eventTime)} · {cleanSource(event.sourceAdapter || event.sourceOracle || 'oracle')}</em>
            </div>
            <code>{shortHash(event.txHash, 9, 5)}<small>log {event.logIndex ?? '--'}</small></code>
          </article>
        ))}
        {!events.length ? (
          <div className="market-empty-state is-compact">
            <strong>No proposal or settlement event yet</strong>
            <span>The market is identity-bound, but its Oracle lifecycle has not started.</span>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ContentCard({ item }: { item: ContentItem }) {
  const body = (
    <>
      <div className="market-content-meta">
        <span>{cleanSource(item.provider || item.source || item.contentType)}</span>
        <time>{formatRelative(item.publishedAt)}</time>
      </div>
      <strong>{item.title || 'Untitled market intelligence'}</strong>
      {item.summary ? <p>{item.summary}</p> : null}
      <div className="market-content-footer">
        <span>{item.category || 'Market context'}</span>
        {item.relevanceScore != null ? <em>Relevance {Math.round(Number(item.relevanceScore) * 100)}%</em> : null}
      </div>
    </>
  );
  return item.url ? (
    <a className="market-content-item" href={item.url} target="_blank" rel="noopener noreferrer">{body}</a>
  ) : (
    <article className="market-content-item">{body}</article>
  );
}

function LinkedIntelligence({ items }: { items: ContentItem[] }) {
  return (
    <section className="market-card market-content-card">
      <div className="market-section-heading">
        <div>
          <span>Reality Layer</span>
          <h2>Linked intelligence</h2>
        </div>
        <StatusBadge label={`${items.length} ITEMS`} tone={items.length ? 'info' : 'warning'} compact />
      </div>
      <div className="market-content-grid">
        {items.slice(0, MAX_VISIBLE_CONTENT).map((item, index) => (
          <ContentCard item={item} key={item.id || `${item.url || item.title}-${index}`} />
        ))}
      </div>
      {!items.length ? (
        <div className="market-empty-state is-compact">
          <strong>No linked reporting</strong>
          <span>This does not change the market evidence; it means no contextual content is indexed.</span>
        </div>
      ) : null}
    </section>
  );
}

function OutcomeRail({
  outcomes,
  activeMarketId,
  activeYesPrice,
}: {
  outcomes: MarketGroupOutcome[];
  activeMarketId?: number | null;
  activeYesPrice?: string | number | null;
}) {
  if (!outcomes.length) return null;
  return (
    <section className="market-outcome-rail" aria-label="Event outcomes">
      <div className="market-outcome-rail-heading">
        <span>Event outcomes</span>
        <strong>{outcomes.length} contracts</strong>
      </div>
      <div className="market-outcome-list">
        {outcomes.map((outcome, index) => {
          const marketId = Number(outcome.marketId);
          const active = Number.isFinite(marketId) && marketId === Number(activeMarketId);
          const displayedPrice = active && activeYesPrice != null ? activeYesPrice : outcome.yesPrice;
          const content = (
            <>
              <span>{outcome.label || outcome.title || `Outcome ${index + 1}`}</span>
              <strong>{formatPercent(displayedPrice)}</strong>
              <em>{formatCurrencyCompact(outcome.volume24h)} · {formatCompact(outcome.tradeCount24h)} tx</em>
            </>
          );
          return Number.isFinite(marketId) && marketId > 0 ? (
            <a
              className={active ? 'active' : ''}
              href={`/markets/${marketId}`}
              aria-current={active ? 'page' : undefined}
              key={outcome.outcomeKey || marketId}
            >
              {content}
            </a>
          ) : (
            <div className="pending" key={outcome.outcomeKey || index}>{content}</div>
          );
        })}
      </div>
    </section>
  );
}

export function MarketWorkspace() {
  const marketId = readMarketId();
  const [bundle, setBundle] = useState<WorkspaceBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<number | null>(null);
  const [watchState, setWatchState] = useState<'idle' | 'busy' | 'watched'>('idle');
  const requestRef = useRef(0);

  const refresh = useCallback(async () => {
    if (!marketId) {
      setError('The market URL does not contain a valid numeric market ID.');
      setLoading(false);
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    try {
      const next = await fetchWorkspaceBundle(marketId, { includeContent: true, includeLob: true });
      if (!next.market) {
        throw new Error(`Market #${marketId} returned no market identity.`);
      }
      const outcome = selectedOutcome(next);
      const tokenId = String(outcome?.yesTokenId || next.identity?.yesTokenId || next.market?.yesTokenId || '').trim();
      const noTokenId = String(outcome?.noTokenId || next.identity?.noTokenId || next.market?.noTokenId || '').trim();
      if (tokenId) {
        try {
          next.lob = await fetchMarketLobByToken(tokenId, outcome?.label || next.market?.title || '', noTokenId, 3500);
        } catch {
          // The market dossier remains usable when the live book is unavailable.
        }
      }
      if (requestId !== requestRef.current) return;
      setBundle(next);
      setError(null);
      setLastRefreshedAt(Date.now());
    } catch (loadError) {
      if (requestId !== requestRef.current) return;
      setError(loadError instanceof Error ? loadError.message : 'Unable to load this market workspace.');
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [marketId]);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      void refresh();
    }, REFRESH_INTERVAL_MS);
    return () => {
      window.clearInterval(interval);
      requestRef.current += 1;
    };
  }, [refresh]);

  const outcome = useMemo(() => selectedOutcome(bundle), [bundle]);
  const market = bundle?.market;

  const watchMarket = async () => {
    if (!marketId) return;
    setWatchState('busy');
    try {
      const session = await fetchAuthSession();
      if (!session.authenticated) {
        window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
        return;
      }
      if (session.user?.forcePasswordChange) {
        window.location.assign('/account');
        return;
      }
      await addWatchlistMarket(marketId);
      setWatchState('watched');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to add this market to the watchlist.');
      setWatchState('idle');
    }
  };
  const price = bundle?.price;
  const yesPrice = price?.latestYesPrice ?? price?.latestPrice ?? outcome?.yesPrice ?? market?.latestYesPrice ?? market?.latestPrice;
  const noPrice = price?.latestNoPrice ?? outcome?.noPrice ?? market?.latestNoPrice;
  const volume = price?.volume24h ?? outcome?.volume24h;
  const trades24h = price?.tradeCount24h ?? outcome?.tradeCount24h;
  const observedAt = price?.updatedAt || bundle?.generatedAt || null;
  const freshness = freshnessFromTimestamp(observedAt, 300);
  const healthLevel = String(bundle?.health?.level || bundle?.diagnostics?.level || (error ? 'critical' : 'unknown'));
  const sourceClaims = bundle ? evidenceClaims(bundle) : [];
  const readyClaims = sourceClaims.filter((claim) => statusTone(claim.status) === 'positive').length;
  const issueCount = bundle?.evidence?.issues?.length || bundle?.health?.issues?.length || 0;
  const tags = useMemo(
    () => [...new Set([market?.category, ...(market?.tags || [])].filter((tag): tag is string => Boolean(tag)))].slice(0, 7),
    [market?.category, market?.tags],
  );

  useEffect(() => {
    if (!market?.title) return;
    const previousTitle = document.title;
    document.title = `${market.title} · PolyData Market Dossier`;
    return () => {
      document.title = previousTitle;
    };
  }, [market?.title]);

  if (!marketId) {
    return (
      <div className="market-shell">
        <main className="market-fatal-state">
          <StatusBadge label="INVALID MARKET URL" tone="critical" />
          <h1>Market workspace unavailable</h1>
          <p>Use a URL such as <code>/markets/2784982</code> or open a market from the Atlas search.</p>
          <a href="/">Return to Atlas</a>
        </main>
      </div>
    );
  }

  return (
    <div className="market-shell">
      <header className="market-topbar">
        <div className="market-brand-cluster">
          <a className="market-home-link" href="/">◎ Atlas</a>
          <a className="market-home-link" href="/data-quality">Quality</a>
          <div className="market-brand">POLYDATA MARKET DOSSIER <span>EVIDENCE-FIRST WORKSPACE</span></div>
        </div>
        <div className="market-actions">
          <span className="market-refresh-note">
            {lastRefreshedAt ? `Observed ${new Date(lastRefreshedAt).toLocaleTimeString()}` : 'Awaiting first observation'}
          </span>
          <button type="button" disabled={watchState !== 'idle'} onClick={() => void watchMarket()}>
            {watchState === 'busy' ? 'Adding…' : watchState === 'watched' ? 'Watching ✓' : 'Watch market'}
          </button>
          <button type="button" onClick={() => void navigator.clipboard.writeText(window.location.href)}>Copy link</button>
          <button type="button" className="primary" disabled={loading} onClick={() => void refresh()}>
            {loading ? 'Refreshing…' : 'Refresh evidence'}
          </button>
        </div>
      </header>

      <main className="market-main">
        <section className="market-hero">
          <div className="market-hero-copy">
            <div className="market-kicker-row">
              <span>Market / {marketId}</span>
              <StatusBadge
                label={String(market?.status || (loading ? 'loading' : 'unknown')).toUpperCase()}
                tone={statusTone(market?.status || (loading ? 'loading' : 'unknown'))}
                compact
              />
              <StatusBadge label={freshness.toUpperCase()} tone={statusTone(freshness)} compact />
            </div>
            <h1>{market?.title || (loading ? 'Loading market dossier…' : `Market #${marketId}`)}</h1>
            <p>
              {outcome?.label && outcome.label !== market?.title
                ? `Focused outcome: ${outcome.label}`
                : 'One auditable surface for probability, execution, resolution and real-world evidence.'}
            </p>
            <div className="market-hero-tags">
              {tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>
          </div>
          <div className="market-probability-lockup">
            <span>Current YES probability</span>
            <strong>{formatPercent(yesPrice)}</strong>
            <em className={signedClass(price?.change24h)}>{formatSignedPercent(price?.change24h)} / 24h</em>
            <div>
              <span>NO <b>{formatPercent(noPrice)}</b></span>
              <span>Closes <b>{formatRelative(market?.endDate)}</b></span>
            </div>
          </div>
        </section>

        {error ? (
          <div className="market-error-banner" role="alert">
            <span>{error}</span>
            <em>{bundle ? 'Last good evidence remains visible.' : 'Retry when the API is available.'}</em>
          </div>
        ) : null}

        {bundle ? (
          <>
            <section className="market-metric-grid" aria-label="Market summary">
              <MetricCard
                eyebrow="YES probability"
                value={formatPercent(yesPrice)}
                detail={`${cleanSource(price?.priceSource || bundle.servingSource)} · ${longAge(observedAt)}`}
                tone={yesPrice == null ? 'warning' : 'positive'}
              />
              <MetricCard
                eyebrow="24h volume"
                value={formatCurrencyCompact(volume)}
                detail={`${bundle.trades.length} local OrderFilled rows · ${formatCompact(trades24h)} reported 24h`}
                tone={Number(volume || 0) > 0 ? 'info' : 'neutral'}
              />
              <MetricCard
                eyebrow="Evidence readiness"
                value={`${readyClaims}/${sourceClaims.length}`}
                detail={`${issueCount} active contract issues`}
                tone={issueCount ? 'warning' : (readyClaims ? 'positive' : 'neutral')}
              />
              <MetricCard
                eyebrow="Resolution"
                value={String(bundle.oracle?.summary?.completionStatus || bundle.oracle?.completionStatus || market?.status || '--').toUpperCase()}
                detail={`${bundle.oracle?.timeline?.length || 0} Oracle lifecycle events`}
                tone={statusTone(bundle.oracle?.summary?.completionStatus || bundle.oracle?.completionStatus || market?.status)}
              />
              <MetricCard
                eyebrow="Workspace health"
                value={healthLevel.toUpperCase()}
                detail={`${bundle.servingSource || 'fallback'} serving · contract v1`}
                tone={statusTone(healthLevel)}
              />
            </section>

            <OutcomeRail
              outcomes={bundle.group?.outcomes || []}
              activeMarketId={market?.id || bundle.identity?.localMarketId}
              activeYesPrice={yesPrice}
            />

            <div className="market-primary-grid">
              <section className="market-card market-chart-card">
                <div className="market-section-heading">
                  <div>
                    <span>Probability Evidence</span>
                    <h2>Market history</h2>
                  </div>
                  <StatusBadge
                    label={String(bundle.health?.chartStatus || bundle.chart?.historyStatus || 'unknown').toUpperCase()}
                    tone={statusTone(bundle.health?.chartStatus || bundle.chart?.historyStatus)}
                  />
                </div>
                <ProbabilityChart bundle={bundle} />
              </section>
              <EvidenceChain bundle={bundle} />
            </div>

            <div className="market-secondary-grid">
              <ResolutionContract bundle={bundle} />
              <OrderBook lob={bundle.lob} />
            </div>

            <TradeTable trades={bundle.trades || []} />

            <div className="market-secondary-grid">
              <OracleTimeline events={bundle.oracle?.timeline || []} bundle={bundle} />
              <LinkedIntelligence items={bundle.content?.items || []} />
            </div>
          </>
        ) : (
          <section className="market-loading-grid" aria-label="Loading market workspace">
            {Array.from({ length: 8 }, (_, index) => <div className="market-skeleton" key={index} />)}
          </section>
        )}
      </main>
    </div>
  );
}

export default MarketWorkspace;
