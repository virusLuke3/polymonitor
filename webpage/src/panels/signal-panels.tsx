import type { RuntimeSignalPayload } from '@/types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from './types';
import { alphaSignalList } from './shared/renderers';

export const signalPanelRenderers: PanelRenderMap = {
  'alpha-signal': {
    render: (ctx) => (
      <Panel title="ALPHA SIGNAL" badge="LIVE" status="live" count={(ctx.runtimeData['alpha-signal'] as RuntimeSignalPayload | undefined)?.items.length || 0} className="wm-alpha-signal-panel">
        {alphaSignalList((ctx.runtimeData['alpha-signal'] as RuntimeSignalPayload | undefined)?.items || [], 'No alpha signals loaded.', ctx.setSelectedMarketId)}
      </Panel>
    ),
  },
};
