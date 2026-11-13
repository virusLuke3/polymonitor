import { fetchRuntimeFedRatesPolymarketGap } from '@/services/api';
import { createMacroDriverPanel } from '@/panels/shared/macro-driver';

export const panel = createMacroDriverPanel({
  panelId: 'fed-rates-polymarket-gap',
  title: 'FED / RATES GAP',
  badge: 'FRED',
  glyph: 'rates',
  driverLabel: 'Policy Market Driver',
  helpTitle: 'Fed Rates Polymarket Gap',
  helpText: 'Uses public Fed funds, SOFR, Treasury yields, and curve data to frame whether Polymarket Fed/rates markets are fighting the rates tape.',
  emptyTitle: 'FED GAP WARMING',
  name: 'Fed Rates Polymarket Gap',
  description: 'Rates tape and Polymarket Fed-market context.',
  limit: 8,
}, fetchRuntimeFedRatesPolymarketGap);
