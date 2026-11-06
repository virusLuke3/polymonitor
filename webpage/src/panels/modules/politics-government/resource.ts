import { fetchPolitics } from '@/services/api';
import { politicsContract } from '../../shared/politics/resource';
import { valid } from './model';
export const snapshot = politicsContract('politics-government', valid);
export const fetchData = (signal?: AbortSignal) => fetchPolitics('government', signal);
