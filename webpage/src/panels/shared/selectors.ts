import type { PanelRenderContext } from '@/types';

function focusedContent(ctx: Pick<PanelRenderContext, 'bundle' | 'bootstrap' | 'selectedMarketId' | 'latestContent'>) {
  return ctx.bundle?.content?.items?.length
    ? ctx.bundle.content.items
    : (ctx.bootstrap?.featuredMarket?.id === ctx.selectedMarketId ? ctx.bootstrap.contentPreview : ctx.latestContent);
}

function globalMarkets(ctx: Pick<PanelRenderContext, 'markets' | 'bootstrap'>) {
  return ctx.markets.length ? ctx.markets : (ctx.bootstrap?.activeMarketsPreview || []);
}

function globalOracle(ctx: Pick<PanelRenderContext, 'globalOracle' | 'bootstrap'>) {
  return ctx.globalOracle.length ? ctx.globalOracle : (ctx.bootstrap?.globalOraclePreview || []);
}


export {
  focusedContent,
  globalMarkets,
  globalOracle,
};
