import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, EvidenceLink, valid, type CulturePayload } from '../../shared/culture-tech';
import { countMentions, mentionPattern } from './model';

function Body({ data }: { data?: CulturePayload }) {
  const [selected,setSelected]=useState(''), [term,setTerm]=useState('inflation');
  const rows=data?.items||[], row=rows.find(r=>r.id===selected)||rows[0];
  const paragraphs=Array.isArray(row?.paragraphs)?row.paragraphs.filter((v):v is string=>typeof v==='string'):[];
  const pattern=mentionPattern(term), highlight=mentionPattern(term,true);
  const hits=countMentions(paragraphs,term);
  const matching=pattern?paragraphs.filter(p=>{pattern.lastIndex=0;return pattern.test(p);}):[];
  return <Frame id="mentions-evidence" title="MENTIONS EVIDENCE" data={data}>
    <div className="wm-ct-scope"><b>FED · OFFICIAL WRITTEN REMARKS</b></div>
    <select aria-label="Written speech" value={row?.id} onChange={e=>setSelected(e.currentTarget.value)}>{rows.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select>
    <label className="wm-ct-meta">Exact English word / phrase <input aria-label="Mention term" value={term} maxLength={40} onInput={e=>setTerm(e.currentTarget.value)}/></label>
    <div className="wm-ct-dual"><div><strong>{hits===null?'—':hits}</strong><small>matches in acquired text</small></div><div><strong>{paragraphs.length||'—'}</strong><small>acquired paragraphs</small></div></div>
    <p className="wm-ct-note">Written text only · audio, timestamps and delivery not verified</p>
    {matching.slice(0,8).map((p,i)=><blockquote className="wm-ct-quote" key={i}>{highlight?p.slice(0,900).split(highlight).map((piece,j)=>j%2?<mark key={j}>{piece}</mark>:piece):p.slice(0,900)}</blockquote>)}
    {!paragraphs.length&&<p className="wm-ct-warning">Official speech text not yet acquired; no zero count inferred.</p>}
    {row&&<EvidenceLink row={row}>Original written remarks</EvidenceLink>}
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "mentions-evidence", title: "MENTIONS EVIDENCE", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 600000, maxAgeMs: 10800000 });
