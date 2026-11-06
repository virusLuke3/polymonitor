import { fetchPolitics } from '@/services/api';
import { politicsContract } from '../../shared/politics/resource';
import { valid } from './model';
export const snapshot = politicsContract('politics-election', valid);
export const fetchData = (signal?: AbortSignal) => fetchPolitics('election', signal);
