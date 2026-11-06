import type { Base } from '../../shared/politics/model';
import { base, record, strings, rows } from '../../shared/politics/model';
export type Payload = Base & { items?: {id:string; title:string; url:string; publishedAt:string; stage:string; text:string}[]; confirmations:unknown[]; hearings:unknown[] };
export const valid = (v: unknown): v is Payload => record(v) && rows(v.items,r => strings(r,['id','title','url','publishedAt','text'])) && base(v);
