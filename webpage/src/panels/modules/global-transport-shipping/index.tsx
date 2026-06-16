import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeGlobalTransportShipping } from '@/services/api';
import type { RuntimeGlobalTransportShippingItem, RuntimeGlobalTransportShippingPayload } from '@/types';
import { formatCompact, formatRelative } from '../../shared/formatters';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '../helpers';

type TransportTab = 'ops' | 'flights' | 'airlines' | 'track' | 'news';
type AviationPayload = NonNullable<RuntimeGlobalTransportShippingPayload['aviation']>;
type AviationRoute = NonNullable<AviationPayload['routes']>[number];

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

function compactUnknown(value: unknown) {
  if (typeof value === 'number' || typeof value === 'string' || value === null || value === undefined) return formatCompact(value);
  return formatCompact(Number(value) || 0);
}

function glyph(item: RuntimeGlobalTransportShippingItem) {
  const type = String(item.evidenceType || item.topic || '').toUpperCase();
  if (type.includes('AIS')) return 'AIS';
  if (type.includes('TRANSIT') || type.includes('GTFS')) return 'GT';
  return 'AIR';
}

function openSource(url?: string | null) {
  const target = String(url || '').trim();
  if (target) window.open(target, '_blank', 'noopener,noreferrer');
}

function statusClass(status?: unknown) {
  const text = String(status || '').toLowerCase();
  if (text.includes('alert')) return 'alert';
  if (text.includes('watch') || text.includes('minor')) return 'watch';
  return 'normal';
}

function statusLabel(status?: unknown) {
  const text = String(status || '').trim();
  if (!text) return 'NORMAL';
  return text.replace(/[_-]+/g, ' ').toUpperCase();
}

function aviationRoutes(payload?: RuntimeGlobalTransportShippingPayload | null) {
  return payload?.aviation?.routes || [];
}

function aviationOps(payload?: RuntimeGlobalTransportShippingPayload | null) {
  return payload?.aviation?.ops || [];
}

function aviationAirlines(payload?: RuntimeGlobalTransportShippingPayload | null) {
  return payload?.aviation?.airlines || [];
}

function aviationNews(payload?: RuntimeGlobalTransportShippingPayload | null) {
  return payload?.aviation?.news || [];
}

function AviationHero({ payload }: { payload?: RuntimeGlobalTransportShippingPayload | null }) {
  const routes = numeric(payload?.summary?.routes);
  const hubs = payload?.aviation?.hubs || [];
  const routeRows = aviationRoutes(payload);
  const topHub = hubs[0];
  const routeRisk = Math.round(Math.max(...routeRows.map((route) => numeric(route.riskScore)), 0));
  const traffic = Math.round(Math.max(...routeRows.map((route) => numeric(route.trafficScore)), 0));
  return (
    <div className="wm-aviation-hero">
      <div className="wm-aviation-radar" aria-hidden="true">
        <span className="wm-aviation-radar-sweep" />
        <span className="wm-aviation-runway" />
        <span className="wm-aviation-plane-dot one" />
        <span className="wm-aviation-plane-dot two" />
        <span className="wm-aviation-plane-dot three" />
      </div>
      <svg className="wm-aviation-mini-routes" viewBox="0 0 240 92" role="img" aria-label="Aviation corridor preview">
        <defs>
          <linearGradient id="wmAviationRoute" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.1" />
            <stop offset="50%" stopColor="#67e8f9" stopOpacity="0.86" />
            <stop offset="100%" stopColor="#facc15" stopOpacity="0.72" />
          </linearGradient>
        </defs>
        <path className="wm-aviation-latline" d="M10 42 C62 30 88 46 122 37 S184 23 230 44" />
        <path className="wm-aviation-latline" d="M12 70 C64 58 96 77 128 64 S188 54 228 72" />
        <path className="wm-aviation-route-a" d="M22 68 C74 12 138 12 220 35" />
        <path className="wm-aviation-route-b" d="M20 34 C78 80 146 80 224 56" />
        <path className="wm-aviation-route-c" d="M58 78 C102 38 152 36 194 18" />
        {[
          [28, 66, 'ATL'],
          [88, 31, 'LHR'],
          [140, 54, 'DXB'],
          [195, 25, 'SIN'],
          [216, 55, 'HKG'],
        ].map(([x, y, label], index) => (
          <g key={String(label)} className={index === 1 ? 'wm-aviation-node major' : 'wm-aviation-node'}>
            <circle cx={Number(x)} cy={Number(y)} r={index === 1 ? 6 : 4.5} />
            <text x={Number(x)} y={Number(y) + 21}>{label}</text>
          </g>
        ))}
      </svg>
      <div className="wm-aviation-hero-stats">
        <span><em>TOP HUB</em><strong>{topHub?.code || payload?.summary?.topHub || '--'}</strong><small>{topHub?.city || 'seeded'}</small></span>
        <span><em>ROUTES</em><strong>{formatCompact(routes)}</strong><small>OpenFlights</small></span>
        <span><em>RISK</em><strong>{routeRisk}</strong><small>{traffic} traffic</small></span>
      </div>
    </div>
  );
}

function OpsRow({ row }: { row: Record<string, unknown> }) {
  const status = statusClass(row.status);
  return (
    <div className="wm-aviation-intel-row">
      <b>{String(row.code || '--')}</b>
      <span><strong>{String(row.name || 'Airport')}</strong><em>{String(row.city || 'Global')}</em></span>
      <i className={status}>{statusLabel(row.status)}</i>
      <small>{compactUnknown(row.routeCount)}</small>
    </div>
  );
}

function FlightRow({ route }: { route: AviationRoute }) {
  const risk = numeric(route.riskScore);
  const status = statusClass(route.status);
  return (
    <div className="wm-aviation-intel-row flight">
      <b>{route.fromCode || '--'}</b>
      <span><strong>{route.fromCode} &gt; {route.toCode}</strong><em>{route.corridor || route.airline || 'air corridor'}</em></span>
      <i className={status}>{risk || statusLabel(route.status)}</i>
      <small>{formatCompact(route.trafficScore)}</small>
    </div>
  );
}

function AirlineRow({ row }: { row: { name?: string | null; routeCount?: number | string | null } }) {
  return (
    <div className="wm-aviation-intel-row airline">
      <b>AL</b>
      <span><strong>{row.name || 'Airline'}</strong><em>OpenFlights route coverage</em></span>
      <i className="normal">NORMAL</i>
      <small>{formatCompact(row.routeCount)}</small>
    </div>
  );
}

function TrackRow({ item }: { item: RuntimeGlobalTransportShippingItem }) {
  const status = severityClass(item);
  return (
    <button type="button" className="wm-aviation-intel-row source" onClick={() => openSource(item.sourceUrl)}>
      <b>{glyph(item)}</b>
      <span><strong>{item.entity || item.evidenceType}</strong><em>{item.summary || item.title}</em></span>
      <i className={status}>{status.toUpperCase()}</i>
      <small>{formatCompact(item.metric)}</small>
    </button>
  );
}

function NewsRow({ row }: { row: Record<string, unknown> }) {
  const status = statusClass(row.status);
  return (
    <div className="wm-aviation-intel-row news">
      <b>NW</b>
      <span><strong>{String(row.title || 'Aviation signal')}</strong><em>{String(row.corridor || row.source || 'route intelligence')}</em></span>
      <i className={status}>{compactUnknown(row.riskScore)}</i>
      <small>{String(row.source || 'seed')}</small>
    </div>
  );
}

function GlobalTransportShippingPanel({ payload }: { payload?: RuntimeGlobalTransportShippingPayload | null }) {
  const [showHelp, setShowHelp] = useState(false);
  const [tab, setTab] = useState<TransportTab>('ops');
  const items = payload?.items || [];
  const tabs: Array<{ id: TransportTab; label: string; count: number }> = [
    { id: 'ops', label: 'Ops', count: aviationOps(payload).length },
    { id: 'flights', label: 'Flights', count: aviationRoutes(payload).length },
    { id: 'airlines', label: 'Airlines', count: aviationAirlines(payload).length },
    { id: 'track', label: 'Track', count: items.length },
    { id: 'news', label: 'News', count: aviationNews(payload).length },
  ];
  const rows = useMemo(() => {
    if (tab === 'ops') return aviationOps(payload).slice(0, 8).map((row, index) => <OpsRow key={`${row.code || index}`} row={row} />);
    if (tab === 'flights') return aviationRoutes(payload).slice(0, 8).map((route, index) => <FlightRow key={`${route.id || index}`} route={route} />);
    if (tab === 'airlines') return aviationAirlines(payload).slice(0, 8).map((row, index) => <AirlineRow key={`${row.name || index}`} row={row} />);
    if (tab === 'news') return aviationNews(payload).slice(0, 8).map((row, index) => <NewsRow key={`${row.title || index}`} row={row} />);
    return items.slice(0, 8).map((item) => <TrackRow key={item.id || `${item.evidenceType}-${item.entity}-${item.title}`} item={item} />);
  }, [items, payload, tab]);
  return (
    <Panel
      title="AIRLINE INTEL"
      titleControls={<button type="button" className="wm-panel-help-button" aria-label="Explain transport ops" aria-expanded={showHelp} onClick={() => setShowHelp((value) => !value)}>?</button>}
      controls={<button type="button" className="wm-evidence-sort-button" aria-label="Refresh aviation source" onClick={() => openSource(payload?.sourceUrl)}>AIR MAP</button>}
      badge={statusBadge(payload)}
      status={payload?.status === 'ok' ? 'live' : 'muted'}
      count={items.length}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>Airline Intel</strong>
          <p>Seeded aviation corridor graph from OpenFlights, with route-flow animation on the 2D map and supporting transport source status.</p>
        </div>
      ) : null}
      className="wm-market-panel wm-evidence-panel wm-global-transport-panel"
      dataPanelId="global-transport-shipping"
    >
      <AviationHero payload={payload} />
      <div className="wm-aviation-tabs" role="tablist" aria-label="Airline intel views">
        {tabs.map((item) => (
          <button key={item.id} type="button" className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}>
            {item.label}<span>{item.count}</span>
          </button>
        ))}
      </div>
      <div className="wm-aviation-intel-list">
        {rows.length ? rows : (
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
