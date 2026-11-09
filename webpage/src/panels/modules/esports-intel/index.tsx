import { runtimePanelFromRenderer } from '@/panels/definePanel';
import { BookmakerPanel } from '@/panels/shared/bookmakers/BookmakerPanel';
import { bookmakerSnapshot, type Payload } from '@/panels/shared/bookmakers/model';
import { fetchRuntimeGridEsports } from '@/services/api';

export const panel = runtimePanelFromRenderer({
  'esports-intel': { render: ctx => <BookmakerPanel game={true} payload={ctx.runtimeData['esports-intel'] as Payload | undefined} /> },
}, {
  id: 'esports-intel', title: 'Game', eyebrow: 'sports',
  description: 'Esports bookmaker comparison, official GRID series state and player props.',
  defaultEnabled: true, snapshot: bookmakerSnapshot(true),
}, {
  // GRID and bookmaker availability must not depend on another panel's batch.
  batch: false, requestTimeoutMs: 45000,
  tier: 'slow', intervalMs: 120000, staleAfterMs: 1800000,
  limit: 10, fetchData: (context, limit) => fetchRuntimeGridEsports(limit, context?.signal),
});
