import { useEffect, useState } from 'preact/hooks';
import { fetchCryptoReferenceInputs, fetchCryptoStrategyInputs } from '@/services/api';
import { usePanelResource, type PanelResource } from '@/panels/usePanelResource';
import { parseInputs, type Asset, type StrategyInputs } from './model';

export const cryptoStrategyResource: PanelResource<StrategyInputs> = {
  key: 'crypto-strategy:four-assets:v1', title: 'Crypto strategy inputs',
  maxAgeMs: 120000, staleAgeMs: 900000, acceptStale: true,
  refreshPolicy: { tier: 'fast', intervalMs: 15000, staleAfterMs: 120000, requestTimeoutMs: 12000 },
  fetch: context => fetchCryptoStrategyInputs(context?.signal), parse: parseInputs,
  updatedAt: value => Date.parse(value.generatedAt),
  statusLabel: value => value.status === 'stale' ? 'STALE' : value.status === 'partial' ? 'PARTIAL' : 'READY',
};
export const cryptoReferenceResource: PanelResource<StrategyInputs> = {
  ...cryptoStrategyResource, key: 'crypto-reference:market-data:v1', title: 'Contract reference',
  maxAgeMs: 15000,
  refreshPolicy: { tier: 'fast', intervalMs: 5000, staleAfterMs: 15000, requestTimeoutMs: 12000 },
  fetch: context => fetchCryptoReferenceInputs(context?.signal),
};
export const useCryptoInputs = (resource = cryptoStrategyResource) => usePanelResource(resource);

let currentAsset: Asset = 'BTC';
const subscribers = new Set<(value: Asset) => void>();
export function selectCryptoAsset(asset: Asset) {
  currentAsset = asset;
  subscribers.forEach(update => update(asset));
}
export function useCryptoAsset(): [Asset, (asset: Asset) => void] {
  const [asset, setAsset] = useState(currentAsset);
  useEffect(() => { subscribers.add(setAsset); return () => { subscribers.delete(setAsset); }; }, []);
  return [asset, selectCryptoAsset];
}
