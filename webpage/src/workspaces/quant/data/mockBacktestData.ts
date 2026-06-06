import type { MarketInfo, PricePoint, Signal, Trade } from '../types';

export const MARKET_INFO: MarketInfo = {
  id: 'mkt-team-a-win',
  conditionId: '0x8f4a7b9c2d1e41c',
  title: 'Will Team A win?',
  category: 'Sports',
  slug: 'will-team-a-win',
  startTime: '2026-06-05 00:00 UTC',
  endTime: '2026-06-06 23:59 UTC',
  resolutionTime: '2026-06-07 02:30 UTC',
  resolvedOutcome: 'PENDING',
  yesTokenId: '713921084580129744...YES',
  noTokenId: '713921084580129744...NO',
  liquidity: '284.2K USDC',
  volume: '3.91M shares',
};

export const MOCK_PRICES: PricePoint[] = Array.from({ length: 128 }, (_, index) => {
  const wave = Math.sin(index / 6) * 0.044 + Math.cos(index / 17) * 0.021;
  const breakout = index > 32 && index < 55 ? (index - 32) * 0.0032 : 0;
  const selloff = index > 76 && index < 92 ? -0.12 + (index - 76) * 0.004 : 0;
  const recovery = index > 99 ? (index - 99) * 0.0028 : 0;
  return {
    timestamp: 1_717_584_000 + index * 300,
    close: Math.max(0.04, Math.min(0.96, 0.49 + wave + breakout + selloff + recovery)),
    volume: 900 + Math.round(Math.abs(Math.sin(index / 4.5)) * 5800 + (index % 9) * 190),
    source: 'mock',
  };
});

function mockTs(index: number) {
  return MOCK_PRICES[index]?.timestamp || MOCK_PRICES[0]?.timestamp || 0;
}

export const MOCK_SIGNALS: Signal[] = [
  { id: 's1', timestamp: mockTs(17), action: 'OPEN', outcome: 'YES', price: 0.48, size: 240, notional: 115.2, reason: 'Momentum breakout', tradeId: 'T-118' },
  { id: 's2', timestamp: mockTs(33), action: 'CLOSE', outcome: 'YES', price: 0.57, size: 240, notional: 136.8, reason: 'Target reached', tradeId: 'T-118' },
  { id: 's3', timestamp: mockTs(56), action: 'SELL', outcome: 'NO', price: 0.62, size: 180, notional: 111.6, reason: 'Breakdown confirmation', tradeId: 'T-119' },
  { id: 's4', timestamp: mockTs(73), action: 'CLOSE', outcome: 'NO', price: 0.54, size: 180, notional: 97.2, reason: 'Trailing stop', tradeId: 'T-119' },
  { id: 's5', timestamp: mockTs(91), action: 'OPEN', outcome: 'YES', price: 0.51, size: 320, notional: 163.2, reason: 'Mean reversion', tradeId: 'T-120' },
  { id: 's6', timestamp: mockTs(112), action: 'CLOSE', outcome: 'YES', price: 0.59, size: 320, notional: 188.8, reason: 'Resolution risk trim', tradeId: 'T-120' },
];

export const MOCK_TRADES: Trade[] = [
  { id: 'T-118', entryTime: '2026-06-05 12:31', exitTime: '2026-06-05 13:36', marketId: MARKET_INFO.id, market: MARKET_INFO.title, outcome: 'YES', side: 'LONG', entryPrice: 0.48, exitPrice: 0.57, size: 240, notional: 115.2, pnl: 21.6, pnlPct: 18.75, holdingTime: '1h 05m', holdingBars: 13, exitReason: 'Target reached' },
  { id: 'T-119', entryTime: '2026-06-05 15:26', exitTime: '2026-06-05 16:36', marketId: MARKET_INFO.id, market: MARKET_INFO.title, outcome: 'NO', side: 'SHORT', entryPrice: 0.62, exitPrice: 0.54, size: 180, notional: 111.6, pnl: 14.4, pnlPct: 12.9, holdingTime: '1h 10m', holdingBars: 14, exitReason: 'Trailing stop' },
  { id: 'T-120', entryTime: '2026-06-05 17:46', exitTime: '2026-06-05 18:41', marketId: MARKET_INFO.id, market: MARKET_INFO.title, outcome: 'YES', side: 'LONG', entryPrice: 0.51, exitPrice: 0.59, size: 320, notional: 163.2, pnl: 25.6, pnlPct: 15.69, holdingTime: '55m', holdingBars: 11, exitReason: 'Resolution risk trim' },
  { id: 'T-121', entryTime: '2026-06-05 19:06', exitTime: '2026-06-05 20:11', marketId: 'mkt-team-b-qualify', market: 'Will Team B qualify?', outcome: 'YES', side: 'LONG', entryPrice: 0.37, exitPrice: 0.33, size: 410, notional: 151.7, pnl: -16.4, pnlPct: -10.81, holdingTime: '1h 05m', holdingBars: 13, exitReason: 'Stop loss' },
];
