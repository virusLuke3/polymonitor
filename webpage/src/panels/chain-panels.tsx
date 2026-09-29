import type { RuntimeSignalPayload } from '@/types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from './types';
import { AiMarketWidePanel } from './shared/ai-market-wide';
import { tradeSignalList, whaleTrackerList } from './shared/renderers';


export const chainPanelRenderers: PanelRenderMap = {
  'sample-chain-trades': {
    render: (ctx) => (
      <AiMarketWidePanel ctx={ctx} lens="special" title="SPECIAL RADAR" badge="RADAR" />
    ),
  },
  'whale-tracker': {
    render: (ctx) => (
      <Panel title="WHALE TRACKER" badge="CHAIN" status="live" count={(ctx.runtimeData['whale-tracker'] as RuntimeSignalPayload | undefined)?.items.length || 0}>
        {whaleTrackerList((ctx.runtimeData['whale-tracker'] as RuntimeSignalPayload | undefined)?.items || [], 'No whale trades loaded.')}
      </Panel>
    ),
  },
  'suspicious-flow': {
    render: (ctx) => (
      <Panel title="FLOW WATCH" badge="CHAIN" status="live" count={(ctx.runtimeData['suspicious-flow'] as RuntimeSignalPayload | undefined)?.items.length || 0} className="wm-market-panel wm-flow-watch-panel">
        {tradeSignalList((ctx.runtimeData['suspicious-flow'] as RuntimeSignalPayload | undefined)?.items || [], 'No suspicious flow loaded.')}
      </Panel>
    ),
  },
};
