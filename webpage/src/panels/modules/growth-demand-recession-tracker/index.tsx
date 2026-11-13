import { fetchRuntimeGrowthDemandRecessionTracker } from '@/services/api';
import { createMacroDriverPanel } from '@/panels/shared/macro-driver';

export const panel = createMacroDriverPanel({
  panelId: 'growth-demand-recession-tracker',
  title: 'GROWTH / DEMAND',
  badge: 'FRED',
  glyph: 'growth',
  driverLabel: 'Macro Demand Driver',
  helpTitle: 'Growth Demand Recession Tracker',
  helpText: 'Tracks retail sales, PCE, industrial production, GDP, and the yield curve to separate demand-driven inflation risk from recession-market risk.',
  emptyTitle: 'GROWTH WATCH WARMING',
  name: 'Growth Demand Recession Tracker',
  description: 'Demand and recession indicators for macro market positioning.',
  limit: 8,
}, fetchRuntimeGrowthDemandRecessionTracker);
