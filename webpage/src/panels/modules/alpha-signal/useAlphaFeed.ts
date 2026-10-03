import { usePanelResource, type PanelResource } from '@/panels/usePanelResource';
import { fetchRuntimeAlpha } from '@/services/api';
import { ALPHA_LIMIT, ALPHA_MAX_AGE_MS, ALPHA_REFRESH_MS, ALPHA_RESOURCE_KEY, alphaStatusLabel, parseAlphaPayload, type AlphaPayload } from './model';

export const alphaResource: PanelResource<AlphaPayload> = {
  key: ALPHA_RESOURCE_KEY, title: 'Alpha Signal', maxAgeMs: ALPHA_MAX_AGE_MS,
  staleAgeMs: 15 * 60_000, cache: { version: 2, maxChars: 96_000 },
  refreshPolicy: { tier: 'fast', intervalMs: ALPHA_REFRESH_MS, staleAfterMs: ALPHA_MAX_AGE_MS },
  fetch: context => fetchRuntimeAlpha(ALPHA_LIMIT, context?.signal), parse: value => {
    const payload = parseAlphaPayload(value);
    // A failed ownership/source check is not a successful empty query. The
    // shared runtime retains the previous validated snapshot and marks failure.
    if (payload.status === 'degraded' && payload.readIntegrity !== 'invalid' && !payload.items.length && !payload.candidates.length) {
      throw new Error(payload.error || 'Alpha source verification failed');
    }
    return payload;
  },
  updatedAt: value => Date.parse(value.generatedAt), statusLabel: alphaStatusLabel,
  shouldPersist: value => value.readIntegrity === 'invalid' || ['ok', 'empty', 'partial'].includes(value.status),
};
export const useAlphaFeed = () => usePanelResource(alphaResource);
