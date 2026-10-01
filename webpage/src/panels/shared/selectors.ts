import type { PanelRenderContext } from '@/types';

function focusedContent(ctx: Pick<PanelRenderContext, 'bundle' | 'bootstrap' | 'selectedMarketId' | 'latestContent'>) {
  if (ctx.selectedMarketId == null) return ctx.latestContent;
  return ctx.bundle?.content?.marketId === ctx.selectedMarketId ? ctx.bundle.content.items : [];
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
