import {
  WORLD_EVENT_SEVERITIES,
  WORLD_EVENT_TIME_RANGES,
  type WorldEventMapState,
  type WorldEventTimeRange,
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
  onTimeRangeChange,
  onSeveritiesChange,
}: {
  state: Pick<WorldEventMapState, 'timeRange' | 'severities'>;
  onTimeRangeChange: (timeRange: WorldEventTimeRange) => void;
  onSeveritiesChange: (severities: GeoEventSeverity[]) => void;
}) {
  const selected = new Set(state.severities);
  return (
    <div className="wm-world-event-map-toolbar" aria-label="World Event Map filters">
      <label>
        <span>Time</span>
        <select
          aria-label="Map time range"
          value={state.timeRange}
          onChange={(event) => onTimeRangeChange(
            (event.currentTarget as HTMLSelectElement).value as WorldEventTimeRange,
          )}
        >
          {WORLD_EVENT_TIME_RANGES.map((timeRange) => (
            <option value={timeRange} key={timeRange}>{timeRange === 'all' ? 'All time' : timeRange}</option>
          ))}
        </select>
      </label>
      <span className="wm-world-event-severity-label">Severity</span>
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
            {SEVERITY_LABELS[severity]}
          </button>
        ))}
      </div>
    </div>
  );
}
