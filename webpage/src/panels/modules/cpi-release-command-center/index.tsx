import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeCpiReleaseCommandCenter } from '@/services/api';
import type { RuntimeCpiReleaseCommandEvent, RuntimeCpiReleaseCommandPayload, RuntimeMacroRegistryItem } from '@/types';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '../helpers';

function panelStatus(status?: string | null): 'live' | 'muted' {
  return String(status || '').toLowerCase() === 'ok' ? 'live' : 'muted';
}

function display(value?: number | string | null) {
  const text = String(value ?? '').trim();
  return text || '--';
}

function formatReleaseTime(value?: string | null) {
  if (!value) return '--';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(parsed);
}

function formatHours(value?: number | string | null) {
  const hours = Number(value);
  if (!Number.isFinite(hours)) return '--';
  if (hours <= 0) return 'released';
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

function eventTone(event: RuntimeCpiReleaseCommandEvent) {
  const surprise = Number(event.surprise);
  if (Number.isFinite(surprise)) {
    if (surprise >= 0.1) return 'hot';
    if (surprise <= -0.1) return 'cool';
  }
  const forecast = Number(event.forecast);
  if (Number.isFinite(forecast)) {
    const hotLine = String(event.key || '').includes('mom') ? 0.35 : 3.2;
    const coolLine = String(event.key || '').includes('mom') ? 0.2 : 2.6;
    if (forecast >= hotLine) return 'hot';
    if (forecast <= coolLine) return 'cool';
  }
  return 'watch';
}

function Metric({ label, value, tone }: { label: string; value?: number | string | null; tone?: string }) {
  return (
    <span className={tone ? `wm-cpi-command-metric ${tone}` : 'wm-cpi-command-metric'}>
      <i>{label}</i>
      <strong>{display(value)}</strong>
    </span>
  );
}

function EventCard({ event }: { event: RuntimeCpiReleaseCommandEvent }) {
  const tone = eventTone(event);
  return (
    <article className={`wm-cpi-event-card ${tone}`}>
      <div className="wm-cpi-event-head">
        <strong>{event.title || 'CPI event'}</strong>
        <span>{event.period || event.asOf || '--'}</span>
      </div>
      <div className="wm-cpi-event-grid">
        <Metric label="Actual" value={event.actualLabel || event.actual || '--'} />
        <Metric label={event.forecastKind || 'Forecast'} value={event.forecastLabel || event.forecast || '--'} tone={tone} />
        <Metric label="Previous" value={event.previousLabel || event.previous || '--'} />
        <Metric label="Surprise" value={event.surpriseLabel || '--'} tone={tone} />
      </div>
      <div className="wm-cpi-event-foot">
        <span>{event.seriesId || 'BLS'}</span>
        <span>{event.forecastSource ? 'Forecast: ' : ''}{event.forecastSource || 'No consensus feed'}</span>
      </div>
    </article>
  );
}

function ReleaseQueue({ items }: { items: RuntimeMacroRegistryItem[] }) {
  const releases = items
    .filter((item) => String(item.type || '').toLowerCase() === 'release')
    .slice(0, 5);
  if (!releases.length) return null;
  return (
    <div className="wm-cpi-release-queue" aria-label="Upcoming macro releases">
      {releases.map((item) => (
        <div className="wm-cpi-release-row" key={item.key || `${item.group}-${item.date}`}>
          <span>{display(item.group)}</span>
          <strong>{display(item.label)}</strong>
          <em>{formatReleaseTime(item.date)}</em>
        </div>
      ))}
    </div>
  );
}

function CpiReleaseCommandPanel({ payload }: { payload?: RuntimeCpiReleaseCommandPayload | null }) {
  const [showHelp, setShowHelp] = useState(false);
  const events = payload?.events || [];
  const release = payload?.release;
  const summary = payload?.summary;
  const rows = payload?.items || [];
  const badge = String(payload?.status || '').toLowerCase() === 'ok' ? 'EVENT' : display(payload?.status || 'WARMING').toUpperCase();
  const sourceLine = summary?.sourceLabel || 'BLS calendar / Cleveland Fed nowcast / FRED actuals';
  const releaseTitle = release?.title || 'Consumer Price Index';
  const releaseAt = release?.releaseAt || events[0]?.releaseAt || null;
  const releaseTime = release?.releaseTimeEt || formatReleaseTime(releaseAt);
  const eventCount = summary?.eventCount ?? events.length;
  const cards = useMemo(() => events.slice(0, 4), [events]);

  return (
    <Panel
      title="CPI RELEASE COMMAND"
      titleControls={(
        <button
          type="button"
          className="wm-panel-help-button"
          aria-label="Explain CPI release command"
          aria-expanded={showHelp}
          onClick={() => setShowHelp((current) => !current)}
        >
          ?
        </button>
      )}
      badge={badge}
      status={panelStatus(payload?.status)}
      count={eventCount}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>CPI Release Command</strong>
          <p>Shows official release timing, Cleveland Fed nowcast as forecast signal, and BLS/FRED latest actuals as previous values. Actual stays blank before the release.</p>
        </div>
      ) : null}
      className="wm-market-panel wm-cpi-command-panel"
      dataPanelId="cpi-release-command-center"
    >
      <div className="wm-cpi-command-hero">
        <div>
          <span>NEXT CPI PRINT</span>
          <strong>{releaseTitle}</strong>
          <em>{summary?.period ? `Reference ${summary.period}` : sourceLine}</em>
        </div>
        <div className="wm-cpi-command-clock">
          <strong>{formatHours(summary?.hoursToEvent)}</strong>
          <span>{releaseTime}</span>
        </div>
      </div>

      <div className="wm-cpi-command-strip">
        <Metric label="Actual" value={`${display(summary?.actualCount)}/${display(summary?.eventCount)}`} />
        <Metric label="Forecast" value={`${display(summary?.forecastCount)}/${display(summary?.eventCount)}`} tone="watch" />
        <Metric label="Previous" value={`${display(summary?.previousCount)}/${display(summary?.eventCount)}`} />
        <Metric label="Source" value={payload?.cacheMode || payload?.status || '--'} />
      </div>

      {cards.length ? (
        <div className="wm-cpi-event-list">
          {cards.map((event) => <EventCard key={event.key || event.title || 'cpi'} event={event} />)}
        </div>
      ) : (
        <div className="wm-empty-state">
          <strong>CPI RELEASE WARMING</strong>
          <em>Waiting for calendar, nowcast, and BLS/FRED CPI series.</em>
        </div>
      )}

      <ReleaseQueue items={rows} />
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'cpi-release-command-center': {
    render: (ctx) => (
      <CpiReleaseCommandPanel
        payload={ctx.runtimeData['cpi-release-command-center'] as RuntimeCpiReleaseCommandPayload | undefined}
      />
    ),
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'cpi-release-command-center',
  title: 'CPI Release Command Center',
  eyebrow: 'macro',
  description: 'Official release timing with CPI event cards, nowcast forecast signal, and BLS/FRED previous values.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  fetchData: () => fetchRuntimeCpiReleaseCommandCenter(36),
});
