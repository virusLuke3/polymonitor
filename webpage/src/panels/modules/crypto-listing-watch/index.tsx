import { useState } from 'preact/hooks';
import { externalPanel, isBasePayload, record, type BasePayload } from '../../shared/external/resource';
import { Empty, Frame, Tabs, useCopy } from '../../shared/finance-expansion/ui';
import './styles.css';
type Product={id:string;base:string;quote:string;status:string;mode:string};
type Data=BasePayload&{products?:Product[];availableProducts?:number;usdProducts?:number;truncated?:boolean};
export function validate(v:unknown):v is Data{const raw=v as Record<string,unknown>;return isBasePayload(v)&&record(raw)&&(raw.products===undefined||Array.isArray(raw.products)&&raw.products.length<=300&&raw.products.every(p=>record(p)&&['id','base','quote','status','mode'].every(k=>typeof p[k]==='string')));}
function View({data}:{data?:Data}){
 const t=useCopy(),[query,setQuery]=useState(''),[filter,setFilter]=useState('all'),[selected,setSelected]=useState('BTC-USD');
 const products=data?.products??[],rows=products.filter(p=>(p.id.toLowerCase().includes(query.toLowerCase()))&&(filter==='all'||filter==='online'&&p.mode==='online'||filter==='restricted'&&p.mode!=='online')).sort((a,b)=>Number(b.base===query.toUpperCase())-Number(a.base===query.toUpperCase()));
 const item=rows.find(p=>p.id===selected)??rows[0];
 const mode=(v:string)=>({online:t('交易模式开放','Trading enabled'),disabled:t('交易关闭','Trading disabled'),'cancel-only':t('仅撤单','Cancel only'),'post-only':t('仅挂单','Post only'),'limit-only':t('仅限价','Limit only'),auction:t('竞价模式','Auction'),unknown:t('状态待核实','Mode unknown')}[v]??v);
 return <Frame id="crypto-listing-watch" title={t('代币上市观察','CRYPTO LISTING WATCH')} data={data}>
 <div className="fx-kicker">COINBASE EXCHANGE · USD</div><input aria-label={t('查找交易对','Find trading pair')} placeholder="BTC / ETH / SOL…" value={query} onInput={e=>setQuery(e.currentTarget.value)}/>
 <Tabs values={[[ 'all',t('全部','All')],['online',t('开放','Enabled')],['restricted',t('限制','Restricted')]]} value={filter} set={setFilter}/>
 {item?<><select aria-label={t('交易对','Product')} value={item.id} onChange={e=>setSelected(e.currentTarget.value)}>{rows.map(p=><option key={p.id} value={p.id}>{p.id} · {mode(p.mode)}</option>)}</select>
 <div className="listing-live-title"><strong>{item.base}</strong><span>{item.quote} · {item.status}</span></div>
 <div className={`listing-live-mode ${item.mode==='online'?'enabled':''}`}>{mode(item.mode)}</div>
 <div className="listing-live-stages">{[[t('公告','Notice'),'—'],[t('充币','Deposit'),'—'],[t('交易','Trading'),mode(item.mode)],[t('提币','Withdrawal'),'—']].map(([label,status])=><div key={label}><i aria-hidden="true">{label===t('交易','Trading')?'●':'○'}</i><b>{label}</b><small>{status}</small></div>)}</div>
 <p className="fx-note">{t('这是当前产品模式，不代表首次上市日期或已发生成交；充提状态需另行证实。','Current product mode does not establish a first listing or executed trade. Deposit and withdrawal states require separate evidence.')}</p>
 </>:<Empty data={data}/>}
 <div className="fx-kicker">{rows.length} {t('当前筛选','matching')} / {data?.usdProducts??'—'} USD · {data?.availableProducts??'—'} {t('全部产品','all products')}</div>
 </Frame>;
}
export const panel=externalPanel<Data>({id:'crypto-listing-watch',title:'Crypto Listing Watch',description:'Exchange product modes with independent listing, transfer and trading evidence.',validate,render:data=><View data={data}/>,intervalMs:300000,maxAgeMs:900000,retentionMs:1800000});
