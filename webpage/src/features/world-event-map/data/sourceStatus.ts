import type { GeoEventAdapterResult, GeoEventSourceStatus } from '../domain/types';

export type WorldEventSourceStatus = {
  key: string;
  label: string;
  status: 'loading' | GeoEventSourceStatus;
  eventCount: number;
  rejectedCount: number;
  generatedAt?: string;
  message?: string;
};

export function sourceStatusFromAdapter({
  key,
  label,
  payloadStatus,
  generatedAt,
  result,
  loaded,
}: {
  key: string;
  label: string;
  payloadStatus?: unknown;
  generatedAt?: string;
  result: GeoEventAdapterResult;
  loaded: boolean;
}): WorldEventSourceStatus {
  if (!loaded) {
    return {
      key,
      label,
      status: 'loading',
      eventCount: 0,
      rejectedCount: 0,
    };
  }
  const rawStatus = String(payloadStatus || '').trim().toLowerCase();
  let status: GeoEventSourceStatus = rawStatus === 'error' || rawStatus === 'failed'
    ? 'error'
    : rawStatus === 'degraded' || rawStatus.includes('stale')
      ? 'degraded'
      : rawStatus === 'partial' || result.rejected.length > 0
        ? 'partial'
        : 'ok';
  if (!result.events.length && status === 'ok' && result.rejected.length) status = 'partial';
  return {
    key,
    label,
    status,
    eventCount: result.events.length,
    rejectedCount: result.rejected.length,
    generatedAt,
    message: result.rejected.length
      ? `${result.rejected.length} record${result.rejected.length === 1 ? '' : 's'} rejected by the map contract`
      : undefined,
  };
}
