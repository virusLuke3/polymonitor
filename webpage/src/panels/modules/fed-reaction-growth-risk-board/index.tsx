import { fetchRuntimeFedReactionGrowthRiskBoard } from '@/services/api';
import { createMacroRegistryPanel } from '@/panels/shared/macro-registry';

export const panel = createMacroRegistryPanel({
  panelId: 'fed-reaction-growth-risk-board',
  title: 'FED / GROWTH RISK',
  helpTitle: 'Fed Reaction Growth Risk Board',
  helpText: 'Merges Fed/rates and growth/demand seeds to explain the likely CPI-to-Fed reaction path without depending on Polymarket market rows.',
  emptyTitle: 'FED GROWTH WARMING',
  name: 'Fed Reaction / Growth Risk Board',
  description: 'Fed, rates, growth, demand, and recession-risk registry.',
  limit: 36,
  defaultEnabled: true,
}, fetchRuntimeFedReactionGrowthRiskBoard);
