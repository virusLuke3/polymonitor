import { afterEach, describe, expect, it, vi } from 'vitest';
import { statusLabel } from '@/components/design-system/StatusPrimitives';
import { ageSeconds, formatCompact, formatLocalizedCompact, numericValue, panelStatus, scoreLabel, seededStatusBadge, watchStatusBadge } from './formatters';
import { panelStatus as videoPanelStatus } from './videoPlayback';

afterEach(() => vi.useRealTimers());

describe('shared presentation preserves provider semantics', () => {
  it('keeps stale and preserved data distinct from successful refreshes', () => {
    const preserved = { status: 'ok', cacheMode: 'preserved' };
    expect(seededStatusBadge(preserved)).toBe('STALE');
    expect(watchStatusBadge(preserved)).toBe('LIVE');
    const stale = { status: 'ok', cacheMode: 'stale-cache' };
    expect(seededStatusBadge(stale)).toBe('STALE');
    expect(watchStatusBadge(stale)).toBe('STALE');
    expect(seededStatusBadge({ status: 'degraded', cacheMode: 'seed' })).toBe('PARTIAL');
    expect(watchStatusBadge({ status: 'partial' })).toBe('PARTIAL');
  });

  it('retains the video and seeded panel readiness policies', () => {
    expect(panelStatus('degraded')).toBe('muted');
    expect(videoPanelStatus({ status: 'degraded' })).toBe('live');
    expect(panelStatus('ok')).toBe('live');
    expect(videoPanelStatus({ status: 'warming' })).toBe('muted');
    expect(seededStatusBadge({ status: 'empty' })).toBe('WARM');
    expect(watchStatusBadge({ status: 'empty' })).toBe('WARMING');
  });

  it('does not turn missing display values into the numeric ranking fallback', () => {
    expect(numericValue('invalid')).toBe(0);
    expect(scoreLabel('invalid')).toBe('--');
    expect(formatCompact(null)).toBe('--');
    const format = (value: number) => String(value);
    expect(formatLocalizedCompact(null, format)).toBe('0');
    expect(formatLocalizedCompact('invalid', format)).toBe('--');
  });

  it('preserves route-specific translations and unknown status labels', () => {
    const t: Parameters<typeof statusLabel>[1] = (key) => key;
    expect(statusLabel('not_collected', t)).toBe('Not Collected');
    expect(statusLabel('not_collected', t, { 'not-collected': 'status.notCollected' })).toBe('status.notCollected');
    expect(statusLabel('unrecognized_source', t)).toBe('Unrecognized Source');
    expect(statusLabel(' stale ', t)).toBe('status.stale');
  });

  it('keeps unknown timestamps unknown and never shows a negative age', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-29T00:00:10Z'));
    expect(ageSeconds('invalid')).toBeNull();
    expect(ageSeconds(null)).toBeNull();
    expect(ageSeconds('2026-09-29T00:00:00Z')).toBe(10);
    expect(ageSeconds('2026-09-29T00:01:00Z')).toBe(0);
  });
});
