import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeGlobalTransportShipping } from '@/services/api';
import type { RuntimeGlobalTransportShippingItem, RuntimeGlobalTransportShippingPayload } from '@/types';
import { formatCompact, formatRelative } from '../../shared/formatters';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '../helpers';

type SortMode = 'impact' | 'latest' | 'source';

function statusBadge(payload?: RuntimeGlobalTransportShippingPayload | null) {
  const mode = String(payload?.cacheMode || '').toLowerCase();
  const status = String(payload?.status || '').toLowerCase();
  if (mode.includes('stale') || mode.includes('preserved')) return 'STALE';
  if (mode.includes('seed')) return status === 'degraded' ? 'PARTIAL' : 'SEED';
  if (status === 'empty' || status === 'warming') return 'WARM';
  return status === 'degraded' ? 'PARTIAL' : 'LIVE';
}

function severityClass(item: RuntimeGlobalTransportShippingItem) {
  const severity = String(item.severity || '').toLowerCase();
  if (severity === 'alert') return 'alert';
  if (severity === 'watch') return 'watch';
  return 'normal';
}

function numeric(value?: number | string | null) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function percent(value?: number | string | null) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '--';
  return `${Math.round(parsed * 100)}%`;
}

function glyph(item: RuntimeGlobalTransportShippingItem) {
  const type = String(item.evidenceType || item.topic || '').toUpperCase();
  if (type.includes('AIS')) return 'AIS';
  if (type.includes('TRANSIT') || type.includes('GTFS')) return 'GT';
  return 'AIR';
}

function marketCount(item: RuntimeGlobalTransportShippingItem) {
  return (item.markets || []).length || (item.relatedPolymarketMarketIds || []).length || 0;
}

function sortItems(items: RuntimeGlobalTransportShippingItem[], mode: SortMode) {
  const rows = [...items];
  if (mode === 'latest') {
    rows.sort((a, b) => String(b.eventTime || '').localeCompare(String(a.eventTime || '')));
    return rows;
  }
  if (mode === 'source') {
    rows.sort((a, b) => String(a.evidenceType || '').localeCompare(String(b.evidenceType || '')) || numeric(b.metric) - numeric(a.metric));
    return rows;
  }
  rows.sort((a, b) => numeric(b.metric) - numeric(a.metric) || marketCount(b) - marketCount(a));
  return rows;
}

function nextMode(mode: SortMode): SortMode {
  if (mode === 'impact') return 'latest';
  if (mode === 'latest') return 'source';
  return 'impact';
}

function modeLabel(mode: SortMode) {
  if (mode === 'latest') return 'Latest';
  if (mode === 'source') return 'Source';
  return 'Impact';
}

function openSource(url?: string | null) {
  const target = String(url || '').trim();
  if (target) window.open(target, '_blank', 'noopener,noreferrer');
}

function TransportRow({ item }: { item: RuntimeGlobalTransportShippingItem }) {
  const severity = severityClass(item);
  const tags = (item.tags || []).slice(0, 2);
  return (
    <button type="button" className={`wm-evidence-row wm-transport-row ${severity}`} onClick={() => openSource(item.sourceUrl)}>
      <span className="wm-evidence-glyph">{glyph(item)}</span>
      <span className="wm-evidence-main">
        <span className="wm-evidence-meta">
          <b>{item.entity || 'Transport'}</b>
          <em>{item.evidenceType || item.country || 'SOURCE'}</em>
          <i className={severity}>{severity.toUpperCase()}</i>
          {tags.map((tag) => <i key={tag}>{tag.toUpperCase()}</i>)}
        </span>
        <strong>{item.title || 'Transport evidence source'}</strong>
        <small>{item.summary || `${item.country || 'Global'} transport evidence`}</small>
      </span>
      <span className="wm-evidence-value">
        <strong>{formatCompact(item.metric)}</strong>
        <em>{item.metricLabel || 'SIGNAL'}</em>
        <small>{percent(item.confidence)} conf</small>
      </span>
    </button>
  );
}

function GlobalTransportShippingPanel({ payload }: { payload?: RuntimeGlobalTransportShippingPayload | null }) {
  const [showHelp, setShowHelp] = useState(false);
  const [sortMode, setSortMode] = useState<SortMode>('impact');
  const items = useMemo(() => sortItems(payload?.items || [], sortMode), [payload?.items, sortMode]);
  return (
    <Panel
      title="TRANSPORT OPS"
      titleControls={<button type="button" className="wm-panel-help-button" aria-label="Explain transport ops" aria-expanded={showHelp} onClick={() => setShowHelp((value) => !value)}>?</button>}
      controls={<button type="button" className="wm-evidence-sort-button" aria-label="Change transport ops sort" onClick={() => setSortMode((value) => nextMode(value))}>{modeLabel(sortMode)}</button>}
      badge={statusBadge(payload)}
      status={payload?.status === 'ok' ? 'live' : 'muted'}
      count={items.length}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>Global Transport / Shipping</strong>
          <p>OpenFlights route topology, Transitland mobility feed coverage, and AISStream websocket readiness as structured transport evidence.</p>
        </div>
      ) : null}
      className="wm-market-panel wm-evidence-panel wm-global-transport-panel"
      dataPanelId="global-transport-shipping"
    >
      <div className="wm-evidence-summary">
        <span><em>HUB</em><strong>{payload?.summary?.topHub || '--'}</strong></span>
        <span><em>ROUTES</em><strong>{formatCompact(payload?.summary?.routes)}</strong></span>
        <span><em>GTFS</em><strong>{formatCompact(payload?.summary?.transitFeeds)}</strong></span>
      </div>
      <div className="wm-evidence-list">
        {items.length ? items.map((item) => <TransportRow key={item.id || `${item.evidenceType}-${item.entity}-${item.title}`} item={item} />) : (
          <div className="wm-registry-empty"><strong>Transport evidence seed warming</strong><span>{formatRelative(payload?.generatedAt)}</span></div>
        )}
      </div>
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'global-transport-shipping': {
    render: (ctx) => <GlobalTransportShippingPanel payload={ctx.runtimeData['global-transport-shipping'] as RuntimeGlobalTransportShippingPayload | undefined} />,
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'global-transport-shipping',
  title: 'Global Transport / Shipping',
  eyebrow: 'transport',
  description: 'OpenFlights, Transitland Atlas, and AISStream transport evidence linked to markets.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 900000,
  fetchData: () => fetchRuntimeGlobalTransportShipping(14),
});
