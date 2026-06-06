import type { QuantBlockClosePoint, QuantFrontendPricePoint } from '@/types';
import type { PricePoint } from '../types';
import { toNumber } from './formatters';

export function frontendToPrices(rows: QuantFrontendPricePoint[]): PricePoint[] {
  return rows.map((row) => ({
    timestamp: Number(row.timestamp),
    close: toNumber(row.price),
    volume: 0,
    source: 'frontend',
  })).filter((row) => row.timestamp && row.close);
}

export function blockToPrices(rows: QuantBlockClosePoint[]): PricePoint[] {
  return rows.map((row) => ({
    timestamp: Number(row.blockNumber),
    close: toNumber(row.closePrice),
    volume: toNumber(row.volume),
    source: 'orderfilled_block_close',
  })).filter((row) => row.timestamp && row.close);
}
