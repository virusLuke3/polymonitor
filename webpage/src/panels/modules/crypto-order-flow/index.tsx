import { panelFromRenderer } from '@/panels/definePanel';
import { Frame, MarketLink, Notice, Series, Stats, compact, fmt, time, useCopy } from '@/panels/shared/crypto-strategy/components';
import { useCryptoAsset, useCryptoInputs } from '@/panels/shared/crypto-strategy/resource';

function Flow() {
  const feed=useCryptoInputs(), [asset]=useCryptoAsset(), t=useCopy(), row=feed.data?.assets[asset], flow=row?.flow, depth=row?.depth;
  return <Frame id="crypto-order-flow" title={t('交易所订单流','CRYPTO ORDER FLOW')} badge="SPOT">
    <Stats items={[{label:t('净主动买入 USDT','Net taker buy USDT'),value:compact(flow?.net)},{label:t('成交样本','Trade sample'),value:String(flow?.count ?? '—')},{label:t('深度失衡','Depth imbalance'),value:fmt(depth?.imbalance==null?null:depth.imbalance*100)+'%'}]}/>
    <Series points={flow?.cvd} label={t('样本累计主动买卖差 · USDT','Sample cumulative signed trades · USDT')} maxGapMs={60000}/>
    <p className="wm-cstrategy-meta">Bybit · {time(flow?.from)} — {time(flow?.to)} · {flow?.count ?? '—'}/{flow?.limit ?? 60}</p>
    <Notice>{t('最近至多60笔现货成交，非完整时间窗。深度失衡来自当前盘口快照；增量 OFI 与跨交易所验证尚未接入。','Up to 60 recent spot trades, not a complete interval. Depth is a snapshot imbalance; incremental OFI and cross-venue validation are unavailable.')}</Notice>
    <details><summary>{t('盘口深度','Order book depth')} · {depth?.levels ?? '—'} {t('档','levels')}</summary><table className="wm-cstrategy-table"><thead><tr><th>Bid</th><th>{asset}</th><th>Ask</th><th>{asset}</th></tr></thead><tbody>{Array.from({length:Math.max(depth?.bids?.length||0,depth?.asks?.length||0)},(_,i)=><tr key={i}><td>{fmt(depth?.bids[i]?.[0])}</td><td>{fmt(depth?.bids[i]?.[1],4)}</td><td>{fmt(depth?.asks[i]?.[0])}</td><td>{fmt(depth?.asks[i]?.[1],4)}</td></tr>)}</tbody></table></details>
    <details><summary>{t('最近成交','Recent trades')}</summary><table className="wm-cstrategy-table"><tbody>{flow?.trades?.slice().reverse().map(trade=><tr key={trade.id}><td>{time(trade.t)}</td><td>{trade.side}</td><td>{fmt(trade.price)}</td><td>{fmt(trade.size,4)}</td></tr>)}</tbody></table></details>
    <MarketLink reference={feed.data?.references[asset]}/>
  </Frame>;
}
export const panel=panelFromRenderer({'crypto-order-flow':{render:()=> <Flow/>}}, {id:'crypto-order-flow',title:'Crypto Order Flow',eyebrow:'macro',description:'Signed exchange trade samples and visible book depth.',defaultEnabled:true});
