import type { PanelRenderMap } from '@/panels/types';
import { runtimePanelFromRenderer } from '@/panels/definePanel';
import { fetchInsightSnapshot } from '@/panels/shared/market-insights/data';
import { useI18n } from '@/services/i18n';
import { insightView } from '@/panels/shared/market-insights/model';
import { InsightFrame, InsightCards, InsightWatchlist } from '@/panels/shared/market-insights/components';

function TrendWatch({ snapshot }: { snapshot: unknown }) {
  const { t } = useI18n();
  const view = insightView(snapshot, 'trend');
  const items = view.insight?.themes || [];
  return <InsightFrame view={view} lens="trend" title={t('marketInsights.title.trend')} count={items.length}>
      <InsightCards title={t('marketInsights.trend')} items={items} empty={t('marketInsights.trendEmpty')} />
      <InsightWatchlist items={view.insight?.watchlist || []} />
    </InsightFrame>;
}

const renderers: PanelRenderMap = {
  'oracle-timeline': { render: (ctx) => <TrendWatch snapshot={ctx.runtimeData['oracle-timeline']} /> },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'oracle-timeline', title: 'Trend Watch', eyebrow: 'agent',
  description: 'Trend Watch from a saved market sample, with generation and freshness status.',
  defaultEnabled: false,
}, {
  tier: 'bootstrap', intervalMs: 60_000, staleAfterMs: 12 * 60 * 60_000, batch: false,
  fetchData: (context) => fetchInsightSnapshot('trend', context?.signal),
});
