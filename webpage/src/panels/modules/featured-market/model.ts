import type { MarketSummary, WorkspaceBundle } from '@/types';

export function marketRules(marketId: number | null, selected: MarketSummary | null, bundle: WorkspaceBundle | null) {
  if (marketId == null) return null;
  const candidates = [bundle?.market, selected].filter((market): market is MarketSummary => Boolean(market && market.id === marketId));
  const market = candidates[0];
  if (!market) return null;
  const oracle = bundle?.oracle?.marketId === marketId ? bundle.oracle : null;
  const chart = bundle?.chart?.marketId === marketId ? bundle.chart : null;
  const description = candidates.map(item => item.description?.trim()).find(Boolean);
  const seen = new Set([String(market.category || '').trim().toLowerCase()]);
  const tags = (market.tags || []).map(tag => tag.trim()).filter(tag => {
    const key = tag.toLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key); return true;
  }).slice(0, 4);
  return { market, tags, text: description || chart?.referenceRule?.trim() || null,
    oracle: market.oracle || oracle?.oracle, questionId: market.questionId || oracle?.questionId,
    ruleSource: description ? 'description' : chart?.referenceRule ? 'reference' : 'missing' } as const;
}
