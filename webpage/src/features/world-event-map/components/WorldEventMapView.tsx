import { lazy, Suspense } from 'preact/compat';
import { useEffect } from 'preact/hooks';
import { loadMapFonts } from '../config/mapTypography';
import { useI18n } from '@/services/i18n';
const WorldEventMap = lazy(() => import('./WorldEventMap').then((module) => ({ default: module.WorldEventMap })));

export function WorldEventMapView(props: import('./WorldEventMap').WorldEventMapProps) {
  const { t } = useI18n();
  useEffect(() => { void loadMapFonts(); }, []);
  return (
    <div className="wm-inline-weather-map">
      <Suspense fallback={<div className="wm-world-event-map-shell" role="status">{t('map.loadingworldeventrenderer')}</div>}>
        <WorldEventMap {...props} />
      </Suspense>
    </div>
  );
}
