import { useState } from 'preact/hooks';
import { externalPanel,isBasePayload,record,type BasePayload } from '../../shared/external/resource';
import { Empty,Frame,SourceLink,date,useCopy } from '../../shared/finance-expansion/ui';
import './styles.css';
type Release={id:string;projectId:string;project:string;version:string;title:string;publishedAt:string;url:string;prerelease:boolean};
type Data=BasePayload&{releases:Release[]};
export function validate(v:unknown):v is Data{const raw=v as Record<string,unknown>;return isBasePayload(v)&&record(raw)&&Array.isArray(raw.releases)&&raw.releases.length<=100&&raw.releases.every(r=>record(r)&&['id','projectId','project','version','title','publishedAt','url'].every(k=>typeof r[k]==='string')&&typeof r.prerelease==='boolean');}
function View({data}:{data?:Data}){const t=useCopy(),[project,setProject]=useState('all');const all=data?.releases??[],rows=all.filter(r=>project==='all'||r.projectId===project),projects=[...new Map(all.map(r=>[r.projectId,r.project])).entries()];const first=rows[0];return <Frame id="crypto-project-milestones" title={t('项目里程碑','PROJECT MILESTONES')} data={data}>
 <select aria-label={t('项目','Project')} value={project} onChange={e=>setProject(e.currentTarget.value)}><option value="all">{t('所有已配置项目','All configured projects')}</option>{projects.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select>
 {first?<><div className="milestone-release-hero"><span className="fx-kicker">{first.project}</span><strong>{first.version}</strong><span>{first.prerelease?t('预发布版本','PRE-RELEASE'):t('已发布版本','PUBLISHED RELEASE')}</span></div>
 <div className="milestone-proof-lanes">{[[t('代码发布','Code release'),date(first.publishedAt),'yes'],[t('治理通过','Governance approved'),t('未核实','Not verified'),'unknown'],[t('主网执行','Mainnet execution'),t('未核实','Not verified'),'unknown']].map(([name,value,kind])=><div key={name} className={kind}><span>{name}</span><b>{value}</b></div>)}</div>
 <div className="milestone-release-timeline">{rows.slice(0,14).map(r=><article key={`${r.projectId}:${r.id}`}><time>{date(r.publishedAt)}</time><strong><SourceLink url={r.url}>{r.version}</SourceLink></strong><span>{r.project} · {r.prerelease?t('预发布','pre-release'):t('正式发布','release')}</span><p>{r.title}</p></article>)}</div>
 </>:<Empty data={data}/>}
 <p className="fx-note">{t('代码发布不等于主网升级；本视图不推断治理票数、执行回执或解锁事实。','A code release is not a mainnet upgrade. Governance votes, execution receipts and token unlocks are not inferred.')}</p></Frame>}
export const panel=externalPanel<Data>({id:'crypto-project-milestones',title:'Project Milestones',description:'Verified public repository releases and separate execution-evidence boundaries.',validate,render:data=><View data={data}/>,intervalMs:600000,maxAgeMs:5400000});
