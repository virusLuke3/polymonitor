import type { Page } from '@playwright/test';
import { GENERATED_AT, installFixtures, transportPayload } from './world-event-map';

export const DASHBOARD_PANELS = ['active-markets', 'price-chart', 'lob-depth', 'global-orderfilled', 'oracle-feed', 'global-transport-shipping', 'breaking-event-radar'];
export const fixtureMarkets = [1, 2].map((id) => ({
  id, slug: `fixture-market-${id}`, title: `Fixture market ${id}`, status: 'active',
  conditionId: `fixture-condition-${id}`, yesTokenId: `yes-${id}`, noTokenId: `no-${id}`,
  latestPrice: id === 1 ? '0.62' : '0.38', category: 'Politics', tags: [],
  volume24h: '12500', tradeCount24h: 23, change24h: '0.03', outcomeCount: 2,
  createdAt: '2026-08-01T00:00:00Z', lastTradeAt: GENERATED_AT, endDate: '2026-12-31T00:00:00Z',
}));

export function fixtureBundle(id: number) {
  const market = fixtureMarkets.find((item) => item.id === id)!;
  const chart = { marketId: id, range: '1d', interval: '5m', kind: 'probability', points: Array.from({ length: 24 }, (_, i) => ({
    timestamp: new Date(Date.parse(GENERATED_AT) - (23 - i) * 300_000).toISOString(),
    yesPrice: String(Number(market.latestPrice) + Math.sin(i) * 0.03),
  })) };
  const book = (tokenId: string) => ({ tokenId, bookStatus: 'live', continuity: true, heartbeatAt: GENERATED_AT,
    receivedAt: GENERATED_AT, staleAfter: '2026-08-26T04:00:00Z', bestBid: '0.61', bestAsk: '0.63',
    bids: [{ price: '0.61', size: '120' }], asks: [{ price: '0.63', size: '150' }] });
  return { market, identity: { marketId: id, localMarketId: id, yesTokenId: market.yesTokenId, noTokenId: market.noTokenId },
    price: { marketId: id, latestPrice: market.latestPrice, latestYesPrice: market.latestPrice, latestNoPrice: String(1 - Number(market.latestPrice)), volume24h: market.volume24h, tradeCount24h: 23, change24h: '0.03', updatedAt: GENERATED_AT },
    chart, trades: [], oracle: { marketId: id, timeline: [], currentStatus: 'active' },
    lob: { marketId: id, fetchedAt: GENERATED_AT, yes: book(market.yesTokenId), no: book(market.noTokenId) },
    content: { marketId: id, items: [] }, generatedAt: GENERATED_AT, focusStatus: 'ready', servingSource: 'fixture',
  };
}

export async function installDashboard(page: Page, locale = 'en', panelIds = DASHBOARD_PANELS) {
  await page.clock.setFixedTime(new Date(GENERATED_AT));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(({ locale, panels }) => {
    localStorage.setItem('polydata:locale:v1', locale);
    localStorage.setItem('polydata:workspace-panels:v4', JSON.stringify(panels));
  }, { locale, panels: panelIds });
  await installFixtures(page);
  await page.route('**/wm-api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/wm-api/, '');
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body });
    if (path === '/auth/session') return json({ enabled: true, authenticated: true, user: { id: 1, username: 'fixture-user', role: 'admin', forcePasswordChange: false }, csrfToken: 'fixture-only', allowedScopes: [] });
    if (path === '/product/workspace-layout') return json({ exists: true, revision: 1, activePanelIds: panelIds, panelLayout: {}, preferences: {}, clientUpdatedAt: GENERATED_AT, updatedAt: GENERATED_AT });
    if (path === '/bootstrap') return json({ generatedAt: GENERATED_AT, defaultWorkspace: { name: 'Fixture', panels: panelIds }, featuredMarket: fixtureMarkets[0], activeMarketsPreview: fixtureMarkets, activeMarketGroupsPreview: [], globalTradesPreview: [], globalOraclePreview: [], latestContentPreview: [], recentTradesPreview: [], oraclePreview: [], contentPreview: [], pricePreview: null, systemHealth: { apiStatus: 'ok', database: 'fixture' } });
    if (path === '/markets' || path === '/markets/search') return json({ items: fixtureMarkets, pagination: { page: 1, pageSize: 80, total: 2, totalPages: 1, hasMore: false } });
    const marketMatch = path.match(/^\/markets\/(\d+)\/(focus-tile|workspace|detail|chart)$/);
    if (marketMatch) { const bundle = fixtureBundle(Number(marketMatch[1])); return json(marketMatch[2] === 'chart' ? bundle.chart : bundle); }
    if (path.startsWith('/runtime/lob/token/')) return json(fixtureBundle(Number(url.searchParams.get('marketId') || 1)).lob);
    if (path === '/trades/recent' || path === '/oracle/recent') return json([]);
    if (path === '/v1/runtime/panels') {
      const panels = Object.fromEntries((url.searchParams.get('ids') || '').split(',').map((id) => [id, id === 'global-transport-shipping' ? transportPayload : { generatedAt: GENERATED_AT, status: 'ok', items: [] }]));
      return json({ apiVersion: 'v1', requestId: 'fixture', generatedAt: GENERATED_AT, status: 'ok', data: { panels }, meta: { panels: {} }, errors: [] });
    }
    if (path === '/product/watchlist') return json({ id: 'fixture', name: 'Fixture watchlist', items: [], summary: { markets: 0, activeRules: 0, oracleGaps: 0, unreadAlerts: 0 }, alertKinds: [] });
    if (path === '/product/notification-preferences') return json({ inAppEnabled: true, webPushEnabled: false, digestMode: 'off', quietStartMinute: null, quietEndMinute: null, timezone: 'UTC', channels: {} });
    if (path === '/product/web-push') return json({ available: false, publicKey: null, enabled: false, connected: false, subscriptionCount: 0 });
    if (path === '/data-quality/markets') return json({ error: 'Fixture: source temporarily unavailable' }, 503);
    return route.fallback();
  });
}
