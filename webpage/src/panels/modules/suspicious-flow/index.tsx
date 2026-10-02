import { useState } from 'preact/hooks';
import { panelFromRenderer } from '@/panels/definePanel';
import type { PanelInputs, PanelRenderMap } from '@/panels/types';
import { TradeCard, TradeFeedBoundary, TradeFeedFrame } from '@/panels/shared/trade-feed/components';
import { useI18n } from '@/services/i18n';
import { useFlowFeed } from './useFlowFeed';

function FlowView({ ctx }: { ctx: PanelInputs<'setSelectedMarketId'> }) {
  const feed = useFlowFeed(), i18n = useI18n(), cn = i18n.locale.startsWith('zh');
  const [filter, setFilter] = useState('all');
  const items = feed.data?.items || [], visible = items.filter(item => filter === 'all' || item.observationType === filter);
  const associationUnavailable = ['oracle', 'oracleTrades'].some(key => (feed.data?.sourceStates[key] as { status?: string } | undefined)?.status === 'error');
  const filters = [{ id: 'all', label: cn ? '全部' : 'All' }, { id: 'oracle-linked', label: cn ? 'Oracle 关联' : 'Oracle-linked' }, { id: 'large-trade', label: cn ? '大额成交' : 'Large trades' }];
  return <TradeFeedFrame title="FLOW WATCH" feed={feed}>
    <div className="wm-trade-watch-tabs" aria-label={cn ? '观测类型筛选' : 'Observation filters'}>{filters.map(value => <button type="button" key={value.id} aria-pressed={filter === value.id} onClick={() => setFilter(value.id)}>{value.label} {items.filter(item => value.id === 'all' || item.observationType === value.id).length}</button>)}</div>
    <details className="wm-trade-watch-help"><summary>{cn ? '成交观测说明' : 'About these observations'}</summary><p>{cn ? 'Oracle 关联表示同市场、事件前六小时内的成交；大额成交没有已确认的 Oracle 关系。成交额分级不表示异常概率。' : 'Oracle-linked means a same-market fill within six hours before an event. Large trades have no established Oracle relationship. Size tiers are not anomaly probabilities.'}</p>
    {feed.data && items.length > 0 && items.every(item => item.observationType === 'large-trade') && <p>{associationUnavailable ? cn ? '当前无法核验 Oracle 关联，以下为大额成交观测。' : 'Oracle association unavailable; showing large-trade observations.' : cn ? '当前样本未匹配到 Oracle 关联成交，以下为大额成交观测。' : 'No Oracle-linked fills in this sample; showing large-trade observations.'}</p>}</details>
    {feed.data && !visible.length && <p role="status">{cn ? '当前筛选下没有成交观测。' : 'No observations match this filter.'}</p>}
    {visible.map(item => <TradeCard key={item.id} item={item} showType onSelect={ctx.setSelectedMarketId} />)}
  </TradeFeedFrame>;
}
const renderers: PanelRenderMap<'setSelectedMarketId'> = { 'suspicious-flow': { render: ctx => <TradeFeedBoundary title="FLOW WATCH"><FlowView ctx={ctx} /></TradeFeedBoundary> } };
export const panel = panelFromRenderer(renderers, { id: 'suspicious-flow', title: 'Flow Watch', eyebrow: 'chain', contextKeys: ['setSelectedMarketId'],
  description: 'Oracle-linked observations and explicitly identified large trades.', defaultEnabled: true });
