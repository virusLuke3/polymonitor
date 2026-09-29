import type { RuntimeSignalPayload } from '@/types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { tradeSignalList } from '@/panels/shared/renderers';
import { fetchRuntimeSuspicious } from '@/services/api';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

const renderers: PanelRenderMap = {
  'suspicious-flow': {
    render: (ctx) => (
      <Panel title="FLOW WATCH" badge="CHAIN" status="live" count={(ctx.runtimeData['suspicious-flow'] as RuntimeSignalPayload | undefined)?.items.length || 0} className="wm-market-panel wm-flow-watch-panel">
        {tradeSignalList((ctx.runtimeData['suspicious-flow'] as RuntimeSignalPayload | undefined)?.items || [], 'No suspicious flow loaded.')}
      </Panel>
    ),
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'suspicious-flow',
  title: 'Flow Watch',
  eyebrow: 'chain',
  description: 'Oracle-adjacent and large live trade flow.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  limit: 12,
  fetchData: (context, limit) => fetchRuntimeSuspicious(limit, context?.signal),
});
