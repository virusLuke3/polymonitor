import type { House } from '../../shared/politics/model';
import { base, record, validHouse } from '../../shared/politics/model';
export type Payload = House;
export const valid = (v: unknown): v is Payload => record(v) && validHouse(v) && base(v);
