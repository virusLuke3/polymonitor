import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeBreakingEventRadar } from '@/services/api';
import type { RuntimeBreakingEventRadarItem, RuntimeBreakingEventRadarPayload } from '@/types';
import { formatRelative } from '../../shared/formatters';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '../helpers';

type SortMode = 'velocity' | 'latest' | 'markets';

function statusBadge(payload?: RuntimeBreakingEventRadarPayload | null) {
  const mode = String(payload?.cacheMode || '').toLowerCase();
  const status = String(payload?.status || '').toLowerCase();
  if (mode.includes('stale') || mode.includes('preserved')) return 'STALE';
  if (mode.includes('seed')) return status === 'degraded' ? 'PARTIAL' : 'SEED';
  if (status === 'empty' || status === 'warming') return 'WARM';
  return status === 'degraded' ? 'PARTIAL' : 'LIVE';
}

function severityClass(item: RuntimeBreakingEventRadarItem) {
  const severity = String(item.severity || '').toLowerCase();
  if (severity === 'alert') return 'alert';
  if (severity === 'watch') return 'watch';
  return 'normal';
}

function score(value?: number | string | null) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? String(Math.round(numeric)) : '--';
}

function percent(value?: number | string | null) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${Math.round(numeric)}%` : '--';
}

function marketCount(item: RuntimeBreakingEventRadarItem) {
  return (item.markets || []).length || (item.relatedPolymarketMarketIds || []).length || 0;
}

function sortItems(items: RuntimeBreakingEventRadarItem[], mode: SortMode) {
  const rows = [...items];
  if (mode === 'latest') {
    rows.sort((a, b) => String(b.eventTime || '').localeCompare(String(a.eventTime || '')));
    return rows;
  }
  if (mode === 'markets') {
    rows.sort((a, b) => marketCount(b) - marketCount(a) || Number(b.velocityScore || 0) - Number(a.velocityScore || 0));
    return rows;
  }
  rows.sort((a, b) => Number(b.velocityScore || 0) - Number(a.velocityScore || 0) || String(b.eventTime || '').localeCompare(String(a.eventTime || '')));
  return rows;
}

function nextMode(mode: SortMode): SortMode {
  if (mode === 'velocity') return 'latest';
  if (mode === 'latest') return 'markets';
  return 'velocity';
}

function modeLabel(mode: SortMode) {
  if (mode === 'latest') return 'Latest';
  if (mode === 'markets') return 'PMKT';
  return 'Heat';
}

function openSource(url?: string | null) {
  const target = String(url || '').trim();
  if (target) window.open(target, '_blank', 'noopener,noreferrer');
}

function RadarRow({ item }: { item: RuntimeBreakingEventRadarItem }) {
  const severity = severityClass(item);
  const tags = (item.tags || []).slice(0, 2);
  return (
    <button type="button" className={`wm-evidence-row wm-breaking-row ${severity}`} onClick={() => openSource(item.sourceUrl)}>
      <span className="wm-evidence-glyph">{severity === 'alert' ? '!' : severity === 'watch' ? '?' : 'i'}</span>
      <span className="wm-evidence-main">
        <span className="wm-evidence-meta">
          <b>{item.entity || 'Event'}</b>
          <em>{item.source || item.country || 'GDELT'}</em>
          <i className={severity}>{severity.toUpperCase()}</i>
          {tags.map((tag) => <i key={tag}>{tag.toUpperCase()}</i>)}
        </span>
        <strong>{item.title || 'Breaking source warming'}</strong>
        <small>{item.summary || `${item.country || 'Global'} evidence stream`}</small>
      </span>
      <span className="wm-evidence-value">
        <strong>{score(item.velocityScore)}</strong>
        <em>{marketCount(item)} PMKT</em>
        <small>{percent(item.confidence)} conf</small>
      </span>
    </button>
  );
}

function BreakingEventRadarPanel({ payload }: { payload?: RuntimeBreakingEventRadarPayload | null }) {
  const [showHelp, setShowHelp] = useState(false);
  const [sortMode, setSortMode] = useState<SortMode>('velocity');
  const items = useMemo(() => sortItems(payload?.items || [], sortMode), [payload?.items, sortMode]);
  return (
    <Panel
      title="BREAKING RADAR"
      titleControls={<button type="button" className="wm-panel-help-button" aria-label="Explain breaking radar" aria-expanded={showHelp} onClick={() => setShowHelp((value) => !value)}>?</button>}
      controls={<button type="button" className="wm-evidence-sort-button" aria-label="Change breaking radar sort" onClick={() => setSortMode((value) => nextMode(value))}>{modeLabel(sortMode)}</button>}
      badge={statusBadge(payload)}
      status={payload?.status === 'ok' ? 'live' : 'muted'}
      count={items.length}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>Breaking Event Radar</strong>
          <p>Seeded GDELT headlines plus Wikimedia pageview proxies, ranked by velocity and linked to related Polymarket markets when available.</p>
        </div>
      ) : null}
      className="wm-market-panel wm-evidence-panel wm-breaking-radar-panel"
      dataPanelId="breaking-event-radar"
    >
      <div className="wm-evidence-summary">
        <span><em>TOP</em><strong>{payload?.summary?.topEntity || '--'}</strong></span>
        <span><em>HEAT</em><strong>{score(payload?.summary?.topVelocity)}</strong></span>
        <span><em>ALERTS</em><strong>{score(payload?.summary?.alerts)}</strong></span>
      </div>
      <div className="wm-evidence-list">
        {items.length ? items.map((item) => <RadarRow key={item.id || `${item.entity}-${item.title}`} item={item} />) : (
          <div className="wm-registry-empty"><strong>Breaking evidence seed warming</strong><span>{formatRelative(payload?.generatedAt)}</span></div>
        )}
      </div>
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'breaking-event-radar': {
    render: (ctx) => <BreakingEventRadarPanel payload={ctx.runtimeData['breaking-event-radar'] as RuntimeBreakingEventRadarPayload | undefined} />,
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'breaking-event-radar',
  title: 'Breaking Event Radar',
  eyebrow: 'evidence',
  description: 'GDELT and Wikimedia evidence velocity linked to Polymarket topics.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 300000,
  fetchData: () => fetchRuntimeBreakingEventRadar(12),
});
