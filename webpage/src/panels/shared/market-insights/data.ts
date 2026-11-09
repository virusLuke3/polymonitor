import type { MarketWideAiInsightLens } from '@/types';
import { fetchMarketWideAiSnapshot } from '@/services/api';
import { isInsight } from './model';
import { publicSnapshot } from '../../public-snapshot';

export function insightSnapshot(lens: MarketWideAiInsightLens) {
  return publicSnapshot({
    key: `market-insights:${lens}:v1`, version: 1, maxAgeMs: 12 * 3_600_000,
    updatedAt: value => isInsight(value, lens) ? Date.parse(value.snapshotGeneratedAt || value.generatedAt || '') : null,
    parse(value: unknown) {
      if (!isInsight(value, lens)) throw new Error('Invalid analysis snapshot.');
      const expires = Date.parse(value.snapshotExpiresAt || '');
      if (Number.isFinite(expires) && expires <= Date.now()) throw new Error('Analysis snapshot expired.');
      return value;
    },
  });
}

export async function fetchInsightSnapshot(lens: MarketWideAiInsightLens, signal?: AbortSignal) {
  const snapshot = await fetchMarketWideAiSnapshot(lens, 15000, signal);
  if (!isInsight(snapshot, lens)) throw new Error('Invalid analysis snapshot.');
  return snapshot;
}
