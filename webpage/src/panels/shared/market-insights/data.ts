import type { MarketWideAiInsightLens } from '@/types';
import { fetchMarketWideAiSnapshot } from '@/services/api';
import { isInsight } from './model';

export async function fetchInsightSnapshot(lens: MarketWideAiInsightLens, signal?: AbortSignal) {
  const snapshot = await fetchMarketWideAiSnapshot(lens, 8000, signal);
  if (!isInsight(snapshot, lens)) throw new Error('Invalid analysis snapshot.');
  return snapshot;
}
