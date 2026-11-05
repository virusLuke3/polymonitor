import { record, safeUrl, validSource, type Source } from '../../shared/official-disclosures';
export type Fact = { value: number; unit: string; start: string; end: string; filed: string; accession: string; form: string; concept: string };
export type Filing = { id: string; company: string; symbol: string; form: string; filed: string; publishedAt: string; period: string | null; url: string; amendment: boolean };
export type Company = { symbol: string; cik: string; filings: Filing[]; facts: { eps?: Fact; revenue?: Fact }; sources: { filings: Source; facts: Source } };
export type CompanyPayload = { panelId: string; schemaVersion: number; generatedAt: string; companies: Company[] };
const validFact = (v: unknown) => record(v) && typeof v.value === 'number' && Number.isFinite(v.value) && ['unit', 'start', 'end', 'filed', 'accession', 'form', 'concept'].every(k => typeof v[k] === 'string');
export function validCompanyPayload(v: unknown): v is CompanyPayload {
  return record(v) && Array.isArray(v.companies) && v.companies.length <= 8 && v.companies.every(c => record(c) && typeof c.symbol === 'string' && typeof c.cik === 'string' && record(c.sources) && validSource(c.sources.filings) && validSource(c.sources.facts) && record(c.facts) && Object.values(c.facts).every(validFact) && Array.isArray(c.filings) && c.filings.length <= 24 && c.filings.every(f => record(f) && ['id','company','symbol','form','filed','publishedAt'].every(k => typeof f[k] === 'string') && safeUrl(f.url)));
}
export function visibleFilings(company: Company | undefined, mode: 'all' | 'reports') {
  return (company?.filings || []).filter(f => mode === 'all' || /^10-[KQ]/.test(f.form));
}
