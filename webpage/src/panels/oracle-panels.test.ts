import { describe, expect, it } from 'vitest';
import type { OracleEvent, OraclePayload } from '@/types';
import { oracleFeedView } from './modules/oracle-feed';

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
