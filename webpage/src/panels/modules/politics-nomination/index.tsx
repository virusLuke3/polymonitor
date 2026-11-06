import { View } from './view';
import { runtimePanelFromRenderer } from '../../definePanel';
import { snapshot, fetchData } from './resource';
import type { Payload } from './model';
export const panel = runtimePanelFromRenderer({ 'politics-nomination': { render: ctx => <View data={ctx.runtimeData['politics-nomination'] as Payload | undefined}/> } }, {
 id: 'politics-nomination', title: 'Nomination Path', eyebrow: 'macro', description: 'Nomination Path: sourced political facts with explicit scope.', defaultEnabled: true, snapshot,
}, { tier: 'slow', intervalMs: 600000, staleAfterMs: 3600000, requestTimeoutMs: 15000, retry: { attempts: 1, baseDelayMs: 5000, maxDelayMs: 5000 }, fetchData: context => fetchData(context?.signal) });
