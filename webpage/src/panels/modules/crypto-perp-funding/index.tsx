import { useState } from 'preact/hooks';
import { panelFromRenderer } from '@/panels/definePanel';
import { Frame, MarketLink, Notice, Series, Stats, direction, signed, compact, fmt, useCopy } from '@/panels/shared/crypto-strategy/components';
import { useCryptoAsset, useCryptoInputs } from '@/panels/shared/crypto-strategy/resource';
import { change } from '@/panels/shared/crypto-strategy/model';

function Derivatives() {
  const feed=useCryptoInputs(), [asset]=useCryptoAsset(), [window,setWindow]=useState(15), t=useCopy();
  const row=feed.data?.assets[asset], history=row?.oiHistory || [], cutoff=(history[history.length-1]?.t || 0)-window*60000;
  return <Frame id="crypto-perp-funding" title={t('持仓与基差','CRYPTO DERIVATIVES')} badge="OI / BASIS" filters={<div className="wm-panel-tabs">{[15,60,240].map(w=><button key={w} aria-pressed={window===w} onClick={()=>setWindow(w)}>{w<60?`${w}m`:`${w/60}h`}</button>)}</div>}>

    {row?.linear ? <>
    <Stats items={[{label:'OI · '+asset,value:compact(row?.linear?.oi),tone:'info',primary:true},{label:t('OI 变化','OI change'),value:signed(change(history,window),2,'%'),tone:direction(change(history,window))},{label:'OI · USDT',value:compact(row?.linear?.oiValue)}]}/>
    <Series points={history.filter(p=>p.t>=cutoff)} label={`Bybit OI · ${asset}`} maxGapMs={360000}/>
    <Stats items={[{label:t('期现基差 bps','Mark / spot bps'),value:signed(row?.basisBps),tone:direction(row?.basisBps)},{label:t('标记/指数 bps','Mark / index bps'),value:signed(row?.premiumBps),tone:direction(row?.premiumBps)},{label:t('指数价 USDT','Index USDT'),value:fmt(row?.linear?.index)}]}/>
    <Series points={row?.basisHistory} label={t('期现基差 · bps','Mark / spot basis · bps')} tone={direction(row?.basisBps)}/>
    <Notice>{t('Bybit USDT 永续。基差使用分别请求的标记价与现货成交价；OI 历史为 5 分钟观测。','Bybit USDT perpetual. Basis uses separately requested mark and spot last; OI history has 5-minute observations.')}</Notice>
    </> : <p className="wm-cstrategy-empty" role="status">{t('当前币种暂无永续持仓与基差数据。','No perpetual OI or basis data available for this asset.')}</p>}
    <MarketLink reference={feed.data?.references[asset]}/>
  </Frame>;
}
export const panel=panelFromRenderer({'crypto-perp-funding':{render:()=> <Derivatives/>}}, {id:'crypto-perp-funding',title:'Crypto Derivatives',eyebrow:'macro',description:'Open interest and explicit mark/spot and mark/index basis.',defaultEnabled:true});
