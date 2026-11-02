import { useState } from 'preact/hooks';
import { panelFromRenderer } from '@/panels/definePanel';
import { Frame, Notice, Stats, fmt, time, useCopy } from '@/panels/shared/crypto-strategy/components';
import { useCryptoAsset, useCryptoInputs } from '@/panels/shared/crypto-strategy/resource';

function Options() {
  const feed=useCryptoInputs(), [asset]=useCryptoAsset(), [expiry,setExpiry]=useState(''), [near,setNear]=useState(true), t=useCopy();
  const data=feed.data?.options[asset], expiries=data?.expiries || [], selected=expiries.find(e=>e.expiry===expiry)||expiries[0];
  const bands=selected?.bands.filter(b=>!near || Math.abs(b.strike/selected.underlying-1)<.15) || [];
  const lower=bands[0]?.lowerStrike||0, upper=bands[bands.length-1]?.upperStrike||1;
  const x=(strike:number)=>8+(strike-lower)/(upper-lower||1)*284;
  return <Frame id="options-implied-probability" title={t('期权隐含概率','OPTIONS IMPLIED')} badge="RISK NEUTRAL" filters={expiries.length > 0 && <div className="wm-panel-tabs"><select aria-label={t('期权到期','Option expiry')} value={selected?.expiry||''} onChange={e=>setExpiry(e.currentTarget.value)}>{expiries.map(e=><option key={e.expiry} value={e.expiry}>{new Date(e.expiry).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</option>)}</select><button aria-pressed={near} onClick={()=>setNear(!near)}>{t(near?'邻近执行价':'全部执行价',near?'Near strikes':'All strikes')}</button></div>}>

    {selected && <Stats items={[{label:t('远期参考 USD','Underlying USD'),value:fmt(selected?.underlying)},{label:t('有效阈值带','Valid strike bands'),value:String(bands.length)},{label:t('报价时间','Source time'),value:time(data?.observedAt)}]}/>}
    {selected && <p className="wm-cstrategy-meta">{t('Deribit · 风险中性参考 · 未匹配 PM 到期','Deribit · risk-neutral proxy · PM expiry unmatched')}</p>}
    {selected && bands.length === 0 && <Notice>{t('当前执行价筛选无有效报价。','No valid quotes in this strike range.')}</Notice>}
    {!selected && <Notice>{t('当前没有有效期权报价支持的分布。首批覆盖 BTC / ETH。','No valid option distribution. Initial coverage: BTC / ETH.')}</Notice>}
    {bands.length>0 && <figure className="wm-cstrategy-chart"><figcaption>{t('阈值带尾概率 · 阴影为买卖报价范围','Tail proxy by strike band · shaded bid/ask range')}</figcaption><svg viewBox="0 0 300 84" role="img" aria-label={t('期权阈值带概率','Option strike-band probabilities')}>
      <path d="M8 12H292M8 42H292M8 72H292" className="wm-cstrategy-grid"/>
      {bands.map(b=><g key={b.strike}><rect x={x(b.lowerStrike)} y={72-b.high*60} width={Math.max(1,x(b.upperStrike)-x(b.lowerStrike)-1)} height={Math.max(1,(b.high-b.low)*60)} fill="var(--ds-color-info)" opacity=".16"/><path d={`M${x(b.lowerStrike)} ${72-b.probability*60}H${x(b.upperStrike)}`} stroke="var(--ds-color-info)" strokeWidth="1.6"/></g>)}
    </svg><div className="wm-cstrategy-meta"><span>${fmt(lower,0)}</span><span>${fmt(upper,0)}</span></div></figure>}
    {bands.length > 0 && <table className="wm-cstrategy-table"><thead><tr><th>{t('阈值带 USD','Strike band USD')}</th><th>{t('隐含参考','Tail proxy')}</th><th>{t('买卖报价范围','Bid/ask range')}</th></tr></thead><tbody>{bands.map(b=><tr key={b.strike}><td>{fmt(b.lowerStrike,0)}–{fmt(b.upperStrike,0)}</td><td>{fmt(b.probability*100,1)}%</td><td>{fmt(b.low*100,1)}–{fmt(b.high*100,1)}%</td></tr>)}</tbody></table>}
    <details><summary>{t('方法与报价身份','Method and instruments')}</summary><Notice>{t('Deribit 看涨价差 ÷ 执行价间距，折现因子假设为1；表示阈值带的平均风险中性尾概率参考。未匹配 PM 到期，不计算概率差。','Deribit call spread / strike width, discount factor assumed 1: a band-averaged risk-neutral tail proxy. PM expiry is unmatched; no probability gap is calculated.')}</Notice>
    <p>{selected?.expiry}</p><p>{data?.method}</p>{bands.slice(0,12).map(b=><p key={b.strike}>{b.instruments.join(' / ')} · mark IV {fmt(b.iv)}%</p>)}</details>
  </Frame>;
}
export const panel=panelFromRenderer({'options-implied-probability':{render:()=> <Options/>}}, {id:'options-implied-probability',title:'Options Implied Probability',eyebrow:'macro',description:'Quote-supported call-spread probability bands and expiry evidence.',defaultEnabled:true});
