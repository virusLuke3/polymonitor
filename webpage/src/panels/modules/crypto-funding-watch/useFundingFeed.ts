import { usePanelResource, type PanelResource } from '@/panels/usePanelResource';
import { fetchRuntimeCryptoFundingWatch } from '@/services/api';
import { parseFunding, fundingStatusLabel, REFRESH_MS, MAX_AGE_MS, RETAIN_MS, type FundingPayload } from './model';

export const fundingResource: PanelResource<FundingPayload> = {
  key: 'funding:usdt-perpetual:latest:v3', title: 'Funding Rate',
  maxAgeMs: MAX_AGE_MS, staleAgeMs: RETAIN_MS, acceptStale: true,
  cache: { version: 3, maxChars: 512_000 },
  refreshPolicy: { tier: 'fast', intervalMs: REFRESH_MS, staleAfterMs: MAX_AGE_MS, requestTimeoutMs: 10_000 },
  fetch: context => fetchRuntimeCryptoFundingWatch(120, context?.signal), parse: parseFunding,
  updatedAt: value => Date.parse(value.generatedAt), statusLabel: fundingStatusLabel,
};

export const useFundingFeed = () => usePanelResource(fundingResource);
