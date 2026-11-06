import type { Base, Race } from '../../shared/politics/model';
import { base, record, rows, validRace } from '../../shared/politics/model';
export type Payload = Base & { items?:Race[]; scope?:string; delegates:null; threshold:null };
export const valid = (v: unknown): v is Payload => record(v) && rows(v.items,validRace) && base(v);
