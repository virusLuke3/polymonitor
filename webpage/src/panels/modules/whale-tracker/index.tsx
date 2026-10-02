import { useState } from 'preact/hooks';
import { panelFromRenderer } from '@/panels/definePanel';
import type { PanelInputs, PanelRenderMap } from '@/panels/types';
import { TradeCard, TradeFeedBoundary, TradeFeedFrame } from '@/panels/shared/trade-feed/components';
import { useI18n } from '@/services/i18n';
import { useWhaleFeed } from './useWhaleFeed';

function WhaleView({ ctx }: { ctx: PanelInputs<'setSelectedMarketId'> }) {
  const feed = useWhaleFeed(), i18n = useI18n(), cn = i18n.locale.startsWith('zh');
  const [side, setSide] = useState('ALL');
  const items = feed.data?.items || [], visible = items.filter(item => side === 'ALL' || item.side === side);
  return <TradeFeedFrame title="WHALE TRACKER" feed={feed}>
    <div className="wm-trade-watch-tabs" aria-label={cn ? '成交方向筛选' : 'Trade direction filters'}>{['ALL', 'BUY', 'SELL'].map(value => <button type="button" key={value} aria-pressed={side === value} onClick={() => setSide(value)}>{value === 'ALL' ? cn ? '全部' : 'All' : value} {items.filter(item => value === 'ALL' || item.side === value).length}</button>)}</div>
    <details className="wm-trade-watch-help"><summary>{cn ? '大额成交说明' : 'About the large-fill sample'}</summary><p>{cn ? '近期大额成交样本；成交额分级不表示钱包获利能力或内幕交易。' : 'Recent large-fill sample. Size tiers do not establish wallet skill or insider activity.'}</p></details>
    {feed.data && !visible.length && <p role="status">{cn ? '当前筛选下没有大额成交。' : 'No large trades match this filter.'}</p>}
    {visible.map(item => <TradeCard key={item.id} item={item} onSelect={ctx.setSelectedMarketId} />)}
  </TradeFeedFrame>;
}
const renderers: PanelRenderMap<'setSelectedMarketId'> = { 'whale-tracker': { render: ctx => <TradeFeedBoundary title="WHALE TRACKER"><WhaleView ctx={ctx} /></TradeFeedBoundary> } };
export const panel = panelFromRenderer(renderers, { id: 'whale-tracker', title: 'Whale Tracker', eyebrow: 'chain',
  contextKeys: ['setSelectedMarketId'], description: 'Recent canonical large fills with exact identities and bounded freshness.', defaultEnabled: true });
