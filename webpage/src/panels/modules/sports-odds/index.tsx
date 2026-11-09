import { runtimePanelFromRenderer } from '@/panels/definePanel';
import { BookmakerPanel } from '@/panels/shared/bookmakers/BookmakerPanel';
import { bookmakerSnapshot, type Payload } from '@/panels/shared/bookmakers/model';
import { fetchRuntimeSportsOdds } from '@/services/api';

export const panel = runtimePanelFromRenderer({
  'sports-odds': { render: ctx => <BookmakerPanel game={false} payload={ctx.runtimeData['sports-odds'] as Payload | undefined} /> },
}, {
  id: 'sports-odds', title: 'Sports', eyebrow: 'sports',
  description: 'Sports bookmaker comparison, exact market lines and official standings.',
  defaultEnabled: true, snapshot: bookmakerSnapshot(false),
}, {
  // Large, independent snapshots must not queue behind unrelated batch readers.
  batch: false, requestTimeoutMs: 45000,
  tier: 'slow', intervalMs: 300000, staleAfterMs: 1800000,
  limit: 8, fetchData: (context, limit) => fetchRuntimeSportsOdds(limit, context?.signal),
});
