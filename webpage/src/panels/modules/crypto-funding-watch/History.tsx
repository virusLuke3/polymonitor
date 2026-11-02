import { Series, Notice, Stats, fmt, useCopy } from '@/panels/shared/crypto-strategy/components';
import { useCryptoInputs, useCryptoAsset } from '@/panels/shared/crypto-strategy/resource';
import { ASSETS } from '@/panels/shared/crypto-strategy/model';

export function FundingHistory() {
  const feed=useCryptoInputs(), [asset,select]=useCryptoAsset(), t=useCopy(), points=feed.data?.assets[asset]?.fundingHistory||[];
  const last=points[points.length-1]?.v;
  const percentile=last==null||points.length<2?null:points.filter(p=>p.v<=last).length/points.length*100;
  return <details className="wm-cstrategy-panel"><summary>{t('历史已结算费率','Settled funding history')} · {asset}</summary>
    <p className="wm-cstrategy-meta">{t('历史采集快照','History snapshot')} · {feed.data?.generatedAt ? new Date(feed.data.generatedAt).toLocaleString() : '—'} · {feed.status.phase.toUpperCase()}</p>
    <div className="wm-cstrategy-tabs">{ASSETS.map(a=><button key={a} aria-pressed={asset===a} onClick={()=>select(a)}>{a}</button>)}</div>
    <Stats items={[{label:t('最近结算 %','Last settlement %'),value:fmt(last,5)},{label:t('样本分位','Sample percentile'),value:fmt(percentile,1)+'%'},{label:t('已结算样本','Settled samples'),value:String(points.length)}]}/>
    <Series points={points} label="Bybit · funding % / settlement" maxGapMs={25*3600000}/>
    <Notice>{t('当前历史仅接入 Bybit 最近至多100次结算；分位基于这组样本，不代表长期极端程度。当前各交易所报价仍分别显示实际周期。','History covers up to 100 Bybit settlements. Percentile is sample-scoped; current venue quotations retain their actual periods.')}</Notice>
  </details>;
}
