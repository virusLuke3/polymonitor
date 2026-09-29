import type { PanelRenderMap } from '@/panels/types';
import { AiMarketWidePanel } from '@/panels/shared/ai-market-wide';
import { panelFromRenderer } from '@/panels/definePanel';

const renderers: PanelRenderMap<'bootstrap' | 'globalOracle' | 'globalTrades' | 'latestContent' | 'marketGroups' | 'markets'> = {
  'price-implications': {
    render: (ctx) => <AiMarketWidePanel ctx={ctx} lens="overview" title="AI INSIGHTS" badge="LIVE" />,
  },
};

export const panel = panelFromRenderer(renderers, {
  contextKeys: ['bootstrap', 'globalOracle', 'globalTrades', 'latestContent', 'marketGroups', 'markets'],
  id: 'price-implications',
  title: 'AI Market Brief',
  eyebrow: 'agent',
  description: 'Market-wide AI brief, focal points, and convergence signals.',
  defaultEnabled: false,
  dataDependencies: ['alpha-signal', 'whale-tracker', 'suspicious-flow'],
});
