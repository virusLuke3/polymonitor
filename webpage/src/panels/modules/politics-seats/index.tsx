import { View } from './view';
import { runtimePanelFromRenderer } from '../../definePanel';
import { snapshot, fetchData } from './resource';
import type { Payload } from './model';
export const panel = runtimePanelFromRenderer({ 'politics-seats': { render: ctx => <View data={ctx.runtimeData['politics-seats'] as Payload | undefined}/> } }, {
 id: 'politics-seats', title: 'Seat Balance', eyebrow: 'macro', description: 'Seat Balance: sourced political facts with explicit scope.', defaultEnabled: true, snapshot,
}, { tier: 'slow', intervalMs: 600000, staleAfterMs: 3600000, requestTimeoutMs: 15000, retry: { attempts: 1, baseDelayMs: 5000, maxDelayMs: 5000 }, fetchData: context => fetchData(context?.signal) });
