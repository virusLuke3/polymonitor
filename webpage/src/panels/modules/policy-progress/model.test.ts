import { describe, expect, it } from 'vitest';
import { nextMilestone, category, validPolicyPayload, type Policy } from './model';
const item: Policy = {id:'rule',title:'Rule',type:'Rule',publishedAt:'2026-11-01',effectiveOn:null,commentsCloseOn:null,url:'https://www.federalregister.gov/documents/rule',pdfUrl:null,agencies:[]};
describe('policy evidence', () => {
  it('does not manufacture milestones or include past dates', () => {
    expect(nextMilestone([item], '2026-11-05')).toBeUndefined();
    expect(nextMilestone([{...item, effectiveOn:'2026-11-04'}], '2026-11-05')).toBeUndefined();
    expect(nextMilestone([{...item, effectiveOn:'2026-12-01',commentsCloseOn:'2026-11-05'}], '2026-11-05')?.kind).toBe('comments');
  });
  it('keeps proposals distinct from rules and rejects unsafe source URLs', () => {
    expect(category('Proposed Rule')).toBe('proposal');
    expect(validPolicyPayload({items:[{...item,url:'javascript:alert(1)'}],source:{lastSuccessAt:null,stale:true,usable:false}})).toBe(false);
  });
});
