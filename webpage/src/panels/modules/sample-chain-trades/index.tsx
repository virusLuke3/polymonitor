import type { PanelRenderMap } from '@/panels/types';
import { runtimePanelFromRenderer } from '@/panels/definePanel';
import { fetchInsightSnapshot } from '@/panels/shared/market-insights/data';
import { useI18n } from '@/services/i18n';
import { insightView } from '@/panels/shared/market-insights/model';
import { InsightFrame, InsightWatchlist } from '@/panels/shared/market-insights/components';

function SpecialRadar({ snapshot }: { snapshot: unknown }) {
  const { t } = useI18n();
  const view = insightView(snapshot, 'special');
  const items = view.insight?.specialMarkets || [];
  return <InsightFrame view={view} lens="special" title={t('marketInsights.title.special')} count={items.length}>
      <section className="wm-ai-insight-list wm-ai-special-list" aria-label={t('marketInsights.candidates')}>
        <div className="wm-ai-insight-section-head"><span>{t('marketInsights.candidates')}</span><em>{items.length}</em></div>
        {items.length ? items.map((item, index) => <article className="wm-ai-insight-market-card" key={index}>
          <div><span>{item.trend}</span><strong>{item.title}</strong><p>{item.why}</p></div><b>{item.evidence}</b>
        </article>) : <p className="wm-ai-insight-notice">{t('marketInsights.specialEmpty')}</p>}
      </section>
      <InsightWatchlist items={view.insight?.watchlist || []} />
    </InsightFrame>;
}

const renderers: PanelRenderMap = {
  'sample-chain-trades': { render: (ctx) => <SpecialRadar snapshot={ctx.runtimeData['sample-chain-trades']} /> },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'sample-chain-trades', title: 'Special Radar', eyebrow: 'agent',
  description: 'Special Radar from a saved market sample, with generation and freshness status.',
  defaultEnabled: false,
}, {
  tier: 'bootstrap', intervalMs: 60_000, staleAfterMs: 12 * 60 * 60_000, batch: false,
  fetchData: (context) => fetchInsightSnapshot('special', context?.signal),
});
