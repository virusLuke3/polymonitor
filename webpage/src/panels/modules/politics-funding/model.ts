import type { Legislation } from '../../shared/politics/model';
import { base, record, rows, validBill } from '../../shared/politics/model';
export type Payload = Legislation & { law?:{id:string; fiscalYear:number; expirationDate:string; expirationTime:null; expirationClause:string; currentCoverageVerified:boolean; url:string; coverage:{id:string;text:string}[]} };
export const valid = (v: unknown): v is Payload => record(v) && rows(v.items,validBill) && (v.law === undefined || record(v.law) && (v.law.expirationDate === undefined || typeof v.law.expirationDate === 'string') && rows(v.law.coverage,c => typeof c.id === 'string' && typeof c.text === 'string')) && base(v);
