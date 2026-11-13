import { fetchPolitics } from '@/services/api';
import { politicsContract } from '../../shared/politics/resource';
import { validHouse as valid } from '../../shared/politics/model';
export const snapshot = politicsContract('politics-government', valid);
export const fetchData = (signal?: AbortSignal) => fetchPolitics('government', signal);
