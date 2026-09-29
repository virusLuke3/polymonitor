import type { PanelRenderMap } from '@/panels/types';
import { AiMarketWidePanel } from '@/panels/shared/ai-market-wide';
import { panelFromRenderer } from '@/panels/definePanel';

const renderers: PanelRenderMap<'bootstrap' | 'globalOracle' | 'globalTrades' | 'latestContent' | 'marketGroups' | 'markets'> = {
  'oracle-timeline': {
    render: (ctx) => (
      <AiMarketWidePanel ctx={ctx} lens="trend" title="TREND WATCH" badge="TREND" />
    ),
  },
};

export const panel = panelFromRenderer(renderers, {
  contextKeys: ['bootstrap', 'globalOracle', 'globalTrades', 'latestContent', 'marketGroups', 'markets'],
  id: 'oracle-timeline',
  title: 'AI Trend Radar',
  eyebrow: 'agent',
  description: 'Market-wide AI synthesis of Polymarket trend clusters, catalysts, and watch items.',
  defaultEnabled: false,
  dataDependencies: ['alpha-signal', 'whale-tracker', 'suspicious-flow'],
});
