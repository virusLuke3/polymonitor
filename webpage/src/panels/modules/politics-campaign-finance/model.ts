import type { Base } from '../../shared/politics/model';
import { base, record, strings, rows, optionalNumber } from '../../shared/politics/model';
export type Candidate = { id:string; name:string; party:string; state:string; district:string; office:string; receipts:number|null; spending:number|null; cash:number|null; debt:number|null; transfersIn:number|null; transfersOut:number|null; periodEnd:string|null; url:string }; export type Payload = Base & { items:Candidate[]; availableCount:number; cycle:string; independentExpenditures:unknown[] };
export const valid = (v: unknown): v is Payload => record(v) && rows(v.items,r => strings(r,['id','name','party','state','url']) && ['receipts','spending','cash','debt','transfersIn','transfersOut'].every(k=>optionalNumber(r[k]))) && base(v);
