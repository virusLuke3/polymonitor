import { macroSnapshot, macroRefreshPolicy, MacroRefresh } from '@/panels/shared/macro-runtime';
import { displayValue as display } from '@/panels/shared/macro-intel';
import { panelStatus } from '@/panels/shared/formatters';
import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeCpiReleaseCommandCenter } from '@/services/api';
import type { RuntimeCpiReleaseCommandEvent, RuntimeCpiReleaseCommandPayload, RuntimeMacroRegistryItem } from '@/types';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '@/panels/definePanel';
import { useSpecialistCopy } from '@/services/specialist-i18n';

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
  if (value == null || value === '') return '--';
  const hours = Number(value);
  if (!Number.isFinite(hours)) return '--';
  if (hours <= 0) return 'released';
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

function eventTone(_event: RuntimeCpiReleaseCommandEvent) { return 'neutral'; }

function Metric({ label, value, tone }: { label: string; value?: number | string | null; tone?: string }) {
  return (
    <span className={tone ? `wm-cpi-command-metric ${tone}` : 'wm-cpi-command-metric'}>
      <i>{label}</i>
      <strong>{display(value)}</strong>
    </span>
  );
}

function EventCard({ event }: { event: RuntimeCpiReleaseCommandEvent }) {
  const { copy, shared } = useSpecialistCopy('cpi-release-command-center');
  const tone = eventTone(event);
  return (
    <article className={`wm-cpi-event-card ${tone}`}>
      <div className="wm-cpi-event-head">
        <strong>{event.title || copy('event', 'CPI event')}</strong>
        <span>{event.period || event.asOf || '--'}</span>
      </div>
      <div className="wm-cpi-event-grid">
        <Metric label={shared('actual', 'Actual')} value={event.actualLabel || event.actual || '--'} />
        <Metric label={event.forecastKind || shared('forecast', 'Forecast')} value={event.forecastLabel || event.forecast || '--'} tone={tone} />
        <Metric label={shared('previous', 'Previous')} value={event.previousLabel || event.previous || '--'} />
        <Metric label={shared('surprise', 'Surprise')} value={event.surpriseLabel || '--'} tone={tone} />
      </div>
      <div className="wm-cpi-event-foot">
        <span>{event.seriesId || 'BLS'}</span>
        <span>{event.forecastSource ? `${shared('forecast', 'Forecast')}: ` : ''}{event.forecastSource || copy('noConsensus', 'No consensus feed')}</span>
      </div>
      <small className="wm-macro-observation">{event.adjustment} · {event.status} · {event.limitation || `Nowcast checked ${event.forecastAsOf || '--'}`}</small>
      {event.sourceUrl ? <a className="wm-macro-source-link" href={event.sourceUrl} target="_blank" rel="noopener noreferrer">BLS / FRED series</a> : null}
      {event.forecastSourceUrl ? <> · <a className="wm-macro-source-link" href={event.forecastSourceUrl} target="_blank" rel="noopener noreferrer">Nowcast source</a></> : null}
    </article>
  );
}

function ReleaseQueue({ items }: { items: RuntimeMacroRegistryItem[] }) {
  const { copy } = useSpecialistCopy('cpi-release-command-center');
  const releases = items
    .filter((item) => String(item.type || '').toLowerCase() === 'release')
    .filter(item => Date.parse(item.date || '') >= Date.now())
    .sort((a, b) => Date.parse(a.date || '') - Date.parse(b.date || ''))
    .slice(0, 5);
  if (!releases.length) return null;
  return (
    <div className="wm-cpi-release-queue" aria-label={copy('upcomingAria', 'Upcoming macro releases')}>
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
  const { copy, shared } = useSpecialistCopy('cpi-release-command-center');
  const [showHelp, setShowHelp] = useState(false);
  const events = payload?.events || [];
  const release = payload?.release;
  const summary = payload?.summary;
  const rows = payload?.items || [];
  const badge = String(payload?.status || '').toLowerCase() === 'ok' ? 'EVENT' : display(payload?.status || 'WARMING').toUpperCase();
  const sourceLine = summary?.sourceLabel || copy('sourceLine', 'BLS calendar / Cleveland Fed nowcast / FRED actuals');
  const releaseTitle = release?.title || copy('consumerPriceIndex', 'Consumer Price Index');
  const releaseAt = release?.releaseAt || events[0]?.releaseAt || null;
  const releaseTime = release?.releaseTimeEt || formatReleaseTime(releaseAt);
  const eventCount = summary?.eventCount ?? events.length;
  const cards = useMemo(() => events.slice(0, 4), [events]);

  return (
    <Panel
      title={copy('title', 'CPI RELEASE COMMAND')}
      titleControls={(
        <button
          type="button"
          className="wm-panel-help-button"
          aria-label={copy('explainAria', 'Explain CPI release command')}
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
          <strong>{copy('helpTitle', 'CPI Release Command')}</strong>
          <p>{copy('helpText', 'Shows official release timing, Cleveland Fed nowcast as forecast signal, and BLS/FRED latest actuals as previous values. Actual stays blank before the release.')}</p>
        </div>
      ) : null}
      className="wm-market-panel wm-cpi-command-panel"
      dataPanelId="cpi-release-command-center"
    >
      <MacroRefresh payload={payload} />
      <small className="wm-macro-observation">Model nowcast is not market consensus. Actual is pending until the matching BLS period is published.</small>
      <div className="wm-cpi-command-hero">
        <div>
          <span>{copy('nextPrint', 'NEXT CPI PRINT')}</span>
          <strong>{releaseTitle}</strong>
          <em>{summary?.period ? copy('reference', 'Reference {period}', { period: summary.period }) : sourceLine}</em>
        </div>
        <div className="wm-cpi-command-clock">
          <strong>{formatHours(releaseAt ? (Date.parse(releaseAt) - Date.now()) / 3_600_000 : null)}</strong>
          <span>{releaseTime}</span>
        </div>
      </div>

      <div className="wm-cpi-command-strip">
        <Metric label={shared('actual', 'Actual')} value={`${display(summary?.actualCount)}/${display(summary?.eventCount)}`} />
        <Metric label={shared('forecast', 'Forecast')} value={`${display(summary?.forecastCount)}/${display(summary?.eventCount)}`} tone="watch" />
        <Metric label={shared('previous', 'Previous')} value={`${display(summary?.previousCount)}/${display(summary?.eventCount)}`} />
        <Metric label={shared('source', 'Source')} value={payload?.cacheMode || payload?.status || '--'} />
      </div>

      {cards.length ? (
        <div className="wm-cpi-event-list">
          {cards.map((event) => <EventCard key={event.key || event.title || 'cpi'} event={event} />)}
        </div>
      ) : (
        <div className="wm-empty-state">
          <strong>{copy('warming', 'CPI RELEASE WARMING')}</strong>
          <em>{copy('warmingText', 'Waiting for calendar, nowcast, and BLS/FRED CPI series.')}</em>
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
  snapshot: macroSnapshot('cpi-release-command-center'),
}, {
  ...macroRefreshPolicy,
  limit: 36,
  fetchData: (context, limit) => fetchRuntimeCpiReleaseCommandCenter(limit, context?.signal),
});
