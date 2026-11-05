import { expect, it } from 'vitest';
import { PANEL_REGISTRY, DEFAULT_PANEL_IDS } from '../../registry';
it('starts the real registry and enables both disclosure owners', () => {
  for (const id of ['company-events','policy-progress']) {
    expect(DEFAULT_PANEL_IDS).toContain(id);
    expect(PANEL_REGISTRY[id]?.fetchData).toBeTypeOf('function');
    expect(PANEL_REGISTRY[id]?.dataSourceId).toBeUndefined();
  }
});
