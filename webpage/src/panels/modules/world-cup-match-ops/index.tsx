import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeWorldCupMatchOps } from '@/services/api';
import type { RuntimeWorldCupMatchOpsItem, RuntimeWorldCupMatchOpsPayload } from '@/types';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '../helpers';

type SortMode = 'next' | 'weather' | 'markets';

function statusBadge(payload?: RuntimeWorldCupMatchOpsPayload | null) {
  const mode = String(payload?.cacheMode || '').toLowerCase();
  const status = String(payload?.status || '').toLowerCase();
  if (mode.includes('stale') || mode.includes('preserved')) return 'STALE';
  if (mode.includes('seed')) return status === 'degraded' ? 'PARTIAL' : 'SEED';
  if (status === 'empty' || status === 'warming') return 'WARM';
  return status === 'degraded' ? 'PARTIAL' : 'LIVE';
}

function dateLabel(value?: string | null) {
  if (!value) return '--';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  }).format(date);
}

function minutesLabel(value?: number | string | null) {
  const minutes = Number(value);
  if (!Number.isFinite(minutes)) return '--';
  if (minutes < 0) return 'LIVE/PAST';
  if (minutes < 90) return `${Math.max(0, Math.round(minutes))}m`;
  if (minutes < 60 * 48) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / 1440)}d`;
}

function score(value?: number | string | null) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? String(Math.round(numeric)) : '--';
}

function riskClass(item: RuntimeWorldCupMatchOpsItem) {
  const level = String(item.weatherRisk?.level || '').toLowerCase();
  if (level === 'high') return 'alert';
  if (level === 'watch') return 'watch';
  return 'normal';
}

function marketCount(item: RuntimeWorldCupMatchOpsItem) {
  return (item.markets || []).length || (item.relatedPolymarketMarketIds || []).length || 0;
}

function sortItems(items: RuntimeWorldCupMatchOpsItem[], mode: SortMode) {
  const rows = [...items];
  if (mode === 'weather') {
    rows.sort((a, b) => Number(b.weatherRisk?.score || 0) - Number(a.weatherRisk?.score || 0));
    return rows;
  }
  if (mode === 'markets') {
    rows.sort((a, b) => marketCount(b) - marketCount(a) || String(a.kickoffUtc || '').localeCompare(String(b.kickoffUtc || '')));
    return rows;
  }
  rows.sort((a, b) => Number(a.minutesUntilKickoff ?? 999999) - Number(b.minutesUntilKickoff ?? 999999));
  return rows;
}

function nextMode(mode: SortMode): SortMode {
  if (mode === 'next') return 'weather';
  if (mode === 'weather') return 'markets';
  return 'next';
}

function modeLabel(mode: SortMode) {
  if (mode === 'weather') return 'Weather';
  if (mode === 'markets') return 'PMKT';
  return 'Next';
}

function MatchRow({ item }: { item: RuntimeWorldCupMatchOpsItem }) {
  const risk = riskClass(item);
  return (
    <article className={`wm-evidence-row wm-match-ops-row ${risk}`}>
      <span className="wm-evidence-glyph">WC</span>
      <span className="wm-evidence-main">
        <span className="wm-evidence-meta">
          <b>{dateLabel(item.kickoffUtc)}</b>
          <em>{item.city || 'Venue TBD'}</em>
          <i className={risk}>{item.weatherRisk?.label || 'WEATHER'}</i>
          {item.marketLinked ? <i>PMKT</i> : null}
        </span>
        <strong>{item.homeTeam || 'TBD'} <span>vs</span> {item.awayTeam || 'TBD'}</strong>
        <small>{item.venue || item.round || 'World Cup 2026'} / {String(item.stage || 'group').toUpperCase()}</small>
      </span>
      <span className="wm-evidence-value">
        <strong>{minutesLabel(item.minutesUntilKickoff)}</strong>
        <em>{score(item.weatherRisk?.score)} risk</em>
        <small>{marketCount(item)} PMKT</small>
      </span>
    </article>
  );
}

function WorldCupMatchOpsPanel({ payload }: { payload?: RuntimeWorldCupMatchOpsPayload | null }) {
  const [showHelp, setShowHelp] = useState(false);
  const [sortMode, setSortMode] = useState<SortMode>('next');
  const items = useMemo(() => sortItems(payload?.items || [], sortMode), [payload?.items, sortMode]);
  return (
    <Panel
      title="MATCH OPS"
      titleControls={<button type="button" className="wm-panel-help-button" aria-label="Explain match ops sources" aria-expanded={showHelp} onClick={() => setShowHelp((value) => !value)}>?</button>}
      controls={<button type="button" className="wm-evidence-sort-button" aria-label="Change match ops sort" onClick={() => setSortMode((value) => nextMode(value))}>{modeLabel(sortMode)}</button>}
      badge={statusBadge(payload)}
      status={payload?.status === 'ok' ? 'live' : 'muted'}
      count={items.length}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>World Cup Match Ops</strong>
          <p>Seeded match evidence derived from the World Cup dashboard: openfootball schedule, score links, venue weather, and Polymarket match links.</p>
        </div>
      ) : null}
      className="wm-market-panel wm-evidence-panel wm-world-cup-match-ops-panel"
      dataPanelId="world-cup-match-ops"
    >
      <div className="wm-evidence-summary">
        <span><em>NEXT</em><strong>{payload?.summary?.nextMatch || '--'}</strong></span>
        <span><em>PMKT</em><strong>{score(payload?.summary?.linkedMarkets)}</strong></span>
        <span><em>WX</em><strong>{score(payload?.summary?.weatherWatch)}</strong></span>
      </div>
      <div className="wm-evidence-list">
        {items.length ? items.map((item) => <MatchRow key={item.id || `${item.homeTeam}-${item.awayTeam}-${item.kickoffUtc}`} item={item} />) : (
          <div className="wm-registry-empty"><strong>World Cup Match Ops seed warming</strong></div>
        )}
      </div>
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'world-cup-match-ops': {
    render: (ctx) => <WorldCupMatchOpsPanel payload={ctx.runtimeData['world-cup-match-ops'] as RuntimeWorldCupMatchOpsPayload | undefined} />,
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'world-cup-match-ops',
  title: 'World Cup Match Ops',
  eyebrow: 'sports',
  description: 'World Cup schedule, venue weather, score status, and Polymarket match links.',
  defaultEnabled: true,
}, {
  tier: 'fast',
  intervalMs: 60000,
  fetchData: () => fetchRuntimeWorldCupMatchOps(12),
});
