import { useState } from 'preact/hooks';
import { panelFromRenderer } from '@/panels/definePanel';
import { Frame, Notice, Series, Stats, direction, signed, signedCompact, compact, fmt, useCopy } from '@/panels/shared/crypto-strategy/components';
import { useCryptoInputs } from '@/panels/shared/crypto-strategy/resource';

function Inflows() {
  const feed=useCryptoInputs(), [exchange,setExchange]=useState('Binance'), [days,setDays]=useState(30), t=useCopy(), data=feed.data?.inflows;
  const available=(data?.rows||[]).filter(r=>r.exchange===exchange).sort((a,b)=>a.date.localeCompare(b.date));
  const end=Date.parse(available[available.length-1]?.date||'');
  const rows=available.filter(r=>Date.parse(r.date)>end-days*86400000);
  return <Frame id="crypto-exchange-inflow" title={t('交易所链上流入','EXCHANGE INFLOWS')} badge="HISTORICAL" assets={false} filters={<div className="wm-panel-tabs">{['Binance','Coinbase'].map(e=><button key={e} aria-pressed={exchange===e} onClick={()=>setExchange(e)}>{e}</button>)}{[30,90,180].map(d=><button key={d} aria-pressed={days===d} onClick={()=>setDays(d)}>{d}d</button>)}</div>}>

    <p className="wm-cstrategy-meta" data-tone="warning">{t('历史 BTC · 非实时流入','Historical BTC research · not live')}</p>
    {rows.length ? <>
    <Stats items={[{label:t('流入 BTC','Inflow BTC'),value:compact(rows.reduce((s,r)=>s+r.inflow,0)),tone:'info'},{label:t('流出 BTC','Outflow BTC'),value:compact(rows.reduce((s,r)=>s+r.outflow,0)),tone:'warning'},{label:t('净流入 BTC','Net BTC'),value:signedCompact(rows.reduce((s,r)=>s+r.net,0)),tone:direction(rows.reduce((s,r)=>s+r.net,0))}]}/>
    <p className="wm-cstrategy-meta">{rows[0]?.date || '—'} — {rows[rows.length-1]?.date || '—'}</p>
    <Series points={rows.map(r=>({t:Date.parse(r.date+'T00:00:00Z'),v:r.net}))} label={t('每日净转入 · BTC','Daily matched net transfers · BTC')} maxGapMs={86400001} tone={direction(rows[rows.length-1]?.net)}/>
    <table className="wm-cstrategy-table"><thead><tr><th>{t('日期','Date')}</th><th>{t('流入','Inflow')}</th><th>{t('流出','Outflow')}</th><th>{t('净额','Net')}</th></tr></thead><tbody>{rows.slice(-10).reverse().map(r=><tr key={r.date}><td>{r.date.slice(5)}</td><td data-tone="info">{fmt(r.inflow)}</td><td data-tone="warning">{fmt(r.outflow)}</td><td data-tone={direction(r.net)}>{signed(r.net)}</td></tr>)}</tbody></table>
    </> : <p className="wm-cstrategy-empty" role="status">{t('该交易所暂无历史流入数据。','No historical inflow data for this exchange.')}</p>}
    <details><summary>{t('覆盖与标签口径','Coverage and labels')}</summary><Notice>{t('历史研究 · BTC · 实时流入未接入。地址标签为事后获取，转入交易所不等于已经卖出。','Historical BTC research; live inflows unavailable. Retrospectively retrieved labels; exchange transfers are not sales.')}</Notice><p>{data?.datasetId || t('历史来源未配置','Historical source is not configured')}</p><p>{data?.labelSemantics} · {compact(data?.transactions)} {t('交易','transactions')}</p><p>{t('仅覆盖有标签地址；同交易所已匹配输入输出净额相抵，未识别内部转账仍可能存在。','Only labeled addresses; matched same-exchange legs are netted. Unidentified internal transfers may remain.')}</p></details>
  </Frame>;
}
export const panel=panelFromRenderer({'crypto-exchange-inflow':{render:()=> <Inflows/>}}, {id:'crypto-exchange-inflow',title:'Exchange Inflows',eyebrow:'macro',description:'Historical labeled BTC exchange transfers with explicit live-data gaps.',defaultEnabled:true});
