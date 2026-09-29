import { useI18n } from '@/services/i18n';
import { useMemo } from 'preact/hooks';
import type { GeoEvent } from '../domain/types';
import { aviationLayerStatsForState } from '../renderer/layerFactories/aviationScene';
import {
  AVIATION_LENS_MODES,
  AVIATION_RISK_SOURCES,
  type AviationLensMode,
  type AviationRiskSource,
  type WorldEventMapState,
} from '../state/mapState';

const LENS_LABELS: Record<AviationLensMode, string> = {
  all: 'All',
  trunk: 'Trunk',
  watch: 'Watch',
};

const RISK_LABELS: Record<AviationRiskSource, string> = {
  all: 'All risk',
  weather: 'Weather',
  conflict: 'Conflict',
  corridor: 'Corridor',
};

export function AviationLens({
  events,
  state,
  onLensChange,
  onRiskSourceChange,
  onClose,
  onZoomToAircraft,
}: {
  events: GeoEvent[];
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>;
  onLensChange: (lens: AviationLensMode) => void;
  onRiskSourceChange: (source: AviationRiskSource) => void;
  onClose: () => void;
  onZoomToAircraft: () => void;
}) {
  const { locale } = useI18n();
  const zh = locale === 'zh';
  const stats = useMemo(
    () => aviationLayerStatsForState(events, state),
    [events, state],
  );
  return (
    <aside className="wm-aviation-lens" aria-label="Aviation reference lens">
      <header>
        <div>
          <span>{zh ? '航空 · 观测与参考航线' : 'Aviation · observations & reference routes'}</span>
          <strong>{LENS_LABELS[state.aviationLens]} aviation</strong>
        </div>
        <button type="button" onClick={onClose} aria-label="Hide aviation layer">×</button>
      </header>
      <div className="wm-aviation-lens-stats" aria-label="Aviation reference counts">
        <span><i className="routes" /><b>{stats.visibleRoutes}</b><em>/{stats.routes} {zh ? '航线' : 'routes'}</em></span>
        <span><i className="hubs" /><b>{stats.visibleHubs}</b><em>/{stats.hubs} {zh ? '枢纽' : 'hubs'}</em></span>
        <span>
          <i className="flights" />
          <b>{stats.visibleLiveAircraft}</b>
          <em>/{stats.liveAircraft} {zh ? '观测飞机' : 'observed aircraft'}</em>
        </span>
      </div>
      <div className="wm-aviation-lens-tabs" role="group" aria-label="Aviation route mode">
        {AVIATION_LENS_MODES.map((lens) => (
          <button
            type="button"
            key={lens}
            className={state.aviationLens === lens ? 'active' : ''}
            aria-pressed={state.aviationLens === lens}
            onClick={() => onLensChange(lens)}
          >
            {LENS_LABELS[lens]}
          </button>
        ))}
      </div>
      {state.aviationLens === 'watch' ? (
        <div className="wm-aviation-risk-tabs" role="group" aria-label="Aviation watch evidence">
          {AVIATION_RISK_SOURCES.map((source) => (
            <button
              type="button"
              key={source}
              className={state.aviationRiskSource === source ? 'active' : ''}
              aria-pressed={state.aviationRiskSource === source}
              onClick={() => onRiskSourceChange(source)}
            >
              <span>{RISK_LABELS[source]}</span>
              <b>{stats.riskSources[source]}</b>
            </button>
          ))}
        </div>
      ) : null}
      {state.zoom < 2 ? <button type="button" className="wm-map-aviation-zoom" onClick={onZoomToAircraft}>
        {zh ? '放大以加载当前区域飞机' : 'Zoom in for aircraft in this region'}
      </button> : null}
      <p>{zh ? '飞机位置来自 ADS-B 观测；航线动画仅为拓扑示意，不代表航班运行。' : 'Aircraft positions are ADS-B observations. Route animation illustrates topology, not operating flights.'}</p>

    </aside>
  );
}
