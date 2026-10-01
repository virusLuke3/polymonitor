import type { RendererViewport } from '../renderer/MapRenderer';
import type { AviationPhase } from '../data/useAviationViewport';
import { lazy, Suspense } from 'preact/compat';
import { useI18n } from '@/services/i18n';
import type { GeoEvent } from '../domain/types';
import type { AviationLensMode, AviationRiskSource, WorldEventMapState } from '../state/mapState';
const WorldEventMap = lazy(() => import('./WorldEventMap').then((module) => ({ default: module.WorldEventMap })));

export function WorldEventMapView({
  onViewportChange,
  aviationStatus,
  onRendererKindChange,
  events,
  state,
  onCameraChange,
  onEventSelect,
  onOpenMarket,
  onAviationLensChange,
  onAviationRiskSourceChange,
  onAviationToggle,
  onCountryChange,
  onWeatherPreset,
}: {
  onViewportChange?: (viewport: RendererViewport) => void;
  aviationStatus?: {phase: AviationPhase; error: string | null; payload: import('@/types').AviationViewportPayload | null};
  onRendererKindChange?: (kind: 'webgl' | 'svg') => void;
  events: GeoEvent[];
  state: WorldEventMapState;
  onCameraChange: (camera: Pick<WorldEventMapState, 'center' | 'zoom'>) => void;
  onEventSelect: (eventId: string | null) => void;
  onOpenMarket: (marketId: number) => void;
  onAviationLensChange: (lens: AviationLensMode) => void;
  onAviationRiskSourceChange: (source: AviationRiskSource) => void;
  onAviationToggle: () => void;
  onCountryChange: (countryCode: string | null) => void;
  onWeatherPreset?: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="wm-inline-weather-map">
      <Suspense fallback={<div className="wm-world-event-map-shell" role="status">{t('map.loadingworldeventrenderer')}</div>}>
        <WorldEventMap
          onViewportChange={onViewportChange}
          aviationStatus={aviationStatus}
          onRendererKindChange={onRendererKindChange}
          events={events}
          state={state}
          onCameraChange={onCameraChange}
          onEventSelect={onEventSelect}
          onOpenMarket={onOpenMarket}
          onAviationLensChange={onAviationLensChange}
          onAviationRiskSourceChange={onAviationRiskSourceChange}
          onAviationToggle={onAviationToggle}
          onCountryChange={onCountryChange}
          onWeatherPreset={onWeatherPreset}
        />
      </Suspense>
    </div>
  );
}
