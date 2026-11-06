import { fetchPolitics } from '@/services/api';
import { politicsContract } from '../../shared/politics/resource';
import { valid } from './model';
export const snapshot = politicsContract('politics-campaign-finance', valid);
export const fetchData = (signal?: AbortSignal) => fetchPolitics('campaign-finance', signal);
