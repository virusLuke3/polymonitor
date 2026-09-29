import type { RuntimeFinanceWatchPayload, RuntimeGlobalWeatherMapPayload, RuntimeMacroDriverPayload, RuntimeMacroRegistryPayload } from '../../src/types';

// Deliberately synthetic, local-only examples. No provider/network dependency.
const time = '2026-08-26T03:00:00Z';
const finance: RuntimeFinanceWatchPayload = {
  generatedAt: time, status: 'ok', sources: { fixture: 'ok' },
  headline: { label: 'Fixture sentiment', score: 65, previousScore: 62, delta: 3, regime: 'Greed', tone: 'up' },
  items: ['up', 'down', 'watch'].map((tone, i) => ({
    id: `fixture-${i}`, label: `Fixture asset ${i + 1}`, title: 'A long fixture headline with enough words to verify wrapping',
    symbol: ['BTC', 'ETH', 'XYZ'][i], summary: 'Fixture source detail for the panel visual contract.',
    metricLabel: ['$62,123', '3.50%', '$1.2B'][i], secondaryLabel: '24h volume $12.3M',
    changeLabel: ['+2.40%', '-1.10%', '0.00%'][i], metric: 65 - i * 20, tone,
    tags: ['fixture', 'data'], source: 'Fixture', publishedAt: time,
    institution: 'Fixture research', analyst: 'Analyst', rating: 'Hold', targetPriceLabel: '$125',
    points: [1, 4, 2, 5, 3].map((value, n) => ({ timestamp: new Date(Date.parse(time) - n * 60_000).toISOString(), value })),
  })),
};
const weather: RuntimeGlobalWeatherMapPayload = {
  generatedAt: time, status: 'ok', sources: { fixture: 'ok' },
  items: [{ cityId: 'fixture-city', city: 'Fixture city', country: 'Test', timezone: 'UTC',
    unit: 'C', currentTemp: 28, todayHigh: 30, todayLow: 21, forecastHigh: 31, condition: 'Sunny',
    weatherUpdatedAt: time, updatedAt: time,
    hourly: [22, 23, 25, 28, 27].map((temp, i) => ({ time: `2026-08-26T0${i}:00:00Z`, temp })),
    daily: [27, 28, 29, 30, 31, 30, 28].map((high, i) => ({ date: new Date(Date.UTC(2026, 7, 26 + i)).toISOString().slice(0, 10), high, low: 21, weatherCode: 0 })),
    eventTitle: 'Fixture temperature market', bins: [24, 28, 32].map((temp, i) => ({
      label: `${temp}°C`, marketId: i + 1, midPriceYes: [0.2, 0.6, 0.2][i], bestBid: 0.2, bestAsk: 0.3,
    })),
  }],
};
const macro: RuntimeMacroDriverPayload & RuntimeMacroRegistryPayload = {
  generatedAt: time, status: 'ok', sources: { fixture: 'ok' },
  items: ['hot', 'cool', 'watch'].map((tone, i) => ({ key: `fixture-${i}`, label: `Fixture inflation driver ${i + 1}`,
    seriesId: `SERIES-${i}`, group: 'Energy', metric: 'Monthly change', value: 2.4, change: -0.2,
    changePct: 1.3, yoyPct: 3.2, unit: '%', date: '2026-08-01', tone, source: 'Fixture' })),
};

export const panelData: Record<string, unknown> = {};
for (const id of ['crypto-perp-funding', 'tradfi-perp-radar', 'ipo-news-watch', 'broker-research-watch', 'global-index-monitor',
  'crypto-fear-greed', 'crypto-etf-flow', 'stablecoin-monitor', 'blockchain-policy-news', 'defi-yield-monitor',
  'defi-security-watch', 'ai-model-race', 'big-tech-market-cap', 'consumer-app-pulse']) panelData[id] = finance;
for (const id of ['energy-gasoline-shock', 'food-retail-basket-pressure', 'supply-tariff-import-watch',
  'shelter-rent-oer-pressure', 'labor-wage-services-pressure', 'growth-demand-recession-tracker',
  'cpi-components-pressure-registry', 'goods-tariff-supply-watch', 'labor-services-inflation-monitor', 'fed-reaction-growth-risk-board']) panelData[id] = macro;
panelData['global-temperature-monitor'] = weather;
panelData['weather-news'] = { status: 'ok', generatedAt: time, items: [
  { id: 'fixture-weather', cityId: 'fixture-city', city: 'Fixture city', source: 'Fixture', publishedAt: time,
    title: 'Fixture weather headline', summary: 'A fixed weather summary for wrapping and density checks.' },
] };
export const populatedPanelIds = [...Object.keys(panelData), 'weather-market-browser', 'weather-city-snapshot',
  'weather-quote-detail', 'weather-quote-table', 'weather-trend-detail', 'weather-trend-7d', 'world-clock'];
