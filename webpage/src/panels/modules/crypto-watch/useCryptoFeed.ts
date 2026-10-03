import { usePanelResource, type PanelResource } from '@/panels/usePanelResource';
import { fetchRuntimeCrypto } from '@/services/api';
import { parseCrypto, cryptoStatusLabel, REFRESH_MS, MAX_AGE_MS, RETAIN_MS, type CryptoPayload } from './model';

export const cryptoResource: PanelResource<CryptoPayload> = {
  key: 'crypto:global:rolling-24h:v1', title: 'Crypto',
  maxAgeMs: MAX_AGE_MS, staleAgeMs: RETAIN_MS, acceptStale: true,
  cache: { version: 1, maxChars: 128_000 },
  refreshPolicy: { tier: 'fast', intervalMs: REFRESH_MS, staleAfterMs: MAX_AGE_MS },
  fetch: context => fetchRuntimeCrypto(context?.signal), parse: parseCrypto,
  updatedAt: value => Date.parse(value.generatedAt), statusLabel: cryptoStatusLabel,
};
export const useCryptoFeed = () => usePanelResource(cryptoResource);
