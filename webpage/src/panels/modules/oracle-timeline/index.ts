import { oraclePanelRenderers } from '../../oracle-panels';
import { panelFromRenderer } from '../helpers';

export const panel = panelFromRenderer(oraclePanelRenderers, {
  id: 'oracle-timeline',
  title: 'AI Trend Radar',
  eyebrow: 'agent',
  description: 'Market-wide AI synthesis of Polymarket trend clusters, catalysts, and watch items.',
  defaultEnabled: false,
  dataDependencies: ['alpha-signal', 'whale-tracker', 'suspicious-flow'],
});
