import { View } from './view';
import { runtimePanelFromRenderer } from '../../definePanel';
import { snapshot, fetchData } from './resource';
import type { Payload } from './model';
export const panel = runtimePanelFromRenderer({ 'politics-funding': { render: ctx => <View data={ctx.runtimeData['politics-funding'] as Payload | undefined}/> } }, {
 id: 'politics-funding', title: 'Funding Deadline', eyebrow: 'macro', description: 'Funding Deadline: sourced political facts with explicit scope.', defaultEnabled: true, snapshot,
}, { tier: 'slow', intervalMs: 300000, staleAfterMs: 3600000, requestTimeoutMs: 15000, retry: { attempts: 1, baseDelayMs: 5000, maxDelayMs: 5000 }, fetchData: context => fetchData(context?.signal) });
