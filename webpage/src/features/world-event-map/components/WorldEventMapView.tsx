import { lazy, Suspense } from 'preact/compat';
import { useI18n } from '@/services/i18n';
import type { GeoEvent } from '../domain/types';
import type { AviationLensMode, AviationRiskSource, WorldEventMapState } from '../state/mapState';
const WorldEventMap = lazy(() => import('./WorldEventMap').then((module) => ({ default: module.WorldEventMap })));

export function WorldEventMapView({
  onRendererKindChange,
  events,
  state,
  onCameraChange,
  onEventSelect,
  onOpenMarket,
  onAviationLensChange,
  onAviationRiskSourceChange,
  onAviationClose,
  onCountryChange,
}: {
  onRendererKindChange?: (kind: 'webgl' | 'svg') => void;
  events: GeoEvent[];
  state: WorldEventMapState;
  onCameraChange: (camera: Pick<WorldEventMapState, 'center' | 'zoom'>) => void;
  onEventSelect: (eventId: string | null) => void;
  onOpenMarket: (marketId: number) => void;
  onAviationLensChange: (lens: AviationLensMode) => void;
  onAviationRiskSourceChange: (source: AviationRiskSource) => void;
  onAviationClose: () => void;
  onCountryChange: (countryCode: string | null) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="wm-inline-weather-map">
      <Suspense fallback={<div className="wm-world-event-map-shell" role="status">{t('map.loadingworldeventrenderer')}</div>}>
        <WorldEventMap
          onRendererKindChange={onRendererKindChange}
          events={events}
          state={state}
          onCameraChange={onCameraChange}
          onEventSelect={onEventSelect}
          onOpenMarket={onOpenMarket}
          onAviationLensChange={onAviationLensChange}
          onAviationRiskSourceChange={onAviationRiskSourceChange}
          onAviationClose={onAviationClose}
          onCountryChange={onCountryChange}
          height={620}
        />
      </Suspense>
    </div>
  );
}
