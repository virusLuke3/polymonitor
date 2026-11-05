import { expect, it } from 'vitest';
import { contract } from '../../shared/official-disclosures';
import { validCompanyPayload } from './model';
it('rejects cross-panel snapshots and malformed company facts', () => {
  expect(() => contract('company-events',validCompanyPayload).parse({panelId:'policy-progress',schemaVersion:1,generatedAt:'2026-11-05T00:00:00Z',companies:[]})).toThrow();
  expect(validCompanyPayload({companies:[{symbol:'AAPL',cik:'0000320193',filings:[],facts:{eps:{value:'2.0'}},sources:{}}]})).toBe(false);
});
