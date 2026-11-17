import { Panel } from '@/components/Panel';
import { runtimePanelFromRenderer } from '@/panels/definePanel';
import { publicFeedSnapshot } from '@/panels/shared/public-feed-snapshot';
import type { PanelRenderMap } from '@/panels/types';
import { fetchRuntimeSmartMoneySignals } from '@/services/api';
import { useI18n } from '@/services/i18n';
import './styles.css';

const LIMIT = 12;
const snapshotContract = publicFeedSnapshot('alpha-signal', LIMIT);

interface SignalCard {
  id: string;
  title: string;
  eventSlug: string;
  outcome: string;
  side: 'BUY' | 'SELL';
  wallet: string;
  amountUsdc: string;
  averagePrice: string;
  fragments: number;
  tradedAt: string;
  tags: string[];
}

interface SignalSnapshot {
  sourceObservedAt: string | null;
  status: string;
  items: SignalCard[];
}

function AlphaSignal({ snapshot }: { snapshot?: SignalSnapshot }) {
  const i18n = useI18n();
  const chinese = i18n.locale.startsWith('zh');
  const copy = (en: string, zh: string) => chinese ? zh : en;
  const format = new Intl.NumberFormat(i18n.locale, { maximumFractionDigits: 4 });
  const items = snapshot?.items ?? [];

  return <Panel title="ALPHA SIGNAL" badge="SMART MONEY" count={items.length} className="wm-alpha-signal-panel">
    {snapshot?.status === 'stale' && <p className="wm-alpha-clock" role="status">{copy('Showing saved signals. The latest available trade is over 15 minutes old.', '正在展示已保存信号，最新可用成交距今已超过 15 分钟。')}</p>}
    {snapshot?.sourceObservedAt && <p className="wm-alpha-clock">{copy('Latest source trade', '来源最新成交')} <time dateTime={snapshot.sourceObservedAt}>{i18n.formatDateTime(snapshot.sourceObservedAt)}</time></p>}
    {snapshot && !items.length && <p role="status">{copy('No matched trade signals are available.', '暂无可展示的筛选信号。')}</p>}
    {items.map(item => <article className={item.side === 'SELL' ? 'wm-alpha-card is-sell' : 'wm-alpha-card'} key={item.id}>
      <div className="wm-alpha-card-heading">
        <b>{item.side === 'BUY' ? copy('Buy', '买入') : copy('Sell', '卖出')} {item.outcome}</b>
        <time dateTime={item.tradedAt}>{i18n.formatDateTime(item.tradedAt)}</time>
      </div>
      {item.eventSlug ? <a className="wm-alpha-market" href={`https://polymarket.com/event/${encodeURIComponent(item.eventSlug)}`} target="_blank" rel="noopener noreferrer">{item.title}</a> : <strong className="wm-alpha-market">{item.title}</strong>}
      <dl className="wm-alpha-metrics">
        <div><dt>{copy('Trade value', '成交金额')}</dt><dd>{format.format(Number(item.amountUsdc))} USDC</dd></div>
        <div><dt>{copy('Average fill price', '成交均价')}</dt><dd>{format.format(Number(item.averagePrice) * 100)}¢</dd></div>
        <div><dt>{copy('Wallet', '钱包')}</dt><dd title={item.wallet}>{item.wallet.slice(0, 8)}…{item.wallet.slice(-6)}</dd></div>
        <div><dt>{copy('Matched fills', '合并成交')}</dt><dd>{item.fragments}</dd></div>
      </dl>
      {!!item.tags.length && <p className="wm-alpha-tags">{item.tags.join(' / ')}</p>}
    </article>)}
  </Panel>;
}

const renderers: PanelRenderMap<never> = {
  'alpha-signal': { render: ctx => <AlphaSignal snapshot={ctx.runtimeData['alpha-signal'] as SignalSnapshot | undefined} /> },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'alpha-signal',
  snapshot: { ...snapshotContract, parse: (value) => {
    if ((value as { source?: string } | null)?.source !== 'matched-trades-v1') throw new Error('Smart Money snapshot unavailable');
    return snapshotContract.parse(value);
  } },
  title: 'Alpha Signal',
  eyebrow: 'signal',
  description: 'Matched trade signals from the Smart Money worktree.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 300_000,
  limit: LIMIT,
  fetchData: (context, limit) => fetchRuntimeSmartMoneySignals(limit, context?.signal),
});
