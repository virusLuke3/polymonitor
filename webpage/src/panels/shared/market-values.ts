import type { MarketGroupItem, MarketGroupOutcome } from '@/types';
import { useI18n } from '@/services/i18n';

export type MarketI18n = Pick<ReturnType<typeof useI18n>, 't' | 'formatDateTime' | 'formatNumber' | 'formatPercent' | 'formatRelativeTime'>;

export function localizedPercent(value: string | number | null | undefined, i18n: MarketI18n) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? i18n.formatPercent(numeric) : '--';
}

export function localizedCompact(value: string | number | null | undefined, i18n: MarketI18n) {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  return Number.isFinite(numeric)
    ? i18n.formatNumber(numeric, { notation: 'compact', maximumFractionDigits: 1 })
    : '--';
}

export function localizedCurrency(value: string | number | null | undefined, i18n: MarketI18n) {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  return Number.isFinite(numeric)
    ? i18n.formatNumber(numeric, { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 })
    : '--';
}

export function firstFiniteValue(...values: Array<string | number | null | undefined>) {
  return values.find((value) => {
    if (value === null || value === undefined || value === '') return false;
    return Number.isFinite(Number(value));
  }) ?? null;
}

export function sumFiniteValues(values: Array<string | number | null | undefined>) {
  const finite = values
    .filter((value) => value !== null && value !== undefined && value !== '')
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  if (!finite.length) return null;
  return finite.reduce((sum, value) => sum + value, 0);
}

export function uniqueGroupOutcomes(outcomes: MarketGroupOutcome[]) {
  const seen = new Set<string>();
  return outcomes.filter((outcome, index) => {
    const key = String(outcome.marketId ?? outcome.outcomeKey ?? outcome.gammaMarketId ?? `${outcome.label || 'outcome'}-${index}`);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function groupDisplayVolume(group: MarketGroupItem) {
  return firstFiniteValue(
    group.volume24h,
    sumFiniteValues((group.outcomes || []).map((outcome) => outcome.volume24h)),
    sumFiniteValues((group.topOutcomes || []).map((outcome) => outcome.volume24h)),
  );
}

export function groupDisplayTradeCount(group: MarketGroupItem) {
  return firstFiniteValue(
    group.tradeCount24h,
    sumFiniteValues((group.outcomes || []).map((outcome) => outcome.tradeCount24h)),
    sumFiniteValues((group.topOutcomes || []).map((outcome) => outcome.tradeCount24h)),
  );
}
