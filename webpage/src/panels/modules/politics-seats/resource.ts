import { fetchPolitics } from '@/services/api';
import { politicsContract } from '../../shared/politics/resource';
import { validHouse as valid } from '../../shared/politics/model';
export const snapshot = politicsContract('politics-seats', valid);
export const fetchData = (signal?: AbortSignal) => fetchPolitics('seats', signal);
