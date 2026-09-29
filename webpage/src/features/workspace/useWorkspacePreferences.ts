import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { DEFAULT_PANEL_IDS, PANEL_LIBRARY } from '@/panels/registry';
import type { PanelLayoutPrefs } from './panelLayout';
import { AuthApiError, fetchAuthSession } from '@/services/auth';
import { fetchWorkspaceLayout, saveWorkspaceLayout } from '@/services/product';
import { clampMapZoom, isWorldEventRegion, type WorldEventRegion } from '@/features/world-event-map';
import type { BootstrapPayload, MarketGroupSort } from '@/types';
export type MapViewMode = '3d' | '2d';
type WorkspaceSyncStatus = 'checking' | 'local' | 'saving' | 'synced' | 'conflict' | 'error';
const PANEL_STORAGE_KEY = 'polydata:workspace-panels:v4';
const PANEL_LAYOUT_STORAGE_KEY = 'polydata:workspace-panel-layout:v4';
const PANEL_LAYOUT_PROMOTION_STORAGE_KEY = 'polydata:workspace-panel-layout-promotions:v1';
const PROMOTED_WIDE_PANEL_IDS = ['breaking-event-radar', 'global-transport-shipping'];
const MARKET_GROUP_SORT_STORAGE_KEY = 'wm:marketGroupSort:v1';
export const DEFAULT_MAP_VIEW_MODE: MapViewMode = '2d';
const VIEW_STORAGE_KEY = 'polydata:map-view:v4';
const LIBRARY_STORAGE_KEY = 'polydata:panel-library-open:v1';
const WORKSPACE_SYNC_META_KEY = 'polydata:workspace-sync-meta:v1';
function isMapViewMode(value: unknown): value is MapViewMode {
  return value === '3d' || value === '2d';
}

function reorderPanelIds(panelIds: string[], draggedPanelId: string, targetPanelId: string, insertAfter: boolean) {
  if (draggedPanelId === targetPanelId) return panelIds;
  const next = panelIds.filter((panelId) => panelId !== draggedPanelId);
  const targetIndex = next.indexOf(targetPanelId);
  if (targetIndex === -1) return panelIds;
  next.splice(targetIndex + (insertAfter ? 1 : 0), 0, draggedPanelId);
  return next;
}

function sanitizePanelIds(panelIds: string[]) {
  const valid = new Set(PANEL_LIBRARY.map((panel) => panel.id));
  const unique: string[] = [];
  for (const panelId of panelIds) {
    if (!valid.has(panelId) || unique.includes(panelId)) continue;
    unique.push(panelId);
  }
  return unique;
}

function defaultWorkspacePanelIds(bootstrapPayload?: BootstrapPayload | null) {
  return sanitizePanelIds([
    ...DEFAULT_PANEL_IDS,
    ...(bootstrapPayload?.defaultWorkspace?.panels || []),
  ]);
}

function readJsonStorage<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function readStringStorage<T extends string>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  const raw = window.localStorage.getItem(key);
  return (raw as T) || fallback;
}

function readSearchParam(key: string): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get(key);
}

function readMarketGroupSortStorage(): MarketGroupSort {
  const saved = readStringStorage<string>(MARKET_GROUP_SORT_STORAGE_KEY, 'active');
  return saved === 'new'
    || saved === 'volume'
    || saved === 'active'
    || saved === 'close'
    || saved === 'move'
    || saved === 'trades'
    ? saved
    : 'active';
}

export function useWorkspacePreferences() {
  const accountLayoutApplied = useRef(false);
  const panelPreferencesOwned = useRef(false);
  const [layoutWidth, setLayoutWidth] = useState(() => typeof window === 'undefined' ? 1440 : window.innerWidth);
  useEffect(() => {
    const resize = () => setLayoutWidth(window.innerWidth);
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
  const enableAllPanels = () => updatePanelIds(sanitizePanelIds(PANEL_LIBRARY.map((panel) => panel.id)));
  const restorePanels = (bootstrap?: BootstrapPayload | null) => updatePanelIds(defaultWorkspacePanelIds(bootstrap));
  const [activePanelIds, setActivePanelIds] = useState<string[]>([]);
  const updatePanelIds = useCallback((value: string[] | ((current: string[]) => string[])) => {
    panelPreferencesOwned.current = true;
    setActivePanelIds(value);
  }, []);
  const applyBootstrapPanels = useCallback((payload: BootstrapPayload) => {
    if (accountLayoutApplied.current || panelPreferencesOwned.current) return;
    panelPreferencesOwned.current = true;
    setActivePanelIds(defaultWorkspacePanelIds(payload));
  }, []);
  const applyAccountPanels = useCallback((ids: string[]) => {
    accountLayoutApplied.current = true;
    setActivePanelIds(sanitizePanelIds(ids));
  }, []);
  const [panelLayoutPrefs, setPanelLayoutPrefs] = useState<PanelLayoutPrefs>(() => readJsonStorage<PanelLayoutPrefs>(PANEL_LAYOUT_STORAGE_KEY, {}));
  const [panelPrefsLoaded, setPanelPrefsLoaded] = useState(false);
  const [viewMode, setViewMode] = useState<MapViewMode>(() => {
    const override = readSearchParam('view');
    if (isMapViewMode(override)) return override;
    const saved = readStringStorage<string>(VIEW_STORAGE_KEY, DEFAULT_MAP_VIEW_MODE);
    return isMapViewMode(saved) ? saved : DEFAULT_MAP_VIEW_MODE;
  });
  const [showPanelLibrary, setShowPanelLibrary] = useState<boolean>(() => {
    const stored = readJsonStorage<boolean | null>(LIBRARY_STORAGE_KEY, null);
    if (stored !== null) return stored;
    return typeof window === 'undefined' || !window.matchMedia('(max-width: 720px)').matches;
  });
  const [marketGroupSort, setMarketGroupSort] = useState<MarketGroupSort>(() => readMarketGroupSortStorage());
  useEffect(() => {
    const saved = readJsonStorage<unknown>(PANEL_STORAGE_KEY, null);
    const hasSavedLayout = Array.isArray(saved) && saved.every((id) => typeof id === 'string');
    panelPreferencesOwned.current = hasSavedLayout;
    // An explicit empty list is a valid preference, not a first visit.
    setActivePanelIds(hasSavedLayout ? sanitizePanelIds(saved) : DEFAULT_PANEL_IDS);
    setPanelPrefsLoaded(true);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (window.localStorage.getItem(PANEL_LAYOUT_PROMOTION_STORAGE_KEY) === 'live-evidence-wide') return;
    setPanelLayoutPrefs((current) => {
      let changed = false;
      const next = { ...current };
      for (const panelId of PROMOTED_WIDE_PANEL_IDS) {
        const entry = next[panelId] || {};
        if ((entry.colSpan || 0) >= 2) continue;
        next[panelId] = { ...entry, colSpan: 2 };
        changed = true;
      }
      return changed ? next : current;
    });
    window.localStorage.setItem(PANEL_LAYOUT_PROMOTION_STORAGE_KEY, 'live-evidence-wide');
  }, []);

  useEffect(() => {
    if (!panelPrefsLoaded || typeof window === 'undefined') return;
    window.localStorage.setItem(PANEL_STORAGE_KEY, JSON.stringify(activePanelIds));
  }, [activePanelIds, panelPrefsLoaded]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(PANEL_LAYOUT_STORAGE_KEY, JSON.stringify(panelLayoutPrefs));
  }, [panelLayoutPrefs]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(VIEW_STORAGE_KEY, viewMode);
  }, [viewMode]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(LIBRARY_STORAGE_KEY, JSON.stringify(showPanelLibrary));
  }, [showPanelLibrary]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(MARKET_GROUP_SORT_STORAGE_KEY, marketGroupSort);
  }, [marketGroupSort]);

  const togglePanel = (panelId: string) => {
    updatePanelIds((current) => {
      if (current.includes(panelId)) return current.filter((candidate) => candidate !== panelId);
      return [...current, panelId];
    });
  };

  const moveWorkspacePanel = (draggedPanelId: string, targetPanelId: string, insertAfter: boolean) => {
    updatePanelIds((current) => reorderPanelIds(current, draggedPanelId, targetPanelId, insertAfter));
  };

  const resizeWorkspacePanel = (panelId: string, patch: { rowSpan?: number; colSpan?: number }) => {
    setPanelLayoutPrefs((current) => {
      const entry = current[panelId] || {};
      return {
        ...current,
        [panelId]: {
          ...entry,
          ...patch,
        },
      };
    });
  };

  const resetWorkspacePanelLayout = (panelId: string) => {
    setPanelLayoutPrefs((current) => {
      if (!current[panelId]) return current;
      const next = { ...current };
      delete next[panelId];
      return next;
    });
  };

  return { layoutWidth, applyBootstrapPanels, applyAccountPanels, enableAllPanels, restorePanels, activePanelIds, setActivePanelIds: updatePanelIds, panelLayoutPrefs, setPanelLayoutPrefs, panelPrefsLoaded, viewMode, setViewMode, showPanelLibrary, setShowPanelLibrary, marketGroupSort, setMarketGroupSort, togglePanel, moveWorkspacePanel, resizeWorkspacePanel, resetWorkspacePanelLayout };
}
export function useWorkspaceSync(workspace: ReturnType<typeof useWorkspacePreferences>, camera: {
  region: WorldEventRegion; mapZoom: number;
  setRegion: (region: WorldEventRegion) => void; setMapZoom: (zoom: number) => void;
}) {
  const { activePanelIds, panelLayoutPrefs, panelPrefsLoaded, viewMode, showPanelLibrary, marketGroupSort } = workspace;
  const { region, mapZoom } = camera;
  const value = useMemo(() => ({
    activePanelIds, panelLayout: panelLayoutPrefs,
    preferences: { region, viewMode, mapZoom, showPanelLibrary, marketGroupSort },
  }), [activePanelIds, panelLayoutPrefs, region, viewMode, mapZoom, showPanelLibrary, marketGroupSort]);
  const snapshot = JSON.stringify(value);
  const latest = useRef({ value, snapshot, workspace, camera });
  latest.current = { value, snapshot, workspace, camera };
  const [workspaceSyncStatus, setStatus] = useState<WorkspaceSyncStatus>('checking');
  const [workspaceSyncUpdatedAt, setUpdatedAt] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [hydration, setHydration] = useState(0);
  const owner = useRef<AbortController | null>(null);
  const revision = useRef(0);
  const ready = useRef(false);
  const writing = useRef(false);
  const applying = useRef(false);
  const acknowledged = useRef('');
  const localHydrated = useRef(false);
  const userId = useRef<number | string | null>(null);
  const timer = useRef<number>();
  const flush = useRef<() => void>(() => {});
  const schedule = () => {
    if (timer.current != null) window.clearTimeout(timer.current);
    if (ready.current && acknowledged.current !== latest.current.snapshot) {
      timer.current = window.setTimeout(() => flush.current(), 900);
    }
  };
  const meta = () => readJsonStorage<{ updatedAt?: string; userId?: number | string }>(WORKSPACE_SYNC_META_KEY, {});
  const markLocalChange = () => window.localStorage.setItem(WORKSPACE_SYNC_META_KEY,
    JSON.stringify({ updatedAt: new Date().toISOString(), userId: userId.current }));
  flush.current = () => {
    const controller = owner.current;
    if (!controller || controller.signal.aborted || !ready.current || writing.current || applying.current) return;
    const submitted = latest.current;
    if (acknowledged.current === submitted.snapshot) return;
    writing.current = true;
    setStatus('saving');
    void saveWorkspaceLayout({ revision: revision.current, ...submitted.value,
      clientUpdatedAt: meta().updatedAt || new Date().toISOString(),
    }, controller.signal).then((saved) => {
      if (controller.signal.aborted || owner.current !== controller) return;
      revision.current = saved.revision;
      acknowledged.current = submitted.snapshot;
      setUpdatedAt(saved.updatedAt);
      setStatus(submitted.snapshot === latest.current.snapshot ? 'synced' : 'saving');
    }).catch((error) => {
      if (controller.signal.aborted || owner.current !== controller) return;
      ready.current = false;
      setStatus(error instanceof AuthApiError && error.status === 409 ? 'conflict' : 'error');
    }).finally(() => {
      if (owner.current !== controller || controller.signal.aborted) return;
      writing.current = false;
      schedule();
    });
  };
  useEffect(() => {
    if (!panelPrefsLoaded) return;
    const controller = new AbortController();
    owner.current = controller;
    ready.current = false; writing.current = false;
    setStatus('checking');
    const started = latest.current.snapshot;
    const synchronize = async () => {
      const session = await fetchAuthSession(controller.signal);
      if (controller.signal.aborted) return;
      if (!session.authenticated || session.user?.forcePasswordChange) { setStatus('local'); return; }
      userId.current = session.user?.id ?? null;
      const server = await fetchWorkspaceLayout(controller.signal);
      if (controller.signal.aborted) return;
      const local = meta();
      const sameUser = local.userId == null || String(local.userId) === String(userId.current);
      const localTime = Date.parse(local.updatedAt || '');
      const serverTime = Date.parse(server.clientUpdatedAt || '');
      const newer = sameUser && (latest.current.snapshot !== started
        || (Number.isFinite(localTime) && (!Number.isFinite(serverTime) || localTime > serverTime)));
      if (!server.exists || newer) {
        const submitted = latest.current;
        const saved = await saveWorkspaceLayout({ revision: server.revision, ...submitted.value,
          clientUpdatedAt: (sameUser && local.updatedAt) || new Date().toISOString(),
        }, controller.signal);
        if (controller.signal.aborted) return;
        revision.current = saved.revision; acknowledged.current = submitted.snapshot;
        setUpdatedAt(saved.updatedAt);
      } else {
        applying.current = true;
        const { workspace: target, camera: map } = latest.current;
        target.applyAccountPanels(server.activePanelIds);
        const valid = new Set(PANEL_LIBRARY.map((panel) => panel.id));
        target.setPanelLayoutPrefs(Object.fromEntries(Object.entries(server.panelLayout || {}).filter(([id]) => valid.has(id))));
        const prefs = server.preferences || {};
        // URL camera and view always take precedence over account defaults.
        if (!readSearchParam('region') && !readSearchParam('center') && !readSearchParam('zoom') && isWorldEventRegion(prefs.region)) map.setRegion(prefs.region);
        if (!readSearchParam('view') && isMapViewMode(prefs.viewMode)) target.setViewMode(prefs.viewMode);
        if (!readSearchParam('zoom') && !readSearchParam('center') && prefs.mapZoom != null) map.setMapZoom(clampMapZoom(prefs.mapZoom));
        if (typeof prefs.showPanelLibrary === 'boolean') target.setShowPanelLibrary(prefs.showPanelLibrary);
        if (['active', 'new', 'volume', 'close', 'move', 'trades'].includes(prefs.marketGroupSort || '')) target.setMarketGroupSort(prefs.marketGroupSort as MarketGroupSort);
        revision.current = server.revision;
        setUpdatedAt(server.updatedAt);
        setHydration((version) => version + 1);
      }
      window.localStorage.setItem(WORKSPACE_SYNC_META_KEY, JSON.stringify({
        userId: userId.current, updatedAt: sameUser ? local.updatedAt : server.clientUpdatedAt,
      }));
      ready.current = true;
      setStatus('synced');
      if (!applying.current) schedule();
    };
    void synchronize().catch((error) => {
      if (!controller.signal.aborted) setStatus(error instanceof AuthApiError && error.status === 409 ? 'conflict' : 'error');
    });
    return () => {
      controller.abort(); ready.current = false;
      if (timer.current != null) window.clearTimeout(timer.current);
    };
  }, [panelPrefsLoaded, epoch]);
  useEffect(() => {
    if (!panelPrefsLoaded) return;
    if (applying.current) {
      applying.current = false; acknowledged.current = snapshot; localHydrated.current = true;
      return;
    }
    if (localHydrated.current) markLocalChange();
    else localHydrated.current = true;
    if (ready.current && acknowledged.current !== snapshot) setStatus('saving');
    schedule();
    return () => { if (timer.current != null) window.clearTimeout(timer.current); };
  }, [panelPrefsLoaded, snapshot, hydration]);
  const retryWorkspaceSync = () => {
    if (workspaceSyncStatus === 'conflict') window.localStorage.removeItem(WORKSPACE_SYNC_META_KEY);
    setEpoch((version) => version + 1);
  };
  return { workspaceSyncStatus, workspaceSyncUpdatedAt, retryWorkspaceSync };
}
