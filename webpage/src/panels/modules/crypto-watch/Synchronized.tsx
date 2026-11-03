import { useState } from 'preact/hooks';
import { Frame, MarketLink, Notice, Series, Stats, direction, signed, fmt, useCopy } from '@/panels/shared/crypto-strategy/components';
import { useCryptoAsset, useCryptoInputs } from '@/panels/shared/crypto-strategy/resource';
import { ASSETS, change } from '@/panels/shared/crypto-strategy/model';

export function Synchronized({ onOverview }: { onOverview: () => void }) {
  const feed=useCryptoInputs(), [asset]=useCryptoAsset(), [view,setView]=useState('prices'), t=useCopy();
  const row=feed.data?.assets[asset], ref=feed.data?.references[asset];
  const spot=ref?.spotHistory?.length ? ref.spotHistory : row?.spotHistory || [];
  const domain: [number,number] | undefined = spot.length > 1 ? [spot[0]!.t,spot[spot.length-1]!.t] : undefined;
  const quote=ref?.quotes?.UP;
  return <Frame id="crypto-watch" title={t('加密同步行情','CRYPTO')} badge="SPOT / PM" filters={<div className="wm-panel-tabs"><button aria-pressed={view==='prices'} onClick={()=>setView('prices')}>{t('同步行情','Prices')}</button><button aria-pressed={view==='strength'} onClick={()=>setView('strength')}>{t('相对强弱','Strength')}</button><button onClick={onOverview}>{t('全部币种','All coins')}</button></div>}>

    {view==='prices' ? <>
      <Stats items={[{label:`${asset} / USDT`,value:fmt(spot[spot.length-1]?.v ?? row?.spot?.price),primary:true},{label:t('15分钟变化','15m return'),value:signed(change(spot,15),2,'%'),tone:direction(change(spot,15))},{label:t('永续标记价','Perp mark'),value:fmt(row?.linear?.mark)}]}/>
      <Series points={spot} label={(ref?.spotHistory?.length ? 'Binance' : 'Bybit')+' SPOT · USDT'} domain={domain} tone={direction(spot.length > 1 ? spot[spot.length-1]!.v-spot[0]!.v : null)}/>
      <Series points={quote?.history?.filter(p=>!domain || p.t>=domain[0] && p.t<=domain[1]).map(p=>({...p,v:p.v*100}))} label="PM UP midpoint · ¢" domain={domain} tone="info"/>
      <Notice>{t('两图按同一时间轴观察。尚未计算领先时间或模型概率。','Shared time axis. Lead/lag and model probabilities are not calculated.')}</Notice>
    </> : <table className="wm-cstrategy-table"><thead><tr><th>{t('币种','Asset')}</th><th>5m %</th><th>15m %</th><th>1h %</th></tr></thead><tbody>{ASSETS.map(a=><tr key={a}><td>{a}</td>{[5,15,60].map(w=><td key={w} data-tone={direction(change(feed.data?.assets[a]?.spotHistory,w))}>{signed(change(feed.data?.assets[a]?.spotHistory,w))}</td>)}</tr>)}</tbody></table>}
    <p className="wm-cstrategy-meta">{t('现货以 USDT 计价；指定参考源以 USD 计价，分别保留。','Spot is quoted in USDT; designated reference is USD.')}</p>
    <MarketLink reference={ref}/>
  </Frame>;
}
