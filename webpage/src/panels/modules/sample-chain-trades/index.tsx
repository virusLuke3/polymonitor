import type { PanelRenderMap } from '@/panels/types';
import { AiMarketWidePanel } from '@/panels/shared/ai-market-wide';
import { panelFromRenderer } from '@/panels/definePanel';

const renderers: PanelRenderMap<'bootstrap' | 'globalOracle' | 'globalTrades' | 'latestContent' | 'marketGroups' | 'markets'> = {
  'sample-chain-trades': {
    render: (ctx) => (
      <AiMarketWidePanel ctx={ctx} lens="special" title="SPECIAL RADAR" badge="RADAR" />
    ),
  },
};

export const panel = panelFromRenderer(renderers, {
  contextKeys: ['bootstrap', 'globalOracle', 'globalTrades', 'latestContent', 'marketGroups', 'markets'],
  id: 'sample-chain-trades',
  title: 'AI Special Markets',
  eyebrow: 'agent',
  description: 'Market-wide AI radar for unusual, high-attention, and fast-moving markets.',
  defaultEnabled: false,
  dataDependencies: ['alpha-signal', 'whale-tracker', 'suspicious-flow'],
});
