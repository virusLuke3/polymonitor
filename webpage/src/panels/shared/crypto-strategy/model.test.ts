import { describe, expect, it } from 'vitest';
import { change, marketUrl, parseInputs, referenceUsable, type Reference } from './model';
const input = () => ({kind:'crypto-strategy', schemaVersion:1, status:'partial', generatedAt:'2026-11-02T10:00:00Z', collectedAt:1793613600000, assets:{BTC:{asset:'BTC'}}, references:{}, options:{}, stablecoins:[], inflows:{mode:'unavailable',rows:[]}});
describe('crypto strategy data boundary', () => {
  it('accepts partial sources but rejects wrong identities and malformed nested series', () => {
    expect(parseInputs(input()).status).toBe('partial');
    expect(() => parseInputs({...input(),kind:'crypto'})).toThrow();
    expect(() => parseInputs({...input(),assets:{BTC:{asset:'ETH'}}})).toThrow();
    expect(() => parseInputs({...input(),assets:{BTC:{spotHistory:'bad'}}})).toThrow();
    expect(() => parseInputs({...input(),options:{BTC:{expiries:[{expiry:'2026-11-03',underlying:100,bands:null}]}}})).toThrow();
    expect(() => parseInputs({...input(),references:{status:'unavailable'}})).toThrow();
  });
  it('does not invent a missing lookback return', () => {
    expect(change([{t:1000000,v:100}],15)).toBeNull();
    expect(change([{t:100000,v:100},{t:1000000,v:110}],15)).toBeCloseTo(10);
    expect(change([{t:200000,v:100},{t:1000000,v:110}],15)).toBeNull();
  });
  it('gates current oracle distance by time and exact window', () => {
    const ref = {status:'ok',latest:{event_at_ms:100000,window_seconds:60},market:{starts_at_ms:90000,ends_at_ms:200000,window_seconds:60,slug:'btc-test'}} as Reference;
    expect(referenceUsable(ref,101000)).toBe(true);
    expect(referenceUsable(ref,116000)).toBe(false);
    expect(referenceUsable({...ref,market:{...ref.market!,starts_at_ms:102000}},101000)).toBe(false);
    expect(referenceUsable({...ref,market:{...ref.market!,ends_at_ms:101000}},101000)).toBe(false);
    expect(referenceUsable({...ref,market:{...ref.market!,window_seconds:1}},101000)).toBe(false);
    expect(marketUrl(ref)).toBe('https://polymarket.com/event/btc-test');
    expect(marketUrl({...ref,market:{...ref.market!,slug:'javascript:bad'}})).toBeNull();
  });
});
