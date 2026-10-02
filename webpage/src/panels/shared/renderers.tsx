import type { ContentItem, OracleEvent, TradeRow } from '@/types';
import { formatCompact, formatDate, formatPercent, formatRelative, shortHash } from './formatters';

type EmptyStateCopy = {
  label?: string;
  detail?: string;
};

type OracleListCopy = {
  noActivity?: string;
  finalCount?: (count: number) => string;
  proposedCount?: (count: number) => string;
  boundCount?: (count: number) => string;
  finalized?: string;
  finalizedOutcome?: (outcome: string) => string;
  disputed?: string;
  proposed?: string;
  requested?: string;
  event?: string;
  pending?: string;
  unboundEvent?: string;
  unbound?: string;
  marketNumber?: (id: number | string) => string;
  formatRelative?: (value?: string | null) => string;
  formatDate?: (value?: string | null) => string;
  empty?: EmptyStateCopy;
};

type ContentListCopy = {
  untitled?: string;
  readSource?: string;
  formatDate?: (value?: string | null) => string;
  empty?: EmptyStateCopy;
};

function emptyState(message: string, copy: EmptyStateCopy = {}) {
  return (
    <div className="wm-empty wm-empty-card">
      <span>{copy.label || 'Standby'}</span>
      <strong>{message}</strong>
      <em>{copy.detail || 'The panel will update automatically when this source has rows for the selected market.'}</em>
    </div>
  );
}

function tradeNotional(trade: TradeRow) {
  const size = Number(trade.size);
  const price = Number(trade.price);
  if (!Number.isFinite(size) || !Number.isFinite(price)) return null;
  return size * price;
}

function tradeActor(trade: TradeRow) {
  return shortHash(trade.taker || trade.maker || trade.txHash || '', 7, 4);
}

function tradeActorFull(trade: TradeRow) {
  return trade.taker || trade.maker || trade.txHash || '--';
}

function formatDateExact(value?: string | null) {
  if (!value) return '--';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

function tradePriceCents(value?: string | number | null) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '--';
  return `${Math.round(numeric * 100)}c`;
}

function polyscanTxUrl(txHash?: string | null) {
  const clean = String(txHash || '').trim();
  if (!clean) return null;
  const normalized = clean.startsWith('0x') ? clean : `0x${clean}`;
  return /^0x[a-fA-F0-9]{64}$/.test(normalized) ? `https://polygonscan.com/tx/${normalized}` : null;
}

function normalizedTxHash(txHash?: string | null) {
  const clean = String(txHash || '').trim();
  if (!clean) return '';
  return clean.startsWith('0x') ? clean : `0x${clean}`;
}

function orderfilledSideLabel(rawSide?: string | null) {
  const side = String(rawSide || '').trim().toUpperCase();
  return side === 'BUY' || side === 'SELL' ? side : 'TRADE';
}

function orderfilledList(
  trades: TradeRow[],
  limit = 8,
  resolveMarketTitle?: (trade: TradeRow) => string | null | undefined,
  options: { compact?: boolean } = {},
) {
  if (!trades.length) return emptyState('Waiting for trade rows.');
  const visibleTrades = trades.slice(0, limit);
  const visibleSides = new Set(visibleTrades.map((trade) => orderfilledSideLabel(trade.side)).filter((side) => side === 'BUY' || side === 'SELL'));
  const showDirectionalSide = visibleSides.size > 1;
  return (
    <div className="wm-orderfilled-list">
      {visibleTrades.map((trade) => {
        const side = showDirectionalSide ? orderfilledSideLabel(trade.side) : 'TRADE';
        const outcome = String(trade.outcome || '--').toUpperCase();
        const tone = side === 'BUY' ? 'positive' : side === 'SELL' ? 'critical' : 'neutral';
        const actor = tradeActor(trade);
        const actorFull = tradeActorFull(trade);
        const marketTitle = resolveMarketTitle?.(trade) || trade.marketTitle || null;
        const txUrl = polyscanTxUrl(trade.txHash);
        const txHash = normalizedTxHash(trade.txHash);
        const rowKey = `${trade.txHash || 'trade'}-${trade.logIndex ?? 'x'}`;
        const notional = tradeNotional(trade);
        const rowContent = (
          <>
            <div className="wm-orderfilled-top">
              <div className="wm-orderfilled-headline">
                <span className={`wm-chip ${tone}`}>{side || 'FLOW'}</span>
                <span className={`wm-orderfilled-outcome ${outcome === 'YES' ? 'yes' : outcome === 'NO' ? 'no' : ''}`}>{outcome}</span>
                <strong>{tradePriceCents(trade.price)}</strong>
                <em>{notional ? `$${formatCompact(notional)}` : '$--'}</em>
              </div>
            </div>
            {!options.compact ? <div className="wm-orderfilled-title">{marketTitle || 'Untitled market'}</div> : null}
            <div className="wm-orderfilled-meta">
              <span>{formatRelative(trade.timestamp || null)}</span>
              <span className="wm-orderfilled-hash">{txHash ? shortHash(txHash, 8, 6) : actor}</span>
              <span className={`wm-orderfilled-link ${txUrl ? 'ready' : 'disabled'}`}>{txUrl ? 'Polyscan' : 'No tx'}</span>
            </div>
            <div className="wm-orderfilled-tooltip" role="tooltip" aria-hidden="true">
              <div className="wm-orderfilled-tooltip-title">{marketTitle || `Market #${trade.marketId || '--'}`}</div>
              <div className="wm-orderfilled-tooltip-row">
                <span>Address</span>
                <strong>{actorFull}</strong>
              </div>
              <div className="wm-orderfilled-tooltip-row">
                <span>Tx</span>
                <strong>{trade.txHash || '--'}</strong>
              </div>
              <div className="wm-orderfilled-tooltip-row">
                <span>Time</span>
                <strong>{formatDateExact(trade.timestamp)}</strong>
              </div>
              {trade.marketId ? (
                <div className="wm-orderfilled-tooltip-row">
                  <span>Market</span>
                  <strong>#{trade.marketId}</strong>
                </div>
              ) : null}
            </div>
          </>
        );
        if (txUrl) {
          return (
            <a
              className={`wm-orderfilled-row ${tone}`}
              href={txUrl}
              key={rowKey}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open OrderFilled transaction ${trade.txHash} on Polyscan`}
            >
              {rowContent}
            </a>
          );
        }
        return (
          <article className={`wm-orderfilled-row ${tone}`} key={rowKey}>
            {rowContent}
          </article>
        );
      })}
    </div>
  );
}

function oracleTone(status?: string | null) {
  const normalized = String(status || '').toLowerCase();
  if (normalized.includes('sett')) return 'positive';
  if (normalized.includes('disput') || normalized.includes('reject')) return 'critical';
  if (normalized.includes('propos')) return 'warning';
  return 'muted';
}

function oracleStageLabel(event: OracleEvent, copy: OracleListCopy = {}) {
  const status = String(event.eventStatus || '').toLowerCase();
  const outcome = String(event.effectiveSettlementOutcome || event.settlementOutcome || '').toUpperCase();
  if (status.includes('settle')) return outcome && outcome !== 'UNKNOWN'
    ? copy.finalizedOutcome?.(outcome) || `Finalized ${outcome}`
    : copy.finalized || 'Finalized';
  if (status.includes('dispute')) return copy.disputed || 'Disputed';
  if (status.includes('propose')) return copy.proposed || 'Proposed';
  if (status.includes('request')) return copy.requested || 'Requested';
  return event.eventStatus || copy.event || 'Oracle event';
}

function oracleOutcomeLabel(event: OracleEvent, copy: OracleListCopy = {}) {
  const outcome = String(event.effectiveSettlementOutcome || event.settlementOutcome || '').toUpperCase();
  if (outcome && outcome !== 'UNKNOWN') return outcome;
  const price = event.settledPrice ?? event.proposedPrice;
  const numeric = Number(price);
  if (Number.isFinite(numeric)) {
    if (numeric >= 0.999 || numeric >= 999999999999999999) return 'YES';
    if (numeric <= 0.001) return 'NO';
    if (Math.abs(numeric - 0.5) < 0.001) return 'CANCELLED';
    return formatPercent(numeric);
  }
  return copy.pending || 'Pending';
}

function oracleActor(event: OracleEvent) {
  return event.proposer || event.disputer || event.requester || event.sourceOracle || event.sourceAdapter || event.txHash || '';
}

function oracleTx(event: OracleEvent) {
  return event.settlementTransaction || event.proposalTransaction || event.txHash || '';
}

function oracleList(events: OracleEvent[], limit = 8, mode: 'feed' | 'timeline' = 'feed', copy: OracleListCopy = {}) {
  if (!events.length) return emptyState(copy.noActivity || 'No oracle activity loaded.', copy.empty);
  const visible = events.slice(0, limit);
  const settledCount = visible.filter((event) => String(event.eventStatus || '').toLowerCase().includes('settle')).length;
  const proposedCount = visible.filter((event) => String(event.eventStatus || '').toLowerCase().includes('propose')).length;
  const boundCount = visible.filter((event) => event.isBound !== false && event.marketId).length;
  return (
    <div className={`wm-oracle-shell ${mode}`}>
      <div className="wm-oracle-summary-strip">
        <span>{copy.finalCount?.(settledCount) || <><strong>{settledCount}</strong> final</>}</span>
        <span>{copy.proposedCount?.(proposedCount) || <><strong>{proposedCount}</strong> proposed</>}</span>
        <span>{copy.boundCount?.(boundCount) || <><strong>{boundCount}</strong> bound</>}</span>
      </div>
      <div className="wm-oracle-list">
      {visible.map((event, index) => {
        const status = String(event.eventStatus || '').toLowerCase();
        const tone = oracleTone(event.eventStatus);
        const stage = oracleStageLabel(event, copy);
        const outcome = oracleOutcomeLabel(event, copy);
        const actor = oracleActor(event);
        const tx = oracleTx(event);
        const lifecycleClass = status.includes('settle') ? 'settle' : status.includes('dispute') ? 'dispute' : status.includes('propose') ? 'propose' : 'request';
        return (
          <article className={`wm-oracle-event-card ${tone} ${lifecycleClass}`} key={`${event.id || index}-${event.blockNumber || index}`}>
            <div className="wm-oracle-event-top">
              <div className="wm-oracle-stage">
                <span className={`wm-oracle-stage-dot ${tone}`} aria-hidden="true" />
                <strong>{stage}</strong>
              </div>
              <span className={`wm-status-pill ${tone}`}>{event.eventStatus || 'event'}</span>
            </div>
            <div className="wm-oracle-market-title">{event.marketTitle || event.marketSlug || copy.unboundEvent || 'Unbound oracle event'}</div>
            <div className="wm-oracle-result-row">
              <span className={`wm-oracle-outcome ${String(outcome).toLowerCase()}`}>{outcome}</span>
              <span>{event.completionStatus || (event.isFinal ? 'SETTLED' : 'PENDING')}</span>
              <span>{event.isBound === false || !event.marketId
                ? copy.unbound || 'UNBOUND'
                : copy.marketNumber?.(event.marketId) || `MKT #${event.marketId}`}</span>
            </div>
            <div className="wm-oracle-event-meta">
              <span>{copy.formatRelative?.(event.eventTime || null) || formatRelative(event.eventTime || null)}</span>
              <span>{copy.formatDate?.(event.eventTime || null) || formatDate(event.eventTime || null)}</span>
            </div>
            <div className="wm-oracle-proof-grid">
              <span>Oracle <strong>{shortHash(actor, 8, 5) || '--'}</strong></span>
              <span>Tx <strong>{shortHash(tx, 8, 5) || '--'}</strong></span>
              <span>QID <strong>{shortHash(event.questionId || event.conditionId || '', 8, 5) || '--'}</strong></span>
            </div>
          </article>
        );
      })}
      </div>
    </div>
  );
}

function contentTone(type?: string | null) {
  const normalized = String(type || '').toLowerCase();
  if (normalized.includes('video')) return 'video';
  if (normalized.includes('report')) return 'report';
  if (normalized.includes('research')) return 'research';
  return 'news';
}

type ContentTag = {
  label: string;
  tone: string;
};

function contentText(item: ContentItem) {
  return `${item.source || ''} ${item.category || ''} ${item.title || ''} ${item.summary || ''} ${item.contentType || ''}`.toLowerCase();
}

function firstMatchingTag(text: string): ContentTag | null {
  const checks: Array<[RegExp, ContentTag]> = [
    [/\b(election|vote|voting|poll|nominee|primary|ballot)\b/, { label: 'ELECTION', tone: 'election' }],
    [/\b(president|senate|congress|parliament|mayor|minister|trump|biden|republican|democrat|party|cabinet)\b/, { label: 'POLITICS', tone: 'politics' }],
    [/\b(nba|nfl|mlb|nhl|soccer|football|ufc|tennis|spurs|thunder|knicks|cavs|cavaliers|sabre|valorant|counter-strike|esports|premier league)\b/, { label: 'SPORTS', tone: 'sports' }],
    [/\b(bitcoin|btc|ethereum|eth|solana|xrp|crypto|dogecoin|token|stablecoin|blockchain)\b/, { label: 'CRYPTO', tone: 'crypto' }],
    [/\b(fed|inflation|cpi|rates?|tariff|gdp|jobs|unemployment|recession|economy|economic|bond|oil|gas|gold|silver|crude)\b/, { label: 'ECONOMIC', tone: 'economic' }],
    [/\b(ai|chip|semiconductor|nvidia|openai|google|microsoft|tesla|robot|cyber|data center|tech)\b/, { label: 'TECH', tone: 'tech' }],
    [/\b(ebola|virus|vaccine|health|hospital|disease|outbreak|infection|pandemic)\b/, { label: 'HEALTH', tone: 'health' }],
    [/\b(war|strike|missile|military|attack|drone|genocide|conflict|invasion|hostage)\b/, { label: 'CONFLICT', tone: 'conflict' }],
    [/\b(iran|israel|gaza|ukraine|russia|china|taiwan|sanction|ceasefire|talks|summit|diplomat|treaty)\b/, { label: 'DIPLOMATIC', tone: 'diplomatic' }],
    [/\b(weather|storm|heat|rain|hurricane|temperature|wildfire|flood)\b/, { label: 'WEATHER', tone: 'weather' }],
    [/\b(earnings|stock|shares|dow|nasdaq|s&p|finance|market|trading)\b/, { label: 'FINANCE', tone: 'finance' }],
    [/\b(movie|music|culture|celebrity|award|streaming)\b/, { label: 'CULTURE', tone: 'culture' }],
  ];
  return checks.find(([pattern]) => pattern.test(text))?.[1] || null;
}

function contentAlertTags(text: string): ContentTag[] {
  if (/\b(breaking|urgent|emergency|critical|killed|death toll|deadly|explosion|invasion|missile|strike|attack|outbreak|genocide|default|crash)\b/.test(text)) {
    return [{ label: 'ALERT', tone: 'alert' }];
  }
  if (/\b(warns?|warning|risk|could|may|threat|probe|lawsuit|charged|ban|delay|volatility|re-escalation)\b/.test(text)) {
    return [{ label: 'CAUTION', tone: 'caution' }];
  }
  if (/\b(ongoing|live|continues?|developing|talks|ceasefire|trial|campaign)\b/.test(text)) {
    return [{ label: 'ONGOING', tone: 'ongoing' }];
  }
  return [];
}

function contentTags(item: ContentItem, tone: string): ContentTag[] {
  const text = contentText(item);
  const tags = contentAlertTags(text);
  const theme = firstMatchingTag(text);
  if (theme) tags.push(theme);
  if (tone !== 'news') tags.push({ label: tone.toUpperCase(), tone });
  if (!tags.length) tags.push({ label: 'NEWS', tone: 'news' });
  return tags.slice(0, 3);
}

function contentPriority(tags: ContentTag[]) {
  if (tags.some((tag) => tag.tone === 'alert')) return 'alert';
  if (tags.some((tag) => tag.tone === 'caution')) return 'caution';
  if (tags.some((tag) => tag.tone === 'ongoing')) return 'ongoing';
  return tags[0]?.tone || 'news';
}

function cleanIntelSummary(value?: string | null) {
  const text = String(value || '').trim();
  if (!text || /^(null|undefined|none)$/i.test(text)) return '';
  return text;
}

function cleanIntelSource(value?: string | null, fallback?: string | null) {
  const raw = String(value || fallback || 'intel').trim();
  if (!raw) return 'intel';
  const withoutProvider = raw
    .replace(/^(tavily|brave search|serpapi|gdelt doc|topic search|market search)\s*:\s*/i, '')
    .replace(/^google news\s*:\s*/i, '');
  const parts = withoutProvider.split(':').map((part) => part.trim()).filter(Boolean);
  return parts[parts.length - 1] || withoutProvider || raw;
}

function contentList(items: ContentItem[], emptyMessage: string, maxItems = 20, copy: ContentListCopy = {}) {
  if (!items.length) return emptyState(emptyMessage, copy.empty);
  return (
    <div className="wm-intel-list">
      {items.slice(0, maxItems).map((item, index) => {
        const tone = contentTone(item.contentType);
        const tags = contentTags(item, tone);
        const priority = contentPriority(tags);
        const summary = cleanIntelSummary(item.summary);
        const source = cleanIntelSource(item.source, item.contentType);
        return (
          <a className={`wm-intel-card ${tone} priority-${priority}`} href={item.url || '#'} target="_blank" rel="noreferrer" key={`${item.url}-${index}`}>
            <span className="wm-intel-rank">{String(index + 1).padStart(2, '0')}</span>
            <div className="wm-intel-topline">
              <div className="wm-intel-meta">
                <span className="wm-intel-dot" aria-hidden="true" />
                <span className="wm-news-source">{source}</span>
                {tags.map((tag) => (
                  <span className={`wm-intel-tag ${tag.tone}`} key={`${item.url || item.title}-${tag.label}`}>{tag.label}</span>
                ))}
              </div>
            </div>
            <div className="wm-news-title">{item.title || copy.untitled || 'Untitled item'}</div>
            {summary ? <p className="wm-intel-summary">{summary}</p> : null}
            <div className="wm-news-meta">
              <span>{copy.formatDate?.(item.publishedAt || null) || formatDate(item.publishedAt || null)}</span>
              <b>{copy.readSource || 'Read source'}</b>
            </div>
          </a>
        );
      })}
    </div>
  );
}



export {
  emptyState,
  orderfilledList,
  oracleList,
  contentList,
};

export function openExternal(url?: string | null) {
  const target = String(url || '').trim();
  if (!target) return;
  window.open(target, '_blank', 'noopener,noreferrer');
}
