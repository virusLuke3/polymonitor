import { politicsFreshnessMs } from '../../shared/politics/resource';
import { View } from './view';
import { runtimePanelFromRenderer } from '../../definePanel';
import { snapshot, fetchData } from './resource';
import type { Payload } from './model';
export const panel = runtimePanelFromRenderer({ 'politics-campaign-finance': { render: ctx => <View data={ctx.runtimeData['politics-campaign-finance'] as Payload | undefined}/> } }, {
 id: 'politics-campaign-finance', title: 'Campaign Finance', eyebrow: 'macro', description: 'Campaign Finance: sourced political facts with explicit scope.', defaultEnabled: true, snapshot,
}, { tier: 'slow', intervalMs: 1800000, staleAfterMs: politicsFreshnessMs('politics-campaign-finance'), requestTimeoutMs: 15000, retry: { attempts: 1, baseDelayMs: 5000, maxDelayMs: 5000 }, fetchData: context => fetchData(context?.signal) });
