import { usePanelResource } from '@/panels/usePanelResource';
import { marketChartResource, marketDetailResource } from './resources';
import { useEffect, useRef, useState } from 'preact/hooks';
import { fetchMarketFlow, fetchMarketOracle } from '@/services/api';
import type { BootstrapPayload, MarketListItem, MarketGroupItem, MarketGroupDetail, MarketGroupChartPayload, MarketGroupChartRange, WorkspaceBundle } from '@/types';
import { pickDefaultMarketId, pickDefaultGroupOutcome, optimisticBundleFromMarket, optimisticBundleFromGroup, emptyWorkspaceBundle, bundleMatchesMarket, mergeWorkspaceBundle } from './marketBundle';
import { pollPanel } from './pollPanel';

const SELECTED_MARKET_KEY = 'wm:selectedMarket:v1';

export function useMarketFocus({ bootstrap, markets, marketGroups, catalogLoaded }: {
  catalogLoaded: boolean; bootstrap: BootstrapPayload | null; markets: MarketListItem[]; marketGroups: MarketGroupItem[];
}) {
  const [selectedMarketId, setMarketId] = useState<number | null>(null);
  const [selectedMarketGroupId, setGroupId] = useState<string | null>(null);
  const [selectedMarketGroupOutcomeKey, setSelectedMarketGroupOutcomeKey] = useState<string | null>(null);
  const [selectedMarketGroupDetail, setGroupDetail] = useState<MarketGroupDetail | null>(null);
  const [selectedMarketGroupChartRange, setSelectedMarketGroupChartRange] = useState<MarketGroupChartRange>('1d');
  const [bundle, setBundle] = useState<WorkspaceBundle | null>(null);
  const [bundleLoading, setBundleLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = useRef<number | null>(null);
  const touched = useRef(false);
  const initialized = useRef(false);
  const missingSelection = useRef<number | null>(null);
  const latestMarkets = useRef(markets);
  latestMarkets.current = markets;

  const selectMarket = (marketId: number | null, automatic = false) => {
    missingSelection.current = null;
    if (!automatic) touched.current = true;
    if (selected.current === marketId) return;
    selected.current = marketId;
    setMarketId(marketId); setGroupId(null); setGroupDetail(null); setSelectedMarketGroupOutcomeKey(null);
    const market = latestMarkets.current.find((row) => row.id === marketId);
    setBundle(market ? optimisticBundleFromMarket(market) : emptyWorkspaceBundle());
    setError(null);
  };
  const focusMarketGroup = (group: MarketGroupItem, outcomeKey?: string | null, marketId?: number | null) => {
    missingSelection.current = null;
    touched.current = true;
    const outcome = pickDefaultGroupOutcome(group, outcomeKey, marketId);
    const id = outcome?.marketId ?? marketId ?? null;
    selected.current = id;
    setMarketId(id); setGroupId(group.eventId == null ? null : String(group.eventId));
    setGroupDetail({ ...group, generatedAt: group.generatedAt || undefined }); setSelectedMarketGroupOutcomeKey(outcome?.outcomeKey || null);
    // A group without a local identity must clear the previous market too.
    setBundle(optimisticBundleFromGroup(group, id, outcome?.outcomeKey || null));
    setError(null);
  };
  const resetMarketSelection = () => selectMarket(pickDefaultMarketId(markets, bootstrap?.featuredMarket));
  useEffect(() => {
    if (!catalogLoaded || initialized.current || touched.current || !markets.length) return;
    initialized.current = true;
    let saved = 0;
    try { saved = Number(window.localStorage.getItem(SELECTED_MARKET_KEY)); } catch { /* Storage may be blocked. */ }
    selectMarket(Number.isSafeInteger(saved) && saved > 0 ? saved : pickDefaultMarketId(markets), true);
  }, [catalogLoaded, markets]);
  useEffect(() => {
    if (selectedMarketId) {
      try { window.localStorage.setItem(SELECTED_MARKET_KEY, String(selectedMarketId)); } catch { /* Optional preference. */ }
    }
  }, [selectedMarketId]);

  const detailFeed = usePanelResource(marketDetailResource(selectedMarketId, () => {
    if (selected.current !== selectedMarketId) return;
    missingSelection.current = selectedMarketId;
    const fallback = pickDefaultMarketId(latestMarkets.current);
    // Empty catalog during an outage is not an explicit user deselection.
    if (fallback != null && fallback !== selectedMarketId) selectMarket(fallback, true);
  }), selectedMarketId != null);
  useEffect(() => {
    if (!catalogLoaded || !markets.length || missingSelection.current == null
      || missingSelection.current !== selected.current) return;
    const fallback = pickDefaultMarketId(markets);
    if (fallback != null && fallback !== missingSelection.current) selectMarket(fallback, true);
    else {
      missingSelection.current = null;
      void detailFeed.refresh();
    }
  }, [catalogLoaded, markets]);
  const chartFeed = usePanelResource(marketChartResource(selectedMarketId, selectedMarketGroupChartRange), selectedMarketId != null);
  useEffect(() => {
    const value = detailFeed.data;
    if (value && selectedMarketId != null && bundleMatchesMarket(value, selectedMarketId)) {
      setBundle(previous => ({ ...mergeWorkspaceBundle(previous, value), focusStatus: detailFeed.error ? 'unavailable' : value.focusStatus }));
    } else if (detailFeed.expired) {
      setBundle(previous => previous ? { ...previous, market: null, price: null, focusStatus: 'unavailable' } : previous);
    }
    setBundleLoading(Boolean(selectedMarketId && !value && !latestMarkets.current.some(row => row.id === selectedMarketId) && !detailFeed.error));
    setError(detailFeed.error);
  }, [detailFeed.data, detailFeed.error, detailFeed.expired, selectedMarketId]);
  useEffect(() => {
    const chart = chartFeed.data;
    setBundle(base => base ? { ...base, chart: chart && chart.marketId === selectedMarketId && chart.range === selectedMarketGroupChartRange
      ? chartFeed.error || chartFeed.status.phase === 'stale' ? { ...chart, historyStatus: 'stale' } : chart : null } : base);
  }, [chartFeed.data, chartFeed.error, chartFeed.status.phase, selectedMarketId, selectedMarketGroupChartRange]);

  useEffect(() => {
    if (!selectedMarketId) { setBundleLoading(false); return; }
    const id = selectedMarketId;
    let alive = true;
    let lastFlowSuccess = 0;
    let lastOracleSuccess = 0;
    const current = () => alive && selected.current === id;
    const update = (change: (base: WorkspaceBundle) => WorkspaceBundle) => {
      if (!current()) return;
      setBundle((previous) => change(bundleMatchesMarket(previous, id) ? previous! : emptyWorkspaceBundle()));
    };
    const stopOracle = pollPanel(
      (signal) => fetchMarketOracle(id, signal),
      (value) => { if (value.marketId === id) { lastOracleSuccess = Date.now(); update((base) => ({ ...base, oracle: value })); } },
      () => update((base) => ({ ...base, oracle: {
        ...(Date.now() - lastOracleSuccess <= 120_000 ? base.oracle : null), marketId: id,
        timeline: Date.now() - lastOracleSuccess <= 120_000 ? base.oracle?.timeline || [] : [],
        status: lastOracleSuccess && Date.now() - lastOracleSuccess <= 120_000 ? 'stale' : 'unavailable',
      } })),
      20_000, 500,
    );
    const stopFlow = pollPanel(
      (signal) => fetchMarketFlow(id, signal),
      (value) => {
        if (value.marketId !== id) return;
        lastFlowSuccess = Date.now();
        update((base) => ({ ...base, trades: value.items, flowStatus: value.status,
          flowCoverage: value.coverage, flowSourceUpdatedAt: value.sourceUpdatedAt }));
      },
      () => update((base) => ({ ...base, trades: Date.now() - lastFlowSuccess <= 60_000 ? base.trades : [],
        flowStatus: lastFlowSuccess && Date.now() - lastFlowSuccess <= 60_000 ? 'stale' : 'unavailable' })),
      10_000, 1000,
    );
    return () => { alive = false; stopOracle(); stopFlow(); };
  }, [selectedMarketId]);

  const selectedMarketGroupChart: MarketGroupChartPayload | null = null;
  void marketGroups;
  return {
    selectedMarketId, setSelectedMarketId: selectMarket, resetMarketSelection,
    selectedMarketGroupId, selectedMarketGroupOutcomeKey, setSelectedMarketGroupOutcomeKey,
    selectedMarketGroupDetail, selectedMarketGroupChart, selectedMarketGroupChartRange,
    setSelectedMarketGroupChartRange, bundle, bundleLoading, error, focusMarketGroup,
  };
}
