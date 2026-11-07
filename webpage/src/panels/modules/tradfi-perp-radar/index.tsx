import { createFinanceWatchPanel } from '@/panels/shared/finance-watch';

export const panel = createFinanceWatchPanel({
  id: 'tradfi-perp-radar',
  title: 'TRADFI PERPS',
  description: 'Tokenized stock, index, and commodity perp radar.',
  question: 'OKX perpetuals with source mark, index, funding forecasts and contract-unit volumes; futures reference quotes are shown separately.',
  limit: 24,
});
