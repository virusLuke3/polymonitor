import type { RuntimeSignalPayload } from '@/types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { whaleTrackerList } from '@/panels/shared/renderers';
import { fetchRuntimeWhales } from '@/services/api';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

const renderers: PanelRenderMap = {
  'whale-tracker': {
    render: (ctx) => (
      <Panel title="WHALE TRACKER" badge="CHAIN" status="live" count={(ctx.runtimeData['whale-tracker'] as RuntimeSignalPayload | undefined)?.items.length || 0}>
        {whaleTrackerList((ctx.runtimeData['whale-tracker'] as RuntimeSignalPayload | undefined)?.items || [], 'No whale trades loaded.')}
      </Panel>
    ),
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'whale-tracker',
  title: 'Whale Tracker',
  eyebrow: 'chain',
  description: 'Largest recent on-chain trades.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  limit: 14,
  fetchData: (context, limit) => fetchRuntimeWhales(limit, context?.signal),
});
