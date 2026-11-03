import { useEffect, useState } from 'preact/hooks';
import { panelFromRenderer } from '@/panels/definePanel';
import { Frame, MarketLink, Notice, Series, Stats, direction, signed, fmt, time, useCopy } from '@/panels/shared/crypto-strategy/components';
import { useCryptoAsset, useCryptoInputs } from '@/panels/shared/crypto-strategy/resource';
import { referenceUsable } from '@/panels/shared/crypto-strategy/model';

function Reference() {
  const feed=useCryptoInputs(), [asset]=useCryptoAsset(), t=useCopy(), ref=feed.data?.references[asset], market=ref?.market;
  const [now,setNow]=useState(Date.now);
  // Display-only clock: validity must expire even when network refreshes fail.
  useEffect(()=>{const id=window.setInterval(()=>setNow(Date.now()),1000);return()=>window.clearInterval(id);},[]);
  const usable=referenceUsable(ref,now), value=Number(ref?.latest?.value), current=Number.isFinite(value)&&value>0?value:null;
  const anchorValue=Number(market?.anchor?.value), anchor=Number.isFinite(anchorValue)&&anchorValue>0?anchorValue:null;
  const at=ref?.latest?.event_at_ms, fresh=!!at && now-at>=-1000 && now-at<=15000 && ref?.status==='ok';
  const distance=usable && current!=null && anchor!=null?current-anchor:null;
  const message=current==null ? t('当前服务未提供该币种的指定源观测。','This service has no designated-source observations for this asset.')
    : !fresh ? t('观测已过期，以下保留最后价格与原始时间；当前距离不可用。','Observation expired. Last price and original time retained; current distance unavailable.')
    : market && market.ends_at_ms<=now ? t('合约已结束；等待当轮合约绑定。','Contract ended; awaiting the current market binding.')
    : !usable ? t('已收到指定源价格；尚无核验通过的当轮合约绑定。','Source price received; current contract binding is not verified.')
    : anchor==null ? t('当轮开盘阈值尚未核验，当前距离不可用。','Opening threshold is not verified; current distance unavailable.') : null;
  return <Frame id="crypto-oracle-reference" title={t('合约指定价格源','CONTRACT REFERENCE')} badge="TWAP">
    {message && !feed.loading && <p className="wm-cstrategy-notice" data-tone="warning" role="status">{message}</p>}
    {current!=null && <>
      <Stats items={[{label:fresh?t('指定源 USD','Reference USD'):t('最后观测 USD','Last observed USD'),value:fmt(current),tone:fresh?'info':'warning',primary:true},{label:t('目标价 USD','Price to beat USD'),value:fmt(usable?anchor:null),tone:'warning'},{label:t('距离阈值 USD','Distance USD'),value:signed(distance),tone:direction(distance)}]}/>
      <Series points={ref?.history} label={t('官方 60秒 TWAP · USD','Official 60s TWAP · USD')} maxGapMs={3000} tone={fresh?'info':'warning'}/>
      <p className="wm-cstrategy-meta">{ref?.latest?.feed_id} · {time(at)}</p>
    </>}
    {usable && market && <p className="wm-cstrategy-meta">{t('截止','Ends')} {time(market.ends_at_ms)} · {market.window_seconds}s TWAP · UP {market.comparator} {t('开盘阈值','opening threshold')}</p>}

    <details><summary>{t('规则与来源证据','Rules and source evidence')}</summary><Notice>{t('展示官方滚动 TWAP 观测。窗口内原始采样尚未接入，暂不计算“已固定贡献”或剩余窗口概率。','Official rolling TWAP observations. Raw window samples are unavailable; fixed contribution and remaining-window probability are not calculated.')}</Notice><p>{t("最后观测","Last observation")}: {fmt(current)} USD · {time(ref?.latest?.event_at_ms)}</p><p>{market?.anchor?.source} · {market?.anchor?.precision}</p><p>{t('开盘对齐','Opening alignment')}: {market?.opening_alignment?.status || '—'}</p><code>{market?.rule_version}</code><p><code>{ref?.latest?.full_accuracy_value}</code> E18</p>{market?.rule_url?.startsWith('https://data.chain.link/') && <a href={market.rule_url} target="_blank" rel="noopener noreferrer">{t('指定 feed','Designated feed')} ↗</a>}</details>
    {market && <MarketLink reference={ref}/>}
  </Frame>;
}
export const panel=panelFromRenderer({'crypto-oracle-reference':{render:()=> <Reference/>}}, {id:'crypto-oracle-reference',title:'Contract Reference',eyebrow:'macro',description:'Exact contract, threshold and designated price feed evidence.',defaultEnabled:true});
