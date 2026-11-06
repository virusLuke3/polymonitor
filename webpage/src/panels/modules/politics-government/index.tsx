import { politicsFreshnessMs } from '../../shared/politics/resource';
import { View } from './view';
import { runtimePanelFromRenderer } from '../../definePanel';
import { snapshot, fetchData } from './resource';
import type { Payload } from './model';
export const panel = runtimePanelFromRenderer({ 'politics-government': { render: ctx => <View data={ctx.runtimeData['politics-government'] as Payload | undefined}/> } }, {
 id: 'politics-government', title: 'Government Formation', eyebrow: 'macro', description: 'Government Formation: sourced political facts with explicit scope.', defaultEnabled: true, snapshot,
}, { tier: 'slow', intervalMs: 600000, staleAfterMs: politicsFreshnessMs('politics-government'), requestTimeoutMs: 15000, retry: { attempts: 1, baseDelayMs: 5000, maxDelayMs: 5000 }, fetchData: context => fetchData(context?.signal) });
