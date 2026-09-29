import { useEffect, useRef, useState } from 'preact/hooks';
import { fetchBootstrap, fetchLatestContent, fetchRecentOracle, fetchRecentTrades, fetchSystemHealth } from '@/services/api';
import { mergeRuntimeData } from '@/panels/runtime-store';
import type { usePanelRuntime } from '@/panels/usePanelRuntime';
import type { BootstrapPayload, ContentItem, OracleEvent, SystemHealth, TradeRow } from '@/types';
import type { useWorkspacePreferences } from './useWorkspacePreferences';

/** Bootstrap and the shared dashboard summaries have one request lifecycle. */
export function useDashboardData(workspace: Pick<ReturnType<typeof useWorkspacePreferences>, 'panelPrefsLoaded' | 'applyBootstrapPanels'>,
  runtime: Pick<ReturnType<typeof usePanelRuntime>, 'setRuntimeData'>) {
  const [bootstrap, setBootstrap] = useState<BootstrapPayload | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [globalTrades, setGlobalTrades] = useState<TradeRow[]>([]);
  const [globalOracle, setGlobalOracle] = useState<OracleEvent[]>([]);
  const [latestContent, setLatestContent] = useState<ContentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const runtimeRef = useRef(runtime);
  runtimeRef.current = runtime;
  const { panelPrefsLoaded, applyBootstrapPanels } = workspace;
  useEffect(() => {
    if (!panelPrefsLoaded) return;
    const controller = new AbortController();
    let refreshController: AbortController | null = null;
    const refreshed = { health: false, trades: false, oracle: false, content: false };
    const refresh = async () => {
      if (document.hidden || controller.signal.aborted || refreshController) return;
      const current = new AbortController();
      refreshController = current;
      const publish = <T,>(key: keyof typeof refreshed, commit: (value: T) => void) => (value: T) => {
        if (controller.signal.aborted || current.signal.aborted) return;
        refreshed[key] = true;
        commit(value);
      };
      // Each summary is independently useful; a slow source must not hold the
      // successful siblings in Promise.allSettled until their longest timeout.
      await Promise.allSettled([
        fetchSystemHealth(current.signal).then(publish('health', setHealth)),
        fetchRecentTrades(24, current.signal).then(publish('trades', setGlobalTrades)),
        fetchRecentOracle(16, current.signal).then(publish('oracle', setGlobalOracle)),
        fetchLatestContent(12, current.signal).then(publish('content', (value) => setLatestContent(value.items || []))),
      ]);
      if (refreshController === current) refreshController = null;
    };
    // Bootstrap is a fast preview, not a global readiness gate. Keep its real
    // response/error, but release independent sources after a bounded head start.
    let startupReleased = false;
    const releaseStartup = () => {
      if (controller.signal.aborted || startupReleased) return;
      startupReleased = true;
      setLoading(false);
      void refresh();
    };
    const startupTimer = window.setTimeout(releaseStartup, 1_200);
    void fetchBootstrap(controller.signal).then((payload) => {
      if (controller.signal.aborted) return;
      setBootstrap(payload);
      if (!refreshed.health) setHealth(payload.systemHealth || null);
      if (!refreshed.trades) setGlobalTrades(payload.globalTradesPreview || []);
      if (!refreshed.oracle) setGlobalOracle(payload.globalOraclePreview || []);
      if (!refreshed.content) setLatestContent(payload.latestContentPreview || []);
      applyBootstrapPanels(payload);
      runtimeRef.current.setRuntimeData((current) => mergeRuntimeData(current,
        payload.commoditiesPreview ? { 'commodities-watch': payload.commoditiesPreview } : {}));
    }).catch((caught) => {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Failed to load dashboard.');
    }).finally(() => {
      window.clearTimeout(startupTimer);
      releaseStartup();
    });
    const timer = window.setInterval(() => void refresh(), 20_000);
    const onVisibility = () => {
      if (document.hidden) { refreshController?.abort(); refreshController = null; }
      else void refresh();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => { controller.abort(); refreshController?.abort(); window.clearTimeout(startupTimer); window.clearInterval(timer); document.removeEventListener('visibilitychange', onVisibility); };
  }, [panelPrefsLoaded, applyBootstrapPanels]);
  return { bootstrap, health, globalTrades, globalOracle, latestContent, loading, error };
}
