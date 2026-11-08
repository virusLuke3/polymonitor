import { describe, expect, it, vi } from 'vitest';

vi.mock('./i18n', async (importOriginal) => {
  const original = await importOriginal<typeof import('./i18n')>();
  return { ...original, useI18n: () => ({
    t: (key: string) => key.endsWith('.translated') ? 'Already translated' : key,
  }) };
});

import { useSpecialistCopy } from './specialist-i18n';

describe('specialist fallback interpolation', () => {
  it('renders observed counts even before new copy has a catalog entry', () => {
    expect(useSpecialistCopy('polymarket-macro-map').copy(
      'boundedCoverage', 'Showing {shown} of {events} events', { shown: 12, events: 43 },
    )).toBe('Showing 12 of 43 events');
  });
  it('preserves known zero counts and leaves unknown parameters explicit', () => {
    expect(useSpecialistCopy('sports-odds').shared(
      'newCount', '{count} events / {unknown}', { count: 0 },
    )).toBe('0 events / {unknown}');
  });
  it('keeps existing translated copy', () => {
    expect(useSpecialistCopy('test').copy('translated', '{count}', { count: 1 }))
      .toBe('Already translated');
  });
});
