import type { Base } from '../../shared/politics/model';
import { base, record, strings, rows } from '../../shared/politics/model';
export type Payload = Base & { items: {id:string; title:string; subtype:string|null; publishedAt:string; signingDate:string|null; effectiveOn:string|null; executiveOrderNumber:string|null; proclamationNumber:string|null; url:string; pdfUrl:string|null; textUrl:string|null; executiveOrderNotes:string|null}[]; availableCount?:number; truncated?:boolean };
export const valid = (v: unknown): v is Payload => record(v) && rows(v.items,r => strings(r,['id','title','publishedAt','url'])) && base(v);
