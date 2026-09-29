import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { fetchMarketFocusTile, fetchMarketGroupDetail, fetchMarketGroupChart, fetchMarketChart, fetchWorkspaceBundle } from '@/services/api';
import type {
  BootstrapPayload,
  MarketListItem,
  MarketGroupItem,
  MarketGroupDetail,
  MarketGroupChartPayload,
  MarketGroupChartRange,
  WorkspaceBundle,
} from '@/types';
import {
  pickDefaultMarketId,
  pickDefaultMarketGroup,
  pickDefaultGroupOutcome,
  findGroupForMarketId,
  outcomeKeyForGroupMarket,
  optimisticBundleFromMarket,
  optimisticBundleFromGroup,
  emptyWorkspaceBundle,
  bundleMatchesMarket,
  mergeWorkspaceBundle,
} from './marketBundle';
const MARKET_FOCUS_BROWSER_CACHE_MS = 15_000;
export function useMarketFocus({ bootstrap, markets, marketGroups, catalogLoaded }: { catalogLoaded: boolean; bootstrap: BootstrapPayload | null; markets: MarketListItem[]; marketGroups: MarketGroupItem[] }) {
  const [selectedMarketGroupId, setSelectedMarketGroupId] = useState<string | null>(null);
  const [selectedMarketGroupOutcomeKey, setSelectedMarketGroupOutcomeKey] = useState<string | null>(null);
  const [selectedMarketGroupDetail, setSelectedMarketGroupDetail] = useState<MarketGroupDetail | null>(null);
  const [selectedMarketGroupChart, setSelectedMarketGroupChart] = useState<MarketGroupChartPayload | null>(null);
  const [selectedMarketGroupChartRange, setSelectedMarketGroupChartRange] = useState<MarketGroupChartRange>('1d');
  const [bundle, setBundle] = useState<WorkspaceBundle | null>(null);
  const [selectedMarketId, setSelectedMarketId] = useState<number | null>(null);
  const [bundleLoading, setBundleLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bootstrapRef = useRef<BootstrapPayload | null>(null);
  const selectedMarketIdRef = useRef<number | null>(null);
  const selectedMarketGroupIdRef = useRef<string | null>(null);
  const bundleRequestSeqRef = useRef(0);
  const bundleCacheRef = useRef<Map<number, WorkspaceBundle>>(new Map());
  const bundleFocusUpdatedAtRef = useRef<Map<number, number>>(new Map());
  const focusTileInflightRef = useRef<Map<number, Promise<WorkspaceBundle>>>(new Map());
  bootstrapRef.current = bootstrap;
  selectedMarketIdRef.current = selectedMarketId;
  selectedMarketGroupIdRef.current = selectedMarketGroupId;
  const initializedRef = useRef(false);
  const catalogSelectionRef = useRef(false);
  const selectionTouchedRef = useRef(false);
  const chartRangeRef = useRef(selectedMarketGroupChartRange);
  chartRangeRef.current = selectedMarketGroupChartRange;
  const selectChartRange = (range: MarketGroupChartRange) => {
    chartRangeRef.current = range;
    setSelectedMarketGroupChartRange(range);
  };
  const focusControllersRef = useRef(new Map<number, AbortController>());
  useEffect(() => () => { focusControllersRef.current.forEach((controller) => controller.abort()); }, []);

  const loadMarketFocusTile = useCallback((marketId: number, force = false): Promise<WorkspaceBundle> => {
    const normalizedMarketId = Number(marketId);
    const cachedBundle = bundleCacheRef.current.get(normalizedMarketId);
    const cachedAt = bundleFocusUpdatedAtRef.current.get(normalizedMarketId) || 0;
    if (!force && cachedBundle && Date.now() - cachedAt <= MARKET_FOCUS_BROWSER_CACHE_MS) {
      return Promise.resolve(cachedBundle);
    }
    const inFlight = focusTileInflightRef.current.get(normalizedMarketId);
    if (inFlight) return inFlight;

    const controller = new AbortController();
    focusControllersRef.current.set(normalizedMarketId, controller);
    const request = fetchMarketFocusTile(normalizedMarketId, 2500, controller.signal)
      .then((loadedBundle) => {
        if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
        if (!bundleMatchesMarket(loadedBundle, normalizedMarketId)) throw new Error('Market focus identity mismatch');
        const current = bundleCacheRef.current.get(normalizedMarketId) || emptyWorkspaceBundle();
        const merged = mergeWorkspaceBundle(current, loadedBundle);
        bundleCacheRef.current.set(normalizedMarketId, merged);
        bundleFocusUpdatedAtRef.current.set(normalizedMarketId, Date.now());
        return merged;
      })
      .finally(() => {
        if (focusTileInflightRef.current.get(normalizedMarketId) === request) {
          focusTileInflightRef.current.delete(normalizedMarketId);
          focusControllersRef.current.delete(normalizedMarketId);
        }
      });
    focusTileInflightRef.current.set(normalizedMarketId, request);
    return request;
  }, []);

  const prefetchMarketFocus = useCallback((marketIds: number[]) => {
    const uniqueMarketIds = [...new Set(
      marketIds
        .map((marketId) => Number(marketId))
        .filter((marketId) => Number.isFinite(marketId) && marketId > 0),
    )].slice(0, 3);
    uniqueMarketIds.forEach((marketId) => {
      void loadMarketFocusTile(marketId).catch(() => undefined);
    });
  }, [loadMarketFocusTile]);

  const focusMarketGroup = (group: MarketGroupItem, outcomeKey?: string | null, marketId?: number | null, automatic = false) => {
    if (!automatic) selectionTouchedRef.current = true;
    const eventId = group.eventId != null ? String(group.eventId) : null;
    const selectedOutcome = pickDefaultGroupOutcome(group, outcomeKey, marketId);
    const nextMarketId = selectedOutcome?.marketId != null ? Number(selectedOutcome.marketId) : (marketId != null ? Number(marketId) : null);
    const nextOutcomeKey = selectedOutcome?.outcomeKey || outcomeKeyForGroupMarket(group, nextMarketId, outcomeKey);
    selectedMarketGroupIdRef.current = eventId;
    selectedMarketIdRef.current = nextMarketId;
    if (nextMarketId != null) {
      const optimisticBundle = optimisticBundleFromGroup(group, nextMarketId, nextOutcomeKey);
      const cachedFocusBundle = bundleCacheRef.current.get(nextMarketId);
      const hydratedBundle = cachedFocusBundle
        ? mergeWorkspaceBundle(cachedFocusBundle, optimisticBundle)
        : optimisticBundle;
      bundleCacheRef.current.set(nextMarketId, hydratedBundle);
      setBundle(hydratedBundle);
      setBundleLoading(false);
      setSelectedMarketGroupDetail(hydratedBundle.group || null);
    }
    setSelectedMarketGroupId(eventId);
    setSelectedMarketGroupOutcomeKey(nextOutcomeKey);
    setSelectedMarketId(nextMarketId);
  };

  const selectMarket = (marketId: number | null, automatic = false) => {
    if (!automatic) selectionTouchedRef.current = true;
    selectedMarketGroupIdRef.current = null;
    selectedMarketIdRef.current = marketId;
    setSelectedMarketGroupId(null);
    setSelectedMarketGroupOutcomeKey(null);
    setSelectedMarketId(marketId);
    setError(null);
  };
  const resetMarketSelection = () => {
    const group = pickDefaultMarketGroup(marketGroups);
    if (group) focusMarketGroup(group, group.defaultOutcomeKey, group.defaultMarketId);
    else selectMarket(pickDefaultMarketId(markets, bootstrap?.featuredMarket));
  };
  useEffect(() => {
    if (!bootstrap || initializedRef.current) return;
    initializedRef.current = true;
    if (selectionTouchedRef.current) return;
    const group = pickDefaultMarketGroup(bootstrap.activeMarketGroupsPreview || []);
    if (group) focusMarketGroup(group, group.defaultOutcomeKey, group.defaultMarketId, true);
    else selectMarket(pickDefaultMarketId(bootstrap.activeMarketsPreview || [], bootstrap.featuredMarket), true);
  }, [bootstrap]);
  useEffect(() => {
    const group = pickDefaultMarketGroup(marketGroups);
    if (!catalogLoaded || (catalogSelectionRef.current && !group)) return;
    initializedRef.current = true;
    catalogSelectionRef.current = true;
    if (selectionTouchedRef.current || selectedMarketGroupIdRef.current) return;
    if (group) focusMarketGroup(group, group.defaultOutcomeKey, group.defaultMarketId, true);
    else selectMarket(pickDefaultMarketId(markets, bootstrap?.featuredMarket), true);
  }, [catalogLoaded, bootstrap, markets, marketGroups]);

  useEffect(() => {
    if (selectedMarketId == null) {
      if (!selectedMarketGroupId) {
        setSelectedMarketGroupId(null);
        setSelectedMarketGroupOutcomeKey(null);
        setSelectedMarketGroupDetail(null);
        setSelectedMarketGroupChart(null);
      }
      return;
    }
    const matchedGroup = findGroupForMarketId(marketGroups, selectedMarketId);
    if (!matchedGroup) {
      if (selectedMarketGroupId || selectedMarketGroupDetail || selectedMarketGroupChart || selectedMarketGroupOutcomeKey) {
        setSelectedMarketGroupId(null);
        setSelectedMarketGroupOutcomeKey(null);
        setSelectedMarketGroupDetail(null);
        setSelectedMarketGroupChart(null);
      }
      return;
    }
    const nextEventId = matchedGroup.eventId != null ? String(matchedGroup.eventId) : null;
    const matchedOutcome = (matchedGroup.outcomes || []).find((outcome) => Number(outcome.marketId) === selectedMarketId) || null;
    if (nextEventId && nextEventId !== selectedMarketGroupId) {
      selectedMarketGroupIdRef.current = nextEventId;
      setSelectedMarketGroupId(nextEventId);
      setSelectedMarketGroupDetail(null);
      setSelectedMarketGroupChart(null);
    }
    const nextOutcomeKey = matchedOutcome?.outcomeKey || matchedGroup.defaultOutcomeKey || null;
    if (nextOutcomeKey && nextOutcomeKey !== selectedMarketGroupOutcomeKey) {
      setSelectedMarketGroupOutcomeKey(nextOutcomeKey);
    }
  }, [
    marketGroups,
    selectedMarketGroupChart,
    selectedMarketGroupDetail,
    selectedMarketGroupId,
    selectedMarketGroupOutcomeKey,
    selectedMarketId,
  ]);

  const selectedFocusDetailReady = Boolean(
    selectedMarketId
      && bundleMatchesMarket(bundle, selectedMarketId)
      && bundle?.focusStatus === 'ready'
      && bundle.group
      && (bundle.group.outcomes || []).length,
  );
  const selectedFocusChartReady = Boolean(
    selectedMarketId
      && bundleMatchesMarket(bundle, selectedMarketId)
      && (bundle?.chart?.points || []).length > 2
      && !['missing', 'snapshot', 'warming'].includes(String(bundle?.chart?.historyStatus || '').toLowerCase()),
  );

  useEffect(() => {
    if (!selectedMarketGroupId) {
      setSelectedMarketGroupDetail(null);
      return;
    }
    if (selectedFocusDetailReady) return;
    let cancelled = false;
    const controller = new AbortController();
    const eventId = selectedMarketGroupId;

    const timer = window.setTimeout(() => {
      fetchMarketGroupDetail(eventId, 3000, controller.signal)
        .then((detailPayload) => {
          if (cancelled || selectedMarketGroupIdRef.current !== eventId
            || (detailPayload.eventId != null && String(detailPayload.eventId) !== eventId)) return;
          setSelectedMarketGroupDetail(detailPayload);
          const liveDetailOutcome = pickDefaultGroupOutcome(detailPayload, selectedMarketGroupOutcomeKey, selectedMarketIdRef.current);
          if (liveDetailOutcome?.marketId != null && Number(liveDetailOutcome.marketId) !== selectedMarketIdRef.current) {
            selectedMarketIdRef.current = Number(liveDetailOutcome.marketId);
            setSelectedMarketId(Number(liveDetailOutcome.marketId));
          }
          setSelectedMarketGroupOutcomeKey(liveDetailOutcome?.outcomeKey || detailPayload.defaultOutcomeKey || null);
        })
        .catch(() => {
          // Keep the optimistic/focus-tile detail visible on a transient detail miss.
        });
    }, 2500);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [selectedFocusDetailReady, selectedMarketGroupId, selectedMarketGroupOutcomeKey]);

  useEffect(() => {
    if (!selectedMarketGroupId) {
      setSelectedMarketGroupChart(null);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    let timer: number | undefined;
    const eventId = selectedMarketGroupId;
    const chartRange = selectedMarketGroupChartRange;
    setSelectedMarketGroupChart(null);
    if (chartRange === '1d' && selectedFocusChartReady) return;

    timer = window.setTimeout(() => {
      fetchMarketGroupChart(eventId, chartRange, 3500, controller.signal)
        .then((chartPayload) => {
          if (!cancelled && selectedMarketGroupIdRef.current === eventId && chartRangeRef.current === chartRange
            && (chartPayload.eventId == null || String(chartPayload.eventId) === eventId) && chartPayload.range === chartRange) {
            setSelectedMarketGroupChart(chartPayload);
          }
        })
        .catch(() => {
          if (!cancelled && selectedMarketGroupIdRef.current === eventId && chartRangeRef.current === chartRange) {
            setSelectedMarketGroupChart(null);
          }
        });
    }, chartRange === '1d' ? 2500 : 150);

    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [selectedFocusChartReady, selectedMarketGroupChartRange, selectedMarketGroupId]);

  useEffect(() => {
    if (!selectedMarketId) return;
    if (selectedMarketGroupChartRange === '1d') return;
    let cancelled = false;
    const controller = new AbortController();
    const currentMarketId = selectedMarketId;
    const chartRange = selectedMarketGroupChartRange;

    fetchMarketChart(currentMarketId, chartRange, undefined, 12000, controller.signal)
      .then((chartPayload) => {
        if (cancelled || selectedMarketIdRef.current !== currentMarketId || chartRangeRef.current !== chartRange || chartPayload.marketId !== currentMarketId) return;
        setBundle((previous) => {
          const base = previous || bundleCacheRef.current.get(currentMarketId) || emptyWorkspaceBundle();
          const next = mergeWorkspaceBundle(base, { ...emptyWorkspaceBundle(), chart: chartPayload });
          bundleCacheRef.current.set(currentMarketId, next);
          return next;
        });
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [selectedMarketGroupChartRange, selectedMarketId]);

  useEffect(() => {
    if (!selectedMarketId) return;
    const currentMarketId = selectedMarketId;
    const requestSeq = ++bundleRequestSeqRef.current;
    let cancelled = false;
    const controller = new AbortController();
    const cachedBundle = bundleCacheRef.current.get(currentMarketId);
    const listMarket = markets.find((market) => market.id === currentMarketId)
      || bootstrapRef.current?.activeMarketsPreview?.find((market) => market.id === currentMarketId)
      || null;
    const listGroup = marketGroups.find((group) => {
      if (selectedMarketGroupId && String(group.eventId ?? '') === selectedMarketGroupId) return true;
      return [...(group.outcomes || []), ...(group.topOutcomes || [])].some((outcome) => Number(outcome.marketId) === currentMarketId);
    }) || null;
    const initialBundle = cachedBundle
      || (listMarket ? optimisticBundleFromMarket(listMarket) : null)
      || (listGroup ? optimisticBundleFromGroup(listGroup, currentMarketId, selectedMarketGroupOutcomeKey) : null)
      || emptyWorkspaceBundle();
    setBundle(initialBundle);
    setBundleLoading(!cachedBundle && !listMarket && !listGroup);
    if (!cachedBundle) {
      bundleCacheRef.current.set(currentMarketId, initialBundle);
    }

    function applyLoadedBundle(loadedBundle: WorkspaceBundle) {
      if (cancelled || bundleRequestSeqRef.current !== requestSeq || selectedMarketIdRef.current !== currentMarketId) return;
      if (!bundleMatchesMarket(loadedBundle, currentMarketId)) return;
      const loadedGroup = loadedBundle.group || null;
      const loadedEventId = loadedGroup?.eventId ?? loadedBundle.identity?.eventId ?? null;
      if (loadedGroup && loadedEventId != null) {
        const eventId = String(loadedEventId);
        selectedMarketGroupIdRef.current = eventId;
        setSelectedMarketGroupId(eventId);
        setSelectedMarketGroupDetail(loadedGroup);
        const liveLoadedOutcome = pickDefaultGroupOutcome(
          loadedGroup,
          loadedBundle.selectedOutcome?.outcomeKey || loadedBundle.identity?.selectedOutcomeKey || loadedGroup.defaultOutcomeKey || null,
          currentMarketId,
        );
        const nextOutcomeKey = liveLoadedOutcome?.outcomeKey
          || loadedBundle.selectedOutcome?.outcomeKey
          || loadedBundle.identity?.selectedOutcomeKey
          || outcomeKeyForGroupMarket(loadedGroup, currentMarketId, loadedGroup.defaultOutcomeKey || null);
        if (nextOutcomeKey) {
          setSelectedMarketGroupOutcomeKey(nextOutcomeKey);
        }
      }
      setBundle((previous) => {
        const base = previous || bundleCacheRef.current.get(currentMarketId) || initialBundle;
        const patch = chartRangeRef.current === '1d' || loadedBundle.chart?.range === chartRangeRef.current
          ? loadedBundle : { ...loadedBundle, chart: null };
        const next = mergeWorkspaceBundle(base, patch);
        bundleCacheRef.current.set(currentMarketId, next);
        return next;
      });
    }

    const loadFocusTile = (force = false) => loadMarketFocusTile(currentMarketId, force)
      .then((loadedBundle) => applyLoadedBundle(loadedBundle))
      .catch((loadError) => {
        if (!cancelled && bundleRequestSeqRef.current === requestSeq && !listMarket && !listGroup && !cachedBundle) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load market.');
        }
      })
      .finally(() => {
        if (!cancelled && bundleRequestSeqRef.current === requestSeq) {
          setBundleLoading(false);
        }
      });

    void loadFocusTile();
    const workspaceTimer = window.setTimeout(() => {
      if (cancelled || bundleRequestSeqRef.current !== requestSeq) return;
      fetchWorkspaceBundle(currentMarketId, { signal: controller.signal })
        .then((loadedBundle) => applyLoadedBundle(loadedBundle))
        .catch(() => undefined);
    }, 6500);
    const timer = window.setInterval(() => {
      if (cancelled || bundleRequestSeqRef.current !== requestSeq || document.visibilityState === 'hidden') return;
      void loadFocusTile(true);
    }, 20000);

    const loadingTimer = window.setTimeout(() => {
      if (!cancelled && bundleRequestSeqRef.current === requestSeq) {
        setBundleLoading(false);
      }
    }, 4500);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
      const focusController = focusControllersRef.current.get(currentMarketId);
      focusController?.abort();
      focusControllersRef.current.delete(currentMarketId);
      focusTileInflightRef.current.delete(currentMarketId);
      window.clearTimeout(workspaceTimer);
      window.clearTimeout(loadingTimer);
    };
  }, [loadMarketFocusTile, selectedMarketId]);

  useEffect(() => {
    if (!selectedMarketId || Number(bundle?.market?.id) === Number(selectedMarketId)) return;
    const selectedGroup = findGroupForMarketId(marketGroups, selectedMarketId);
    const selectedListMarket = markets.find((market) => Number(market.id) === Number(selectedMarketId)) || null;
    const optimistic = selectedGroup
      ? optimisticBundleFromGroup(selectedGroup, selectedMarketId, selectedMarketGroupOutcomeKey)
      : selectedListMarket
        ? optimisticBundleFromMarket(selectedListMarket)
        : null;
    if (!optimistic) return;
    setBundle((previous) => {
      const next = mergeWorkspaceBundle(previous, optimistic);
      bundleCacheRef.current.set(selectedMarketId, next);
      return next;
    });
  }, [bundle?.market?.id, marketGroups, markets, selectedMarketGroupOutcomeKey, selectedMarketId]);


  return {
    selectedMarketId, setSelectedMarketId: selectMarket, resetMarketSelection,
    selectedMarketGroupId, selectedMarketGroupOutcomeKey, setSelectedMarketGroupOutcomeKey,
    selectedMarketGroupDetail, selectedMarketGroupChart, selectedMarketGroupChartRange,
    setSelectedMarketGroupChartRange: selectChartRange,
    bundle, bundleLoading, error, focusMarketGroup, prefetchMarketFocus,
  };
}
