import { useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeGeoSanctionsShock } from '@/services/api';
import type { RuntimeGeoSanctionsShockItem, RuntimeGeoSanctionsShockPayload } from '@/types';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '../helpers';

function badgeLabel(status?: string | null) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'ok') return 'LIVE';
  if (normalized === 'empty') return 'QUIET';
  if (normalized === 'degraded') return 'DEGRADED';
  return 'LIVE';
}

function panelTone(status?: string | null): 'live' | 'muted' {
  return String(status || '').toLowerCase() === 'ok' ? 'live' : 'muted';
}

function upperMetric(value?: string | null) {
  const text = String(value || '').trim();
  return text ? text.toUpperCase() : '--';
}

function severityClass(level?: string | null) {
  const normalized = String(level || '').toLowerCase();
  if (normalized === 'critical') return 'sev-critical';
  if (normalized === 'warning') return 'sev-warning';
  return 'sev-watch';
}

function severityLabel(level?: string | null) {
  const normalized = String(level || '').toLowerCase();
  if (normalized === 'critical') return 'CRITICAL';
  if (normalized === 'warning') return 'ALERT';
  return 'WATCH';
}

function kindLabel(kind?: string | null) {
  const normalized = String(kind || '').toLowerCase();
  if (normalized === 'sanction') return 'SANCTION';
  if (normalized === 'notice') return 'NOTICE';
  if (normalized === 'conflict') return 'CONFLICT';
  return 'SIGNAL';
}

function kindGlyph(kind?: string | null) {
  const normalized = String(kind || '').toLowerCase();
  if (normalized === 'sanction') return 'S';
  if (normalized === 'notice') return 'N';
  if (normalized === 'conflict') return '!';
  return 'G';
}

function formatDate(value?: string | null) {
  const text = String(value || '').trim();
  if (!text) return '--';
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text.slice(0, 10);
  return parsed.toISOString().slice(0, 10);
}

function formatAge(value?: string | null) {
  const text = String(value || '').trim();
  if (!text) return '--';
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text.slice(0, 10);
  const diffMs = Date.now() - parsed.getTime();
  const absDiff = Math.abs(diffMs);
  const minutes = Math.floor(absDiff / 60000);
  const hours = Math.floor(absDiff / 3600000);
  const days = Math.floor(absDiff / 86400000);
  if (minutes < 1) return 'JUST NOW';
  if (minutes < 60) return `${minutes}M AGO`;
  if (hours < 24) return `${hours}H AGO`;
  if (days < 30) return `${days}D AGO`;
  return parsed.toISOString().slice(0, 10);
}

function violenceLabel(value?: string | number | null) {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (normalized === '1' || normalized === 'state-based') return 'STATE';
  if (normalized === '2' || normalized === 'non-state') return 'NON-STATE';
  if (normalized === '3' || normalized === 'one-sided') return 'ONE-SIDED';
  return 'CONFLICT';
}

function isUcdpConflict(item: RuntimeGeoSanctionsShockItem) {
  return String(item.kind || '').toLowerCase() === 'conflict' && String(item.source || '').toUpperCase() === 'UCDP';
}

function GeoShockPanel({ payload }: {
  payload?: RuntimeGeoSanctionsShockPayload | null;
}) {
  const [showHelp, setShowHelp] = useState(false);
  const items = payload?.items || [];

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
      count={items.length || undefined}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>Geo shock registry</strong>
          <p>Composes OFAC, Federal Register, and conflict feeds into tradeable geopolitical macro-risk signals.</p>
        </div>
      ) : null}
      className="wm-market-panel wm-geo-shock-panel"
      dataPanelId="geo-sanctions-shock"
    >
      <div className="wm-geo-shock-layout">
        <section className="wm-geo-shock-section compact">
          <div className="wm-geo-shock-feed">
            {items.length ? items.slice(0, 12).map((item) => {
              const sevClass = severityClass(item.severity);
              const targetLabel = upperMetric(item.targetLabels?.[0] || item.country || '');
              const ucdpConflict = isUcdpConflict(item);
              const actors = [item.sideA, item.sideB].map((part) => String(part || '').trim()).filter(Boolean).join(' vs ');
              const deaths = Number(item.deathsBest ?? 0);
              return (
                <article key={item.id || `${item.headline}-${item.occurredAt}`} className={`wm-geo-shock-row ${sevClass}${ucdpConflict ? ' is-conflict' : ''}`}>
                  <span className={`wm-row-glyph ${sevClass}`}>{kindGlyph(item.kind)}</span>
                  <div className="wm-geo-shock-row-main">
                    {ucdpConflict ? (
                      <>
                        <div className="wm-geo-conflict-grid">
                          <span>
                            <i>Country</i>
                            <strong>{item.country || '--'}</strong>
                          </span>
                          <span>
                            <i>Deaths</i>
                            <strong>{deaths ? deaths.toLocaleString() : '0'}</strong>
                          </span>
                          <span>
                            <i>Date</i>
                            <strong>{formatDate(item.occurredAt)}</strong>
                          </span>
                          <span>
                            <i>Type</i>
                            <strong>{violenceLabel(item.violenceType)}</strong>
                          </span>
                        </div>
                        <div className="wm-geo-shock-headline">{actors || item.headline || 'UCDP conflict event'}</div>
                        <div className="wm-geo-shock-summary">{item.locationLabel || item.summary || 'UCDP georeferenced conflict event'}</div>
                      </>
                    ) : (
                      <>
                        <div className="wm-geo-shock-row-top">
                          <span className={`wm-geo-shock-kind ${sevClass}`}>{severityLabel(item.severity)}</span>
                          <span className="wm-geo-shock-domain">{kindLabel(item.kind)}</span>
                          <span className="wm-geo-shock-source">{upperMetric(item.source || 'SOURCE')}</span>
                          <span className="wm-geo-shock-time">{formatAge(item.occurredAt)}</span>
                        </div>
                        <div className="wm-geo-shock-headline">{item.headline || 'Monitoring update'}</div>
                        {targetLabel && targetLabel !== '--' ? <span className="wm-geo-shock-target-mini">{targetLabel}</span> : null}
                      </>
                    )}
                  </div>
                </article>
              );
            }) : (
              <div className="wm-geo-shock-empty">No seeded shock items yet.</div>
            )}
          </div>
        </section>
      </div>
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
  description: 'Geopolitical shocks, sanctions changes, and linked macro-risk markets.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  fetchData: () => fetchRuntimeGeoSanctionsShock(12),
});
