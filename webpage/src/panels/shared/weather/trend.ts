import type { RuntimeGlobalWeatherCity } from '@/types';
import { num } from './model';

export type TrendPoint = {
  label: string;
  time: number;
  avg: number;
  high: number;
};

function movingAverage(values: number[], index: number) {
  const start = Math.max(0, index - 2);
  const slice = values.slice(start, index + 1);
  return slice.reduce((sum, value) => sum + value, 0) / Math.max(1, slice.length);
}

export function oneDayPoints(city?: RuntimeGlobalWeatherCity | null): TrendPoint[] {
  const hourly = (city?.hourly || [])
    .filter((point) => num(point.temp) !== null)
    .slice(0, 24);
  const values = hourly.map((point) => num(point.temp) || 0);
  return hourly.map((point, index) => {
    const value = num(point.temp) || 0;
    const date = String(point.time || '');
    const parsed = Date.parse(date);
    return {
      label: date.slice(11, 16) || date.slice(5, 10) || '--',
      time: Number.isFinite(parsed) ? Math.floor(parsed / 1000) : index + 1,
      avg: movingAverage(values, index),
      high: value,
    };
  }).sort((left, right) => left.time - right.time);
}

export function sevenDayPoints(city?: RuntimeGlobalWeatherCity | null): TrendPoint[] {
  const days = (city?.daily || [])
    .filter((point) => num(point.high) !== null || num(point.low) !== null)
    .slice(0, 7);
  return days.map((day, index) => {
    const high = num(day.high) ?? num(day.low) ?? 0;
    const low = num(day.low) ?? high;
    const avg = (high + low) / 2;
    const label = String(day.date || '').slice(5) || '--';
    const parsed = Date.parse(`${day.date}T00:00:00Z`);
    return { label, time: Number.isFinite(parsed) ? Math.floor(parsed / 1000) : index + 1, avg, high };
  }).sort((left, right) => left.time - right.time);
}
