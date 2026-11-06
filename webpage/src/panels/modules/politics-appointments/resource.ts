import { fetchPolitics } from '@/services/api';
import { politicsContract } from '../../shared/politics/resource';
import { valid } from './model';
export const snapshot = politicsContract('politics-appointments', valid);
export const fetchData = (signal?: AbortSignal) => fetchPolitics('appointments', signal);
