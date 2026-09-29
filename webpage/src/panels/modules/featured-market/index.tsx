import type { PanelInputs } from '../../types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { shortHash } from '@/panels/shared/formatters';
import { useI18n } from '@/services/i18n';
import { panelFromRenderer } from '@/panels/definePanel';

type Inputs = PanelInputs<'bootstrap' | 'bundle' | 'selectedMarket'>;

function FeaturedMarketPanel({ ctx }: { ctx: Inputs }) {
  const { t } = useI18n();
  const selected = ctx.selectedMarket || ctx.bundle?.market || ctx.bootstrap?.featuredMarket || null;
  const tags = (selected?.tags || []).filter(Boolean).slice(0, 4);
  const resolutionText = selected?.description || ctx.bundle?.chart?.referenceRule || t('atlasMarket.resolutionLoading');
  return (
    <Panel title={t('atlasMarket.context')} badge={t('atlasMarket.rules')} status="live" className="wm-market-panel wm-market-context-panel">
      <div className="wm-feature-panel">
        <section className="wm-feature-hero">
          <span className="wm-feature-kicker">{t('atlasMarket.resolutionContext')}</span>
          <p>{resolutionText}</p>
        </section>

        <div className="wm-feature-tags" aria-label={t('atlasMarket.tags')}>
          <span>{selected?.category || t('atlasOracle.market')}</span>
          {tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <span>{t('atlasMarket.untagged')}</span>}
        </div>

        <div className="wm-feature-grid">
          <article className="wm-feature-stat">
            <span>ORACLE</span>
            <strong>{shortHash(selected?.oracle || ctx.bundle?.oracle?.oracle || '', 8, 5)}</strong>
          </article>
          <article className="wm-feature-stat">
            <span>CONDITION</span>
            <strong>{shortHash(selected?.conditionId || '', 8, 5)}</strong>
          </article>
          <article className="wm-feature-stat">
            <span>QUESTION ID</span>
            <strong>{shortHash(selected?.questionId || ctx.bundle?.oracle?.questionId || '', 8, 5)}</strong>
          </article>
          <article className="wm-feature-stat">
            <span>GAMMA ID</span>
            <strong>{selected?.gammaMarketId || '--'}</strong>
          </article>
        </div>
      </div>
    </Panel>
  );
}

const renderers: PanelRenderMap<'bootstrap' | 'bundle' | 'selectedMarket'> = {
  'featured-market': {
    render: (ctx) => <FeaturedMarketPanel ctx={ctx} />,
  },
};

export const panel = panelFromRenderer(renderers, {
  contextKeys: ['bootstrap', 'bundle', 'selectedMarket'],
  id: 'featured-market',
  title: 'Market Context',
  eyebrow: 'focus',
  description: 'Resolution rules, tags, and oracle references for the selected market.',
  defaultEnabled: true,
});
