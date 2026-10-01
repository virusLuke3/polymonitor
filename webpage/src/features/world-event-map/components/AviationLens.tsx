import { useI18n } from '@/services/i18n';
import { useMemo, useState } from 'preact/hooks';
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
  status,
  state,
  onLensChange,
  onRiskSourceChange,
  onClose,
  onZoomToAircraft,
}: {
  events: GeoEvent[];
  status?: {phase: import('../data/useAviationViewport').AviationPhase; error: string | null; payload: import('@/types').AviationViewportPayload | null};
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource' | 'presentationMode'>;
  onLensChange: (lens: AviationLensMode) => void;
  onRiskSourceChange: (source: AviationRiskSource) => void;
  onClose: () => void;
  onZoomToAircraft: () => void;
}) {
  const { locale } = useI18n();
  const zh = locale === 'zh';
  const [folded,setFolded] = useState(state.presentationMode === 'overview');
  const labels = zh ? {OFF:'未开启',ZOOM_REQUIRED:'需放大查看',LOADING:'正在加载',READY:'观测可用',EMPTY:'当前范围无记录',PARTIAL:'覆盖有限',STALE:'保留过期观测',UNAVAILABLE:'来源不可用',RENDERER_LIMITED:'当前渲染器受限'} : {OFF:'Off',ZOOM_REQUIRED:'Zoom in to load',LOADING:'Loading',READY:'Observations ready',EMPTY:'No records in this area',PARTIAL:'Limited coverage',STALE:'Retained stale observations',UNAVAILABLE:'Source unavailable',RENDERER_LIMITED:'Renderer limited'};
  const stats = useMemo(
    () => aviationLayerStatsForState(events, state),
    [events, state],
  );
  return (
    <aside className="wm-aviation-lens" aria-label="Aviation reference lens">
      <header>
        <div>
          <span>{zh ? '航空 · 观测与参考航线' : 'Aviation · observations & reference routes'}</span>
          <strong>{zh ? ({all:'全部',trunk:'干线',watch:'关注'}[state.aviationLens]) : LENS_LABELS[state.aviationLens]} {zh ? '航空' : 'aviation'}</strong>
        </div>
        <button type="button" aria-expanded={!folded} onClick={()=>setFolded(v=>!v)} aria-label={zh ? '展开航空详情' : 'Expand aviation details'}>{folded ? '▾' : '▴'}</button>
        <button type="button" onClick={onClose} aria-label="Hide aviation layer">×</button>
      </header>
      <p role="status" data-aviation-phase={status?.phase}>{status?.phase ? labels[status.phase] : labels.LOADING} · {status?.payload?.source || (zh ? '尚无区域观测' : 'No viewport observation')}
        {status?.payload?.generatedAt ? ` · ${zh ? '接收' : 'received'} ${status.payload.generatedAt}` : ''}
        {status?.error ? ` · ${status.error}` : ''}</p>
      {!folded ? <>
      <div className="wm-aviation-lens-stats" aria-label="Aviation reference counts">
        <span><i className="routes" /><b>{stats.visibleRoutes}</b><em>/{stats.routes} {zh ? '航线' : 'routes'}</em></span>
        <span><i className="hubs" /><b>{stats.visibleHubs}</b><em>/{stats.hubs} {zh ? '枢纽' : 'hubs'}</em></span>
        <span>
          <i className="flights" />
          <b>{stats.visibleLiveAircraft}</b>
          <em>/{stats.liveAircraft} {zh ? '观测飞机' : 'observed aircraft'}</em>
        </span>
      </div>
      <p>{zh ? '返回 / 有效 / 视口内' : 'Returned / valid / in view'}: {status?.payload?.counts ? `${status.payload.counts.returned} / ${status.payload.counts.valid} / ${status.payload.counts.inView}` : '—'} · {zh ? '匹配并有地图或记录入口' : 'Matched, with map or record access'}: {stats.visibleLiveAircraft}. {status?.payload?.coverage?.complete === false ? (zh ? '当前查询未覆盖完整区域。' : 'The query does not cover the entire area.') : ''}</p>
      <div className="wm-aviation-lens-tabs" role="group" aria-label="Aviation route mode">
        {AVIATION_LENS_MODES.map((lens) => (
          <button
            type="button"
            key={lens}
            className={state.aviationLens === lens ? 'active' : ''}
            aria-pressed={state.aviationLens === lens}
            onClick={() => onLensChange(lens)}
          >
            {zh ? ({all:'全部',trunk:'干线',watch:'关注'}[lens]) : LENS_LABELS[lens]}
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
      {(state.zoom < 2 || (state.zoom < 12 && status?.payload?.coverage?.complete === false)) ? <button type="button" className="wm-map-aviation-zoom" onClick={onZoomToAircraft}>
        {state.zoom < 2 ? (zh ? '放大以加载当前区域飞机' : 'Zoom in for aircraft in this region')
          : (zh ? '放大以缩小查询覆盖缺口' : 'Zoom in to reduce query coverage gaps')}
      </button> : null}
      <p>{zh ? '飞机位置来自 ADS-B 观测；航线动画仅为拓扑示意，不代表航班运行。' : 'Aircraft positions are ADS-B observations. Route animation illustrates topology, not operating flights.'}</p>

      </> : null}
    </aside>
  );
}
