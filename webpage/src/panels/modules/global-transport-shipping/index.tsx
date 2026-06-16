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

function clamp(value: number, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
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

function sourceCount(items: RuntimeGlobalTransportShippingItem[], source: string) {
  return items.filter((item) => String(item.evidenceType || '').toUpperCase().includes(source)).length;
}

function TransportNetwork({ items, payload }: { items: RuntimeGlobalTransportShippingItem[]; payload?: RuntimeGlobalTransportShippingPayload | null }) {
  const routes = numeric(payload?.summary?.routes);
  const ais = items.find((item) => String(item.evidenceType || '').toUpperCase().includes('AIS'));
  const aisMessages = numeric(ais?.metric);
  const routeIntensity = clamp(routes / 800);
  const aisIntensity = clamp(aisMessages * 8);
  return (
    <div className="wm-transport-network-card">
      <svg className="wm-transport-map" viewBox="0 0 320 118" role="img" aria-label="Transport network intensity">
        <defs>
          <linearGradient id="wmTransportRoute" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.18" />
            <stop offset="55%" stopColor="#38bdf8" stopOpacity="0.72" />
            <stop offset="100%" stopColor="#4ade80" stopOpacity="0.18" />
          </linearGradient>
        </defs>
        <path className="wm-transport-gridline" d="M8 34 C80 18 112 48 160 30 S238 22 312 46" />
        <path className="wm-transport-gridline" d="M14 82 C74 66 104 98 156 76 S250 62 306 88" />
        <path className="wm-transport-route main" d="M30 74 C88 18 156 18 292 38" style={{ '--route': `${routeIntensity}%` } as any} />
        <path className="wm-transport-route alt" d="M24 42 C90 95 178 98 302 68" />
        <path className="wm-transport-route alt two" d="M72 94 C124 42 182 44 250 18" />
        {[
          [34, 72, 'ATL'],
          [86, 34, 'LHR'],
          [146, 56, 'GT'],
          [218, 35, 'AIS'],
          [286, 66, 'PEK'],
        ].map(([x, y, label], index) => (
          <g key={String(label)} className={index === 3 ? 'wm-transport-node ais' : 'wm-transport-node'}>
            <circle cx={Number(x)} cy={Number(y)} r={index === 3 ? 10 : 7} />
            <text x={Number(x)} y={Number(y) + 21}>{label}</text>
          </g>
        ))}
      </svg>
      <div className="wm-transport-network-stats">
        <span><em>AIR ROUTES</em><strong>{formatCompact(payload?.summary?.routes)}</strong></span>
        <span><em>GTFS FEEDS</em><strong>{formatCompact(payload?.summary?.transitFeeds)}</strong></span>
        <span><em>AIS MSG</em><strong>{formatCompact(aisMessages)}</strong></span>
      </div>
      <div className="wm-transport-signal" style={{ '--ais': `${aisIntensity}%` } as any}>
        <b>{payload?.summary?.topHub || '--'}</b>
        <span>{sourceCount(items, 'OPENFLIGHTS')} air / {sourceCount(items, 'TRANSITLAND')} gtfs / {sourceCount(items, 'AIS')} ais</span>
      </div>
    </div>
  );
}

function TransportRow({ item }: { item: RuntimeGlobalTransportShippingItem }) {
  const severity = severityClass(item);
  const tags = (item.tags || []).slice(0, 2);
  const width = clamp(numeric(item.metric) / 120);
  return (
    <button type="button" className={`wm-transport-strip ${severity} ${glyph(item).toLowerCase()}`} onClick={() => openSource(item.sourceUrl)}>
      <span className="wm-transport-strip-kind">{glyph(item)}</span>
      <span className="wm-transport-strip-main">
        <span className="wm-evidence-meta">
          <b>{item.entity || 'Transport'}</b>
          <em>{item.evidenceType || item.country || 'SOURCE'}</em>
          <i className={severity}>{severity.toUpperCase()}</i>
          {tags.map((tag) => <i key={tag}>{tag.toUpperCase()}</i>)}
        </span>
        <strong>{item.title || 'Transport evidence source'}</strong>
        <small>{item.summary || `${item.country || 'Global'} transport evidence`}</small>
      </span>
      <span className="wm-transport-strip-metric">
        <i style={{ '--width': `${width}%` } as any} />
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
      <TransportNetwork items={items} payload={payload} />
      <div className="wm-transport-strips">
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
  size: 'wide',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 900000,
  fetchData: () => fetchRuntimeGlobalTransportShipping(14),
});
