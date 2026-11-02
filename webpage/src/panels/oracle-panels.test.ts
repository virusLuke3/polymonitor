import { describe, expect, it } from 'vitest';
import type { OracleEvent, OraclePayload } from '@/types';
import { oracleFeedView } from './modules/oracle-feed';
import { oracleList, orderfilledList } from './shared/renderers';

function renderedText(node: unknown): string {
  if (node == null || typeof node === 'boolean') return '';
  if (Array.isArray(node)) return node.map(renderedText).join('');
  if (typeof node === 'object') return renderedText((node as { props?: { children?: unknown } }).props?.children);
  return String(node);
}

describe('Missing stored values', () => {
  it('keeps missing trade prices distinct from a real zero price', () => {
    for (const price of [null, undefined, '']) {
      const text = renderedText(orderfilledList([{ price, size: '5' }]));
      expect(text).not.toContain('0c');
      expect(text).toContain('$--');
    }
    const zero = renderedText(orderfilledList([{ price: '0', size: '5' }]));
    expect(zero).toContain('0c');
    expect(zero).toContain('$0');
  });

  it('does not show a missing oracle price as a NO outcome', () => {
    for (const proposedPrice of [null, undefined, '']) {
      const text = renderedText(oracleList([{ eventStatus: 'request', proposedPrice, settledPrice: null }]));
      expect(text).toContain('Pending');
      expect(text).not.toContain('NO');
    }
    expect(renderedText(oracleList([{ eventStatus: 'propose', proposedPrice: 0 }]))).toContain('NO');
  });
});

describe('Oracle feed presentation', () => {
  it('keeps a verified empty selected-market timeline separate from global events', () => {
    const focused: OraclePayload = {
      marketId: 4559386,
      localMarketId: 4559386,
      currentStatus: 'Active',
      timeline: [],
    };
    const globalEvents: OracleEvent[] = [{
      id: 5934010,
      blockNumber: 90414675,
      eventTime: '2026-07-17T22:23:30Z',
      eventStatus: 'request',
      marketId: 3034150,
      isBound: true,
    }];

    expect(oracleFeedView(focused, globalEvents)).toEqual({
      events: [],
      source: 'focused',
    });
  });

  it('keeps a selected market timeline ahead of the global feed', () => {
    const focusedEvent: OracleEvent = {
      id: 5921588,
      blockNumber: 90394865,
      eventStatus: 'propose',
      marketId: 3023777,
    };
    const focused: OraclePayload = {
      marketId: 3023777,
      timeline: [focusedEvent],
    };
    const globalEvents: OracleEvent[] = [{ id: 5934010, blockNumber: 90414675 }];

    expect(oracleFeedView(focused, globalEvents)).toEqual({
      events: [focusedEvent],
      source: 'focused',
    });
  });
});
