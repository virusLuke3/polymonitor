import type { Base } from '../../shared/politics/model';
import { base, record, strings, rows, finite } from '../../shared/politics/model';
export type County = { id:string; sent:number; accepted:number; spoiled:number; receivedNotCounted:number; outstanding:number }; export type Payload = Base & { items?:County[]; totals?:Omit<County,'id'>; electionDate?:string; expectedCounties?:number };
export const valid = (v: unknown): v is Payload => record(v) && rows(v.items,r => strings(r,['id']) && ['sent','accepted','spoiled','receivedNotCounted','outstanding'].every(k=>finite(r[k]))) && (v.totals === undefined || record(v.totals) && Object.values(v.totals).every(finite)) && base(v);
