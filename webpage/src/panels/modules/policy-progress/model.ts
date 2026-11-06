import { record, safeUrl, validSource, type Source } from '../../shared/official-disclosures';
import { base, rows, validBill, type Legislation } from '../../shared/politics/model';
export type Policy = { id: string; title: string; type: string; publishedAt: string; effectiveOn: string | null; commentsCloseOn: string | null; url: string; pdfUrl: string | null; agencies: string[] };
export type PolicyPayload = { panelId: string; schemaVersion: number; generatedAt: string; items: Policy[]; source: Source; availableCount: number; legislation?: Legislation };
export function validPolicyPayload(v: unknown): v is PolicyPayload {
  return record(v) && (v.legislation === undefined || record(v.legislation) && rows(v.legislation.items,validBill) && base(v.legislation)) && validSource(v.source) && Array.isArray(v.items) && v.items.length <= 100 && v.items.every(r => record(r) && ['id','title','type','publishedAt'].every(k => typeof r[k] === 'string') && safeUrl(r.url) && (r.pdfUrl === null || safeUrl(r.pdfUrl)) && ['effectiveOn','commentsCloseOn'].every(k => r[k] === null || typeof r[k] === 'string') && Array.isArray(r.agencies) && r.agencies.every(a => typeof a === 'string'));
}
export function nextMilestone(items: Policy[], today: string) {
  return items.flatMap(item => [
    ...(item.commentsCloseOn && item.commentsCloseOn >= today ? [{ item, date: item.commentsCloseOn, kind: 'comments' as const }] : []),
    ...(item.effectiveOn && item.effectiveOn >= today ? [{ item, date: item.effectiveOn, kind: 'effective' as const }] : []),
  ]).sort((a,b) => a.date.localeCompare(b.date))[0];
}
export const category = (type: string) => type === 'Rule' ? 'rule' : type === 'Proposed Rule' ? 'proposal' : type === 'Presidential Document' ? 'presidential' : 'notice';
