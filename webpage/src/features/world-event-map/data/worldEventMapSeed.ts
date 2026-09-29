import type { RuntimeGeoSanctionsShockItem, RuntimeGeoSanctionsShockPayload } from '@/types';
import type { PanelRuntimeData } from '@/panels/types';

const GEO_SHOCK_STORAGE_KEY = 'polydata:seed:world:geo-sanctions-shock:v1';
const GEO_SHOCK_LOCAL_STALE_MS = 24 * 60 * 60 * 1000;
type GeoShockLocalSeed = {
  storedAt: number;
  payload: RuntimeGeoSanctionsShockPayload;
};


export function hasGeoConflictCoordinates(item: RuntimeGeoSanctionsShockItem) {
  const lat = Number(item.latitude);
  const lon = Number(item.longitude);
  return Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
}


function hasRenderableGeoShockPayload(payload?: RuntimeGeoSanctionsShockPayload | null) {
  return Boolean((payload?.items || []).some(hasGeoConflictCoordinates));
}

export function readWorldEventMapSeed(): PanelRuntimeData {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(GEO_SHOCK_STORAGE_KEY);
    if (!raw) return {};
    const cached = JSON.parse(raw) as GeoShockLocalSeed;
    if (!cached?.payload || !hasRenderableGeoShockPayload(cached.payload)) return {};
    if (Date.now() - Number(cached.storedAt || 0) > GEO_SHOCK_LOCAL_STALE_MS) return {};
    return {
      'geo-sanctions-shock': {
        ...cached.payload,
        cacheMode: 'local-stale',
      },
    };
  } catch {
    return {};
  }
}

export function writeWorldEventMapSeed(payload?: RuntimeGeoSanctionsShockPayload | null) {
  if (typeof window === 'undefined' || !hasRenderableGeoShockPayload(payload)) return;
  try {
    window.localStorage.setItem(GEO_SHOCK_STORAGE_KEY, JSON.stringify({ storedAt: Date.now(), payload }));
  } catch {
    // The remote seed remains authoritative; local storage is only a first-paint fallback.
  }
}
