import type { Base } from '../../shared/politics/model';
import { base, record, strings, rows } from '../../shared/politics/model';
export type Confirmation = {id:string; name:string; office:string; submittedAt:string; confirmedAt:string; stage:string; url:string};
export type Hearing = {id:string; title:string; heldDates:string[]; committee:string[]; witnesses:string[]; congress:string; url:string; publishedAt:string};
export type Payload = Base & { items?: {id:string; title:string; url:string; publishedAt:string; stage:string; text:string}[]; confirmations:Confirmation[]; hearings:Hearing[]; confirmationCount?:number; confirmationPublishedAt?:string; hearingTargetCount?:number };
export const valid = (v: unknown): v is Payload => record(v) && rows(v.items,r => strings(r,['id','title','url','publishedAt','text'])) && rows(v.confirmations,r => strings(r,['id','name','office','submittedAt','confirmedAt','stage','url'])) && rows(v.hearings,r => strings(r,['id','title','congress','url','publishedAt']) && ['heldDates','committee','witnesses'].every(k => Array.isArray(r[k]) && (r[k] as unknown[]).every(v=>typeof v==='string'))) && base(v);
