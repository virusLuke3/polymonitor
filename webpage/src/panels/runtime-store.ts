import type { PanelModule, PanelRefreshTier, PanelRuntimeData } from './types';
import { fetchRuntimePanels } from '@/services/api';

const PANEL_RUNTIME_LIMITS: Record<string, number> = {
  'alpha-signal': 8,
  'polybeats-feed': 8,
  'cpi-components-pressure-registry': 48,
  'cpi-release-calendar': 8,
  'cpi-release-command-center': 36,
  'blockchain-policy-news': 12,
  'broker-research-watch': 12,
  'crypto-etf-flow': 8,
  'crypto-fear-greed': 6,
  'crypto-funding-watch': 18,
  'crypto-perp-funding': 10,
  'defi-security-watch': 12,
  'defi-token-watch': 10,
  'defi-yield-monitor': 10,
  'energy-gasoline-shock': 6,
  'espn-matchup-predictor': 8,
  'esports-intel': 3,
  'fed-reaction-growth-risk-board': 36,
  'food-retail-basket-pressure': 8,
  'geo-sanctions-shock': 6,
  'global-index-monitor': 12,
  'global-temperature-monitor': 60,
  'weather-market-browser': 60,
  'goods-tariff-supply-watch': 36,
  'ipo-news-watch': 12,
  'jin10-flash': 24,
  'labor-services-inflation-monitor': 36,
  'nba-intel': 12,
  'nba-scoreboard': 10,
  'new-market-signals': 12,
  'polymarket-macro-map': 12,
  'sports-odds': 8,
  'stablecoin-monitor': 8,
  'suspicious-flow': 12,
  'tradfi-perp-radar': 16,
  'weather-news': 24,
  'whale-tracker': 14,
};

export function buildRuntimeDataPatch(panelId: string, value: unknown): PanelRuntimeData {
  return { [panelId]: value };
}

export function getRefreshablePanels(panels: PanelModule[], tier: PanelRefreshTier): PanelModule[] {
  return panels.filter((panel) => panel.refresh?.tier === tier && typeof panel.fetchData === 'function');
}

export async function fetchPanelRuntimeData(
  panels: PanelModule[],
  onPanelData?: (panelId: string, value: unknown) => void,
  onPanelSettled?: (panelId: string) => void,
): Promise<PanelRuntimeData> {
  const entries = panels.filter((panel) => typeof panel.fetchData === 'function');
  const patch: PanelRuntimeData = {};
  if (entries.length > 1) {
    try {
      const ids = entries.map((panel) => panel.id);
      const payload = await fetchRuntimePanels(ids, PANEL_RUNTIME_LIMITS);
      const values = payload.panels || {};
      entries.forEach((panel) => {
        const value = values[panel.id];
        if (value !== undefined) {
          patch[panel.id] = value;
          onPanelData?.(panel.id, value);
        }
        onPanelSettled?.(panel.id);
      });
      return patch;
    } catch {
      // Fall back to individual panel requests if the batch route is unavailable.
    }
  }
  await Promise.all(entries.map(async (panel) => {
    try {
      const value = await panel.fetchData!();
      patch[panel.id] = value;
      onPanelData?.(panel.id, value);
    } catch {
      // Runtime panels are opportunistic; keep the last visible seed on transient misses.
    } finally {
      onPanelSettled?.(panel.id);
    }
  }));
  return patch;
}

export function mergeRuntimeData(current: PanelRuntimeData, patch: PanelRuntimeData): PanelRuntimeData {
  if (!Object.keys(patch).length) return current;
  const next = { ...current };
  for (const [panelId, value] of Object.entries(patch)) {
    const previous = current[panelId];
    if (hasItems(previous) && isEmptyWarming(value)) {
      continue;
    }
    next[panelId] = value;
  }
  return next;
}

function hasItems(value: unknown): boolean {
  return Boolean(
    value &&
    typeof value === 'object' &&
    Array.isArray((value as { items?: unknown[] }).items) &&
    ((value as { items?: unknown[] }).items?.length || 0) > 0,
  );
}

function isEmptyWarming(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  const payload = value as { items?: unknown[]; status?: unknown };
  return (!Array.isArray(payload.items) || payload.items.length === 0) && String(payload.status || '').toLowerCase() === 'warming';
}
