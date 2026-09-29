import { describe, expect, it } from 'vitest';
import type { MarketSummary, WorkspaceBundle } from '@/types';
import { marketRules } from './model';
const market: MarketSummary = { id: 2, title: 'Selected market', slug: 'selected', category: 'sports', tags: ['SPORTS', 'soccer', 'Soccer', 'awards'] };
describe('selected market rules', () => {
  it('does not fall back to another market or its chart and oracle fields', () => {
    const bundle = { market: { ...market, id: 1, description: 'Other rules' }, chart: { marketId: 1, referenceRule: 'Other reference' }, oracle: { marketId: 1, oracle: 'other-oracle' } } as WorkspaceBundle;
    expect(marketRules(2, market, bundle)).toMatchObject({ text: null, oracle: undefined });
    expect(marketRules(null, market, bundle)).toBeNull();
    expect(marketRules(3, market, bundle)).toBeNull();
  });
  it('deduplicates tags and uses only rules matching the selected identity', () => {
    const rules = marketRules(2, { ...market, description: 'Selected rules' }, null);
    expect(rules).toMatchObject({ text: 'Selected rules', tags: ['soccer', 'awards'], ruleSource: 'description' });
  });
});
