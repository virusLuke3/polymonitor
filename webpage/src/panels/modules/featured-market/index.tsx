import type { PanelInputs } from '../../types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { shortHash } from '@/panels/shared/formatters';
import { useI18n } from '@/services/i18n';
import { panelFromRenderer } from '@/panels/definePanel';
import { marketRules } from './model';

type Inputs = PanelInputs<'bundle' | 'selectedMarket' | 'selectedMarketId'>;

function FeaturedMarketPanel({ ctx }: { ctx: Inputs }) {
  const { t } = useI18n();
  const rules = marketRules(ctx.selectedMarketId, ctx.selectedMarket, ctx.bundle);
  const selected = rules?.market;
  const tags = rules?.tags || [];
  const resolutionText = rules?.text || t(ctx.selectedMarketId == null ? 'atlasMarket.noSelection' : 'marketRules.unavailable');
  return (
    <Panel title={t('atlasMarket.context')} badge={t(rules?.text ? 'atlasMarket.rules' : 'marketRules.missing')} status={rules?.text ? 'locked' : 'muted'} className="wm-market-panel wm-market-context-panel">
      <div className="wm-feature-panel">
        <section className="wm-feature-hero">
          {selected ? <strong className="wm-feature-market-title">{selected.title}</strong> : null}
          <span className="wm-feature-kicker">{t('atlasMarket.resolutionContext')}</span>
          <p>{resolutionText}</p>
          {rules?.text ? <small>{t(rules.ruleSource === 'description' ? 'marketRules.description' : 'marketRules.reference')}</small> : null}
        </section>

        <div className="wm-feature-tags" aria-label={t('atlasMarket.tags')}>
          <span>{selected?.category || t('atlasOracle.market')}</span>
          {tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <span>{t('atlasMarket.untagged')}</span>}
        </div>

        <div className="wm-feature-grid">
          <article className="wm-feature-stat">
            <span>ORACLE</span>
            <strong>{shortHash(rules?.oracle || '', 8, 5)}</strong>
          </article>
          <article className="wm-feature-stat">
            <span>CONDITION</span>
            <strong>{shortHash(selected?.conditionId || '', 8, 5)}</strong>
          </article>
          <article className="wm-feature-stat">
            <span>QUESTION ID</span>
            <strong>{shortHash(rules?.questionId || '', 8, 5)}</strong>
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

const renderers: PanelRenderMap<'bundle' | 'selectedMarket' | 'selectedMarketId'> = {
  'featured-market': {
    render: (ctx) => <FeaturedMarketPanel ctx={ctx} />,
  },
};

export const panel = panelFromRenderer(renderers, {
  contextKeys: ['bundle', 'selectedMarket', 'selectedMarketId'],
  id: 'featured-market',
  title: 'Market Context',
  eyebrow: 'focus',
  description: 'Resolution rules, tags, and oracle references for the selected market.',
  defaultEnabled: true,
});
