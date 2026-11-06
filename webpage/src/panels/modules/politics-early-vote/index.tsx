import { View } from './view';
import { runtimePanelFromRenderer } from '../../definePanel';
import { snapshot, fetchData } from './resource';
import type { Payload } from './model';
export const panel = runtimePanelFromRenderer({ 'politics-early-vote': { render: ctx => <View data={ctx.runtimeData['politics-early-vote'] as Payload | undefined}/> } }, {
 id: 'politics-early-vote', title: 'Early Vote', eyebrow: 'macro', description: 'Early Vote: sourced political facts with explicit scope.', defaultEnabled: true, snapshot,
}, { tier: 'slow', intervalMs: 600000, staleAfterMs: 3600000, requestTimeoutMs: 15000, retry: { attempts: 1, baseDelayMs: 5000, maxDelayMs: 5000 }, fetchData: context => fetchData(context?.signal) });
