import type { Base, Race } from '../../shared/politics/model';
import { base, record, rows, validRace, strings, finite } from '../../shared/politics/model';
export type DelegateContest = { id:string; party:string; year:number; candidate:string; delegates:number; eventDate:string; basis:string; delegateType:string; url:string; threshold:number|null };
export type Payload = Base & { items?:Race[]; scope?:string; delegates:null; threshold:null; delegateApplicability?:string; delegateContests?:DelegateContest[] };
export const valid = (v: unknown): v is Payload => record(v) && rows(v.items,validRace) && rows(v.delegateContests,r => strings(r,['id','party','candidate','eventDate','basis','delegateType','url']) && finite(r.delegates) && finite(r.year)) && base(v);
