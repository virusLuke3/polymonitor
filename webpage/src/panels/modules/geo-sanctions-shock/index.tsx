import { macroSnapshot, macroRefreshPolicy, MacroRefresh } from '@/panels/shared/macro-runtime';
import { panelStatus as panelTone } from '@/panels/shared/formatters';
import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeGeoSanctionsShock } from '@/services/api';
import type { RuntimeGeoSanctionsShockItem, RuntimeGeoSanctionsShockPayload } from '@/types';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

type UcdpTab = 'state-based' | 'non-state' | 'one-sided';

const UCDP_DISPLAY_LIMIT = 50;

const UCDP_TABS: { key: UcdpTab; label: string }[] = [
  { key: 'state-based', label: 'State' },
  { key: 'non-state', label: 'Non-state' },
  { key: 'one-sided', label: 'One-sided' },
];

function badgeLabel(status?: string | null) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'ok') return 'CONTEXT';
  if (normalized === 'empty') return 'QUIET';
  if (normalized === 'degraded') return 'DEGRADED';
  return 'WARMING';
}

function formatDate(value?: string | null) {
  const text = String(value || '').trim();
  if (!text) return '--';
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text.slice(0, 10);
  return parsed.toISOString().slice(0, 10);
}

function formatCompactNumber(value?: number | null) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) return '0';
  return numeric.toLocaleString();
}

function violenceKey(value?: string | number | null): UcdpTab {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (normalized === '2' || normalized === 'non-state') return 'non-state';
  if (normalized === '3' || normalized === 'one-sided') return 'one-sided';
  return 'state-based';
}

function isUcdpConflict(item: RuntimeGeoSanctionsShockItem) {
  return String(item.kind || '').toLowerCase() === 'conflict' && String(item.source || '').toUpperCase() === 'UCDP';
}

function eventActors(item: RuntimeGeoSanctionsShockItem) {
  const actors = [item.sideA, item.sideB].map((part) => String(part || '').trim()).filter(Boolean);
  return actors.length ? actors.join(' vs ') : item.headline || 'UCDP conflict event';
}

function deathRange(item: RuntimeGeoSanctionsShockItem) {
  const low = Number(item.deathsLow ?? 0);
  const high = Number(item.deathsHigh ?? 0);
  if (!Number.isFinite(low) || !Number.isFinite(high) || (!low && !high)) return '';
  return `(${formatCompactNumber(low)}-${formatCompactNumber(high)})`;
}

function GeoShockPanel({ payload }: {
  payload?: RuntimeGeoSanctionsShockPayload | null;
}) {
  const [showHelp, setShowHelp] = useState(false);
  const [view, setView] = useState<'sanctions' | 'conflicts'>('sanctions');
  const sanctions = (payload?.sanctionsItems ?? payload?.items ?? []).filter(item => ['sanction', 'notice', 'policy'].includes(String(item.kind || '').toLowerCase()));
  const [activeTab, setActiveTab] = useState<UcdpTab>('state-based');
  const events = useMemo(
    () => (payload?.items || []).filter(isUcdpConflict),
    [payload?.items],
  );
  const counts = useMemo(() => {
    const result: Record<UcdpTab, number> = { 'state-based': 0, 'non-state': 0, 'one-sided': 0 };
    events.forEach((event) => {
      result[violenceKey(event.violenceType)] += 1;
    });
    return result;
  }, [events]);
  const filtered = events.filter((event) => violenceKey(event.violenceType) === activeTab);
  const totalDeaths = filtered.reduce((sum, event) => sum + Number(event.deathsBest || 0), 0);
  const visibleRows = filtered.slice(0, UCDP_DISPLAY_LIMIT);
  const activeCount = counts[activeTab];

  return (
    <Panel
      title="GEO / SANCTIONS SHOCK"
      titleControls={(
        <button
          type="button"
          className="wm-panel-help-button"
          aria-label="Explain GEO / SANCTIONS SHOCK"
          aria-expanded={showHelp}
          onClick={() => setShowHelp((current) => !current)}
        >
          ?
        </button>
      )}
      badge={badgeLabel(payload?.status)}
      status={panelTone(payload?.status)}
      count={view === 'sanctions' ? sanctions.length : activeCount}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>Sanctions and conflict context</strong>
          <p>OFAC list entries and dated Federal Register notices are separate from historical UCDP conflict observations. List entries are not necessarily new sanctions. Historical deaths do not measure current escalation.</p>
        </div>
      ) : null}
      className="wm-market-panel wm-geo-shock-panel"
      dataPanelId="geo-sanctions-shock"
    >
      <MacroRefresh payload={payload} sourceMinutes={5} />
      <div className="wm-macro-filters" aria-label="Geopolitical data view">
        <button type="button" aria-pressed={view === 'sanctions'} onClick={() => setView('sanctions')}>Sanctions / policy {sanctions.length}</button>
        <button type="button" aria-pressed={view === 'conflicts'} onClick={() => setView('conflicts')}>Conflict history {events.length}</button>
      </div>
      {view === 'sanctions' ? <div>
        <small className="wm-macro-observation">OFAC list entries are context, not a count of new sanctions. Policy notices keep their publication dates.</small>
        {sanctions.length ? sanctions.map(item => <article key={item.id} className="wm-macro-registry-row">
          <div><strong>{item.headline}</strong><p>{item.summary}</p>
            <small className="wm-macro-observation">{item.source} · Published {formatDate(item.occurredAt)}</small>
            <small className="wm-macro-observation">Collected {item.collectedAt ? new Date(item.collectedAt).toLocaleString() : 'Unknown'}{item.retained ? ' · Saved record; source refresh failed' : ''}</small>
            <a className="wm-macro-source-link" href={item.sourceUrl || 'https://ofac.treasury.gov/sanctions-list-service'} target="_blank" rel="noopener noreferrer">Source</a>
          </div>
        </article>) : <p>No sanctions / policy observations available. Check source status above.</p>}
      </div> : <div className="wm-geo-ucdp-panel">
        <small className="wm-macro-observation">Historical UCDP dataset · Latest observation {events.map(item => item.occurredAt || '').sort().slice(-1)[0]?.slice(0, 10) || '--'}. Not a live conflict alert.</small>
        <div className="wm-geo-ucdp-header">
          <div className="wm-geo-ucdp-tabs" role="tablist" aria-label="UCDP violence type">
            {UCDP_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.key}
                className={activeTab === tab.key ? 'active' : undefined}
                onClick={() => setActiveTab(tab.key)}
              >
                <span>{tab.label}</span>
                <b>{counts[tab.key]}</b>
              </button>
            ))}
          </div>
          <span className="wm-geo-ucdp-total">{formatCompactNumber(totalDeaths)} deaths</span>
        </div>

        {visibleRows.length ? (
          <table className="wm-geo-ucdp-table">
            <thead>
              <tr>
                <th>Country</th>
                <th>Deaths</th>
                <th>Date</th>
                <th>Actors</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((event) => {
                const deaths = Number(event.deathsBest ?? 0);
                return (
                  <tr key={event.id || `${event.country}-${event.occurredAt}-${eventActors(event)}`}>
                    <td className="wm-geo-ucdp-country">{event.country || '--'}</td>
                    <td className="wm-geo-ucdp-deaths">
                      <strong>{formatCompactNumber(deaths)}</strong>
                      {deathRange(event) ? <small>{deathRange(event)}</small> : null}
                    </td>
                    <td className="wm-geo-ucdp-date">{formatDate(event.occurredAt)}</td>
                    <td className="wm-geo-ucdp-actors">
                      <strong>{eventActors(event)}</strong>
                      {event.locationLabel || event.summary ? <span>{event.locationLabel || event.summary}</span> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="wm-geo-shock-empty">No UCDP events in this category.</div>
        )}
        {visibleRows.length ? (
          <div className="wm-geo-ucdp-more">
            <span>Showing {formatCompactNumber(visibleRows.length)} of {formatCompactNumber(filtered.length)}</span>
            <span>Cache {formatCompactNumber(events.length)}</span>
          </div>
        ) : null}
      </div>}
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'geo-sanctions-shock': {
    render: (ctx) => {
      const payload = ctx.runtimeData['geo-sanctions-shock'] as RuntimeGeoSanctionsShockPayload | undefined;
      return <GeoShockPanel payload={payload} />;
    },
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'geo-sanctions-shock',
  title: 'Geopolitical & Sanctions Shock',
  eyebrow: 'world',
  description: 'UCDP conflict events, sanctions changes, and linked macro-risk markets.',
  defaultEnabled: true,
  snapshot: macroSnapshot('geo-sanctions-shock', true),
}, {
  ...macroRefreshPolicy,
  staleAfterMs: 10 * 60_000,
  limit: 2000,
  fetchData: (context, limit) => fetchRuntimeGeoSanctionsShock(limit, context?.signal),
});
