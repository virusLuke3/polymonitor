import { useEffect, useState } from 'preact/hooks';
import { useI18n } from '@/services/i18n';
import { mapText } from '@/locales/map';
import {
  WORLD_EVENT_SEVERITIES,
  WORLD_EVENT_TIME_RANGES,
  WORLD_EVENT_BASEMAP_PROVIDERS,
  WORLD_EVENT_BASEMAP_THEMES,
  type WorldEventMapState,
  type WorldEventTimeRange,
  type WorldEventBasemapProvider,
  type WorldEventBasemapTheme,
} from '../state/mapState';
import type { GeoEventSeverity } from '../domain/types';

const SEVERITY_LABELS: Record<GeoEventSeverity, string> = {
  info: 'Info',
  watch: 'Watch',
  warning: 'Warning',
  critical: 'Critical',
};

export function MapToolbar({
  state,
  onPresentationChange,
  onTimeRangeChange,
  onSeveritiesChange,
  onBasemapProviderChange,
  onBasemapThemeChange,
  onClearCountry,
}: {
  state: Pick<WorldEventMapState, 'timeRange' | 'severities' | 'basemapProvider' | 'basemapTheme' | 'countryCode' | 'presentationMode'>;
  onPresentationChange?: (mode: WorldEventMapState['presentationMode']) => void;
  onTimeRangeChange: (timeRange: WorldEventTimeRange) => void;
  onSeveritiesChange: (severities: GeoEventSeverity[]) => void;
  onBasemapProviderChange: (provider: WorldEventBasemapProvider) => void;
  onBasemapThemeChange: (theme: WorldEventBasemapTheme) => void;
  onClearCountry: () => void;
}) {
  const { locale, t } = useI18n();
  const mt = (text: string) => mapText(locale, text);
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 720px)').matches);
  const [filtersOpen, setFiltersOpen] = useState(false);
  useEffect(() => { const media = window.matchMedia('(max-width: 720px)'); const update = () => setCompact(media.matches);
    media.addEventListener('change', update); return () => media.removeEventListener('change', update); }, []);
  const selected = new Set(state.severities);
  return (
    <div className="wm-world-event-map-toolbar" aria-label={mt("World Event Map filters")}>
      {onPresentationChange ? <div className="wm-map-time-segments" role="group" aria-label={locale === 'zh' ? '地图展示模式' : 'Map presentation'}>
        {(['overview', 'records'] as const).map(mode => <button type="button" aria-pressed={state.presentationMode === mode} onClick={() => onPresentationChange(mode)}>{locale === 'zh' ? mode === 'overview' ? '态势概览' : '完整记录' : mode === 'overview' ? 'Overview' : 'Records'}</button>)}
      </div> : null}
      <details className="wm-map-filter-details" open={!compact || filtersOpen} onToggle={e => {if (compact) setFiltersOpen(e.currentTarget.open);}}>
      <summary>{locale === 'zh' ? '筛选' : 'Filters'} · {state.timeRange} · {state.severities.length}/4</summary>
      <div className="wm-map-filter-options">
      <label>
        <span>{mt("Time")}</span>
        <div className="wm-map-time-segments" role="group" aria-label={mt('Map time range')}>
          {WORLD_EVENT_TIME_RANGES.map(timeRange => <button type="button" key={timeRange}
            aria-pressed={state.timeRange === timeRange}
            onClick={() => onTimeRangeChange(timeRange)}>
            {timeRange === 'all' ? mt('All time') : timeRange}
          </button>)}
        </div>
      </label>
      <span className="wm-world-event-severity-label">{mt("Severity")}</span>
      <div className="wm-world-event-severity-filters">
        {WORLD_EVENT_SEVERITIES.map((severity) => (
          <button
            type="button"
            key={severity}
            className={`is-${severity} ${selected.has(severity) ? 'active' : ''}`}
            aria-pressed={selected.has(severity)}
            onClick={() => onSeveritiesChange(
              selected.has(severity)
                ? state.severities.filter((candidate) => candidate !== severity)
                : [...state.severities, severity],
            )}
          >
            {mt(SEVERITY_LABELS[severity])}
          </button>
        ))}
      </div>
      <label className="wm-world-event-basemap-control">
        <span>{mt("Basemap")}</span>
        <select
          aria-label={mt("Basemap provider")}
          value={state.basemapProvider}
          onChange={(event) => onBasemapProviderChange(
            (event.currentTarget as HTMLSelectElement).value as WorldEventBasemapProvider,
          )}
        >
          {WORLD_EVENT_BASEMAP_PROVIDERS.map((provider) => (
            <option value={provider} key={provider}>{provider === 'auto' ? mt('Auto') : provider.toUpperCase()}</option>
          ))}
        </select>
      </label>
      <label className="wm-world-event-basemap-control">
        <span>{mt("Theme")}</span>
        <select
          aria-label={mt("Basemap theme")}
          value={state.basemapTheme}
          onChange={(event) => onBasemapThemeChange(
            (event.currentTarget as HTMLSelectElement).value as WorldEventBasemapTheme,
          )}
        >
          {WORLD_EVENT_BASEMAP_THEMES.map((theme) => (
            <option value={theme} key={theme}>{mt(theme === 'positron' ? 'Light' : 'Dark')}</option>
          ))}
        </select>
      </label>
      </div>
      </details>
      {state.countryCode ? (
        <button type="button" className="wm-world-event-country-filter" onClick={onClearCountry}>
          {mt('Country')} · {state.countryCode} ×
        </button>
      ) : null}
      <details className="wm-map-help"><summary aria-label={mt('Map help')}>?</summary><p>{t('atlas.weatherHint')}</p></details>
    </div>
  );
}
