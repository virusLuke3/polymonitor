import type { RuntimeSignalPayload } from '@/types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { alphaSignalList } from '@/panels/shared/renderers';
import { fetchRuntimeAlpha } from '@/services/api';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

const renderers: PanelRenderMap<'setSelectedMarketId'> = {
  'alpha-signal': {
    render: (ctx) => (
      <Panel title="ALPHA SIGNAL" badge="LIVE" status="live" count={(ctx.runtimeData['alpha-signal'] as RuntimeSignalPayload | undefined)?.items.length || 0} className="wm-alpha-signal-panel">
        {alphaSignalList((ctx.runtimeData['alpha-signal'] as RuntimeSignalPayload | undefined)?.items || [], 'No alpha signals loaded.', ctx.setSelectedMarketId)}
      </Panel>
    ),
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  contextKeys: ['setSelectedMarketId'],
  id: 'alpha-signal',
  title: 'Alpha Signal',
  eyebrow: 'signal',
  description: 'Cross-source heuristic signal stack.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  limit: 8,
  fetchData: (context, limit) => fetchRuntimeAlpha(limit, context?.signal),
});
