import type { PanelRenderContext } from '@/types';

function focusedContent(ctx: PanelRenderContext) {
  return ctx.bundle?.content?.items?.length
    ? ctx.bundle.content.items
    : (ctx.bootstrap?.featuredMarket?.id === ctx.selectedMarketId ? ctx.bootstrap.contentPreview : ctx.latestContent);
}

function globalMarkets(ctx: PanelRenderContext) {
  return ctx.markets.length ? ctx.markets : (ctx.bootstrap?.activeMarketsPreview || []);
}

function globalOracle(ctx: PanelRenderContext) {
  return ctx.globalOracle.length ? ctx.globalOracle : (ctx.bootstrap?.globalOraclePreview || []);
}


export {
  focusedContent,
  globalMarkets,
  globalOracle,
};
