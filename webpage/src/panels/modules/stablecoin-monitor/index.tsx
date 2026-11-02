import { useState } from 'preact/hooks';
import { panelFromRenderer } from '@/panels/definePanel';
import { Frame, Notice, Series, Stats, fmt, time, useCopy } from '@/panels/shared/crypto-strategy/components';
import { useCryptoInputs } from '@/panels/shared/crypto-strategy/resource';

function Stablecoins() {
  const feed=useCryptoInputs(), [symbol,setSymbol]=useState('USDC'), t=useCopy();
  const rows=feed.data?.stablecoins.filter(r=>r.asset===symbol)||[], available=rows.filter(r=>r.price!=null);
  const mean=available.length?available.reduce((s,r)=>s+r.price!,0)/available.length:null;
  const spread=available.length>1?(Math.max(...available.map(r=>r.price!))-Math.min(...available.map(r=>r.price!)))*10000:null;
  return <Frame id="stablecoin-monitor" title={t('稳定币压力','STABLECOINS')} badge="USD PEG" assets={false} filters={<div className="wm-panel-tabs">{['USDC','USDT'].map(s=><button key={s} aria-pressed={symbol===s} onClick={()=>setSymbol(s)}>{s}</button>)}</div>}>

    {rows.length ? <>
    <Stats items={[{label:t('来源均价 USD','Source mean USD'),value:fmt(mean,4)},{label:t('来源差异 bps','Source spread bps'),value:fmt(spread)},{label:t('可用来源','Available sources'),value:available.length+'/'+rows.length}]}/>
    {rows.map(row=><section key={row.source}><Series points={row.history} label={row.source+' · '+t('偏离 bps','deviation bps')}/><p className="wm-cstrategy-meta">{row.source} · ${fmt(row.price,4)} · {time(row.receivedAt)} · {row.status.toUpperCase()}</p>{row.observedStressSeconds!=null && <p className="wm-cstrategy-meta">{t('观测到偏离≥20 bps 持续','Observed deviation ≥20 bps for')} {fmt(row.observedStressSeconds/60,1)}m</p>}</section>)}
    </> : <p className="wm-cstrategy-empty" role="status">{t('当前币种暂无美元报价来源。','No USD quote sources available for this stablecoin.')}</p>}
    <Notice>{t('美元报价。持续时间仅覆盖连续采样，断点会重置；来源未提供逐笔时刻，显示接收时间。','USD quotations. Duration covers continuous samples only and resets across gaps; receipt time is shown where native quote time is unavailable.')}</Notice>
  </Frame>;
}
export const panel=panelFromRenderer({'stablecoin-monitor':{render:()=> <Stablecoins/>}}, {id:'stablecoin-monitor',title:'Stablecoin Pressure',eyebrow:'macro',description:'USD peg deviation across sources and observed persistence.',defaultEnabled:true});
