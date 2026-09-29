import type { PanelRenderMap } from '@/panels/types';
import { runtimePanelFromRenderer } from '@/panels/definePanel';
import { fetchInsightSnapshot } from '@/panels/shared/market-insights/data';
import { useI18n } from '@/services/i18n';
import { insightView } from '@/panels/shared/market-insights/model';
import { InsightFrame, InsightCards, InsightWatchlist } from '@/panels/shared/market-insights/components';

function MarketBrief({ snapshot }: { snapshot: unknown }) {
  const { t } = useI18n();
  const view = insightView(snapshot, 'overview');
  const items = view.insight?.focus || [];
  return <InsightFrame view={view} lens="overview" title={t('marketInsights.title.overview')} count={items.length}>
      <InsightCards title={t('marketInsights.overview')} items={items} empty={t('marketInsights.overviewEmpty')} />
      <InsightWatchlist items={view.insight?.watchlist || []} />
    </InsightFrame>;
}

const renderers: PanelRenderMap = {
  'price-implications': { render: (ctx) => <MarketBrief snapshot={ctx.runtimeData['price-implications']} /> },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'price-implications', title: 'AI Insights', eyebrow: 'agent',
  description: 'AI Insights from a saved market sample, with generation and freshness status.',
  defaultEnabled: false,
}, {
  tier: 'bootstrap', intervalMs: 60_000, staleAfterMs: 12 * 60 * 60_000, batch: false,
  fetchData: (context) => fetchInsightSnapshot('overview', context?.signal),
});
