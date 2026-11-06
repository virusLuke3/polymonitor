import type { Base, Race } from '../../shared/politics/model';
import { base, record, strings, rows, validRace, finite } from '../../shared/politics/model';
export type Payload = Base & { polls: { id:string; race:string; date:string; pollster:string; sample:number|null; population:string; marginOfError:number|null; results:{name:string;value:number}[]; url:string; }[]; pollCount:number; attribution:string; results:Race[]; defaultPhase:string; certifications:unknown[] };
export const valid = (v: unknown): v is Payload => record(v) && rows(v.polls,p => strings(p,['id','race','date','pollster','population']) && Array.isArray(p.results) && rows(p.results,r => typeof r.name === 'string' && finite(r.value))) && rows(v.results,validRace) && base(v);
