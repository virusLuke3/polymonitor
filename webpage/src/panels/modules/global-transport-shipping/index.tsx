import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeGlobalTransportShipping } from '@/services/api';
import type { RuntimeGlobalTransportShippingItem, RuntimeGlobalTransportShippingPayload } from '@/types';
import { formatCompact, formatRelative } from '../../shared/formatters';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '../helpers';

type TransportTab = 'ops' | 'flights' | 'airlines' | 'track' | 'news';
type AviationIconKind = 'airport' | 'flight' | 'airline' | 'track' | 'news';
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

function AviationIcon({ kind }: { kind: AviationIconKind }) {
  const paths: Record<AviationIconKind, string> = {
    airport: 'M21 16.2 13.9 14.4 10.4 21l-2-.6 1.1-6.2-5-1.8-2.2 2.1-1.3-.9 2.8-4.4 5.7.8 4.6-8.3c.5-.9 1.5-1.3 2.4-1 .9.4 1.3 1.4.9 2.4l-3.1 7 6.1.6.6 1.5Z',
    flight: 'M21 16.2 13.9 14.4 10.4 21l-2-.6 1.1-6.2-5-1.8-2.2 2.1-1.3-.9 2.8-4.4 5.7.8 4.6-8.3c.5-.9 1.5-1.3 2.4-1 .9.4 1.3 1.4.9 2.4l-3.1 7 6.1.6.6 1.5Z',
    airline: 'M4 15.8 20 7l.7 1.5-16 8.8L4 15.8Zm3.4 2.5 9.6-3.1.5 1.6-8.7 4.2-1.4-2.7Zm-1-7.4 9.1-4.4.7 1.5-8.8 5.1-1-2.2Z',
    track: 'M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18Zm0 2a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm0 2.6a4.4 4.4 0 0 1 4.4 4.4h-2a2.4 2.4 0 0 0-2.4-2.4v-2Zm0 4.4 5.6-5.6 1.4 1.4-6.2 6.2H8v-2h4Z',
    news: 'M5 4h14a1 1 0 0 1 1 1v14l-3-2H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm2 4v2h10V8H7Zm0 4v2h7v-2H7Z',
  };
  return (
    <span className={`wm-aviation-icon ${kind}`} aria-hidden="true">
      <svg viewBox="0 0 24 24" focusable="false">
        <path d={paths[kind]} />
      </svg>
    </span>
  );
}

function OpsRow({ row }: { row: Record<string, unknown> }) {
  const status = statusClass(row.status);
  return (
    <div className="wm-aviation-intel-row">
      <span className="wm-aviation-code"><AviationIcon kind="airport" /><b>{String(row.code || '--')}</b></span>
      <span><strong>{String(row.name || 'Airport')}</strong><em>{String(row.city || 'Global')}</em></span>
      <i className={status}>{statusLabel(row.status)}</i>
      <small>--</small>
    </div>
  );
}

function FlightRow({ route }: { route: AviationRoute }) {
  const risk = numeric(route.riskScore);
  const status = statusClass(route.status);
  return (
    <div className="wm-aviation-intel-row flight">
      <span className="wm-aviation-code"><AviationIcon kind="flight" /><b>{route.fromCode || '--'}</b></span>
      <span><strong>{route.fromCode} &gt; {route.toCode}</strong><em>{route.corridor || route.airline || 'air corridor'}</em></span>
      <i className={status}>{risk || statusLabel(route.status)}</i>
      <small>{formatCompact(route.trafficScore)}</small>
    </div>
  );
}

function AirlineRow({ row }: { row: { name?: string | null; routeCount?: number | string | null } }) {
  return (
    <div className="wm-aviation-intel-row airline">
      <span className="wm-aviation-code"><AviationIcon kind="airline" /><b>AL</b></span>
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
      <span className="wm-aviation-code"><AviationIcon kind="track" /><b>{glyph(item)}</b></span>
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
      <span className="wm-aviation-code"><AviationIcon kind="news" /><b>NW</b></span>
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
  const tabs: Array<{ id: TransportTab; label: string; count: number; icon: AviationIconKind }> = [
    { id: 'ops', label: 'Ops', count: aviationOps(payload).length, icon: 'airport' },
    { id: 'flights', label: 'Flights', count: aviationRoutes(payload).length, icon: 'flight' },
    { id: 'airlines', label: 'Airlines', count: aviationAirlines(payload).length, icon: 'airline' },
    { id: 'track', label: 'Track', count: items.length, icon: 'track' },
    { id: 'news', label: 'News', count: aviationNews(payload).length, icon: 'news' },
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
      title="航空公司情报"
      titleControls={<button type="button" className="wm-panel-help-button" aria-label="Explain transport ops" aria-expanded={showHelp} onClick={() => setShowHelp((value) => !value)}>?</button>}
      controls={<button type="button" className="wm-evidence-sort-button wm-aviation-refresh-button" aria-label="Open aviation source" onClick={() => openSource(payload?.sourceUrl)}>↻</button>}
      badge={statusBadge(payload)}
      status={payload?.status === 'ok' ? 'live' : 'muted'}
      count={items.length}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>航空公司情报</strong>
          <p>Seeded aviation corridor graph from OpenFlights, with route-flow animation on the 2D map and supporting transport source status.</p>
        </div>
      ) : null}
      className="wm-market-panel wm-evidence-panel wm-global-transport-panel"
      dataPanelId="global-transport-shipping"
    >
      <div className="wm-aviation-tabs" role="tablist" aria-label="Airline intel views">
        {tabs.map((item) => (
          <button key={item.id} type="button" className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}>
            <AviationIcon kind={item.icon} /><strong>{item.label}</strong><span>{item.count}</span>
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
