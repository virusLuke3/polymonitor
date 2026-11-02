import { panelFromRenderer } from '@/panels/definePanel';
import { Frame, MarketLink, Notice, Series, Stats, fmt, time, useCopy } from '@/panels/shared/crypto-strategy/components';
import { useCryptoAsset, useCryptoInputs } from '@/panels/shared/crypto-strategy/resource';
import { referenceUsable } from '@/panels/shared/crypto-strategy/model';

function Reference() {
  const feed=useCryptoInputs(), [asset]=useCryptoAsset(), t=useCopy(), ref=feed.data?.references[asset], market=ref?.market;
  const usable=referenceUsable(ref), current=ref?.latest?.value ? Number(ref.latest.value):null, anchor=market?.anchor?.value ? Number(market.anchor.value):null;
  const seconds=market?Math.max(0,Math.floor((market.ends_at_ms-Date.now())/1000)):null;
  return <Frame id="crypto-oracle-reference" title={t('合约指定价格源','CONTRACT REFERENCE')} badge={ref?.status==='ok'?'TWAP':t('来源待恢复','SOURCE GAP')}>
    {usable ? <>
      <Stats items={[{label:t('指定源 USD','Reference USD'),value:fmt(current)},{label:t('目标价 USD','Price to beat USD'),value:fmt(anchor)},{label:t('距离阈值 USD','Distance USD'),value:fmt(current!=null && anchor!=null?current-anchor:null)}]}/>
      <Series points={ref?.history} label={t('指定源 TWAP · USD','Designated TWAP · USD')} maxGapMs={3000}/>
      <p className="wm-cstrategy-meta">{ref?.latest?.feed_id} · {time(ref?.latest?.event_at_ms)}</p>
    </> : <p className="wm-cstrategy-empty" role="status">{t('指定源陈旧、缺失或合约已过期；当前阈值距离不可用。','Stale/missing source or expired contract; current threshold distance is unavailable.')}</p>}
    {usable && market && <Stats items={[{label:t('剩余秒数','Seconds remaining'),value:seconds==null?'—':String(seconds)},{label:t('平均窗口','Average window'),value:market.window_seconds+'s'},{label:t('UP 条件','UP condition'),value:market.comparator}]}/>}

    <details><summary>{t('规则与来源证据','Rules and source evidence')}</summary><Notice>{t('展示官方滚动 TWAP 观测。窗口内原始采样尚未接入，暂不计算“已固定贡献”或剩余窗口概率。','Official rolling TWAP observations. Raw window samples are unavailable; fixed contribution and remaining-window probability are not calculated.')}</Notice><p>{t("最后观测","Last observation")}: {fmt(current)} USD · {time(ref?.latest?.event_at_ms)}</p><p>{market?.anchor?.source} · {market?.anchor?.precision}</p><p>{t('开盘对齐','Opening alignment')}: {market?.opening_alignment?.status || '—'}</p><code>{market?.rule_version}</code><p><code>{ref?.latest?.full_accuracy_value}</code> E18</p>{market?.rule_url?.startsWith('https://data.chain.link/') && <a href={market.rule_url} target="_blank" rel="noopener noreferrer">{t('指定 feed','Designated feed')} ↗</a>}</details>
    <MarketLink reference={ref}/>
  </Frame>;
}
export const panel=panelFromRenderer({'crypto-oracle-reference':{render:()=> <Reference/>}}, {id:'crypto-oracle-reference',title:'Contract Reference',eyebrow:'macro',description:'Exact contract, threshold and designated price feed evidence.',defaultEnabled:true});
