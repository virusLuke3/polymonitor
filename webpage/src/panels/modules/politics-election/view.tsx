import { useState } from 'preact/hooks';
import { Bar, Empty, Evidence, Link, Note, Row, Scope, Shell, Stat, Tabs, useCopy } from '../../shared/politics/ui';
import { num, partyTone } from '../../shared/politics/model';
import type { Payload } from './model';

export function View({ data }: { data?: Payload }) {
  const t = useCopy(), [manualPhase, setPhase] = useState<string | null>(null), [selected, setSelected] = useState(''), [selectedPoll, setPoll] = useState('');
  const phase = manualPhase || data?.defaultPhase || 'polls', results = data?.results || [], race = results.find(r => r.id === selected) || results[0];
  const polls = data?.polls || [], poll = polls.find(r => r.id === selectedPoll) || polls[0], total = race?.choices.reduce((n, c) => n + c.votes, 0) || 0;
  return <Shell id="politics-election" title={t('选举观察', 'ELECTION WATCH')} data={data} explanation={t('民调、北卡官方发布的分区票数、认证分别展示。民调支持率不是胜选概率，票数文件不是选举夜实时源。', 'Polls, North Carolina published precinct tabulations and certification are separate. Support is not win probability; precinct files are not a live election-night feed.')}>
    <Tabs values={[[ 'polls', t('民调','Polls') ], ['counting',t('票数','Votes')],['certification',t('认证','Certification')]]} value={phase} set={setPhase}/>
    {phase === 'polls' ? poll ? <><select aria-label={t('选择民调','Select poll')} value={poll.id} onChange={e => setPoll(e.currentTarget.value)}>{polls.map(r => <option key={r.id} value={r.id}>{r.race} · {r.date} · {r.pollster}</option>)}</select><Scope name={poll.race.toUpperCase()} tag={poll.date}/>
      <div className="pol-stats">{poll.results.slice().sort((a,b) => b.value-a.value).slice(0,2).map((r,i) => <Stat key={r.name} label={r.name.replace(/-/g,' ')} value={`${num(r.value,1)}%`} tone={i ? 'purple':'blue'}/>)}</div>
      {poll.results.map((r,i) => <Bar key={r.name} label={r.name.replace(/-/g,' ')} value={`${num(r.value,1)}%`} percent={r.value} tone={i % 2 ? 'purple':'blue'}/>)}
      {Date.now()-Date.parse(poll.date)>30*86400000 && <Note>{t('这是较早发布的调查，不能代表当前选情。','This is an older survey, not a current election estimate.')}</Note>}
      <Row label={poll.pollster} value={`n = ${num(poll.sample)}`}/><Row label={poll.population} value={poll.marginOfError === null ? '—' : `±${poll.marginOfError}pp`}/>
      <Evidence><Link href={poll.url}>{t('原始民调','Original poll')}</Link><p>{data?.attribution}</p><p>{polls.length}/{data?.pollCount} {t('调查记录；支持率不能直接与 Market 胜率等同。未决定比例仅在来源显式提供时展示。','poll records; support is not Market probability. Undecided share is shown only when explicit in the source.')}</p></Evidence>
    </> : <Empty>{t('暂无已取得的民调。','No acquired polls.')}</Empty> : phase === 'counting' ? race ? <>
      <Scope name="US · NORTH CAROLINA" tag={race.electionDate}/><select aria-label={t('选择选举','Select contest')} value={race.id} onChange={e=>setSelected(e.currentTarget.value)}>{results.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select>
      <div className="pol-stats">{race.choices.slice(0,2).map(c=><Stat key={c.name} label={c.name} value={num(c.votes)} tone={partyTone(c.party)}/>)}</div>
      {race.choices.map(c=><Bar key={c.name} label={c.name} value={`${num(c.votes)} · ${total ? num(c.votes/total*100,2)+'%':'—'}`} percent={total ? c.votes/total*100:null} tone={partyTone(c.party)}/>)}
      <Note>{t('已发布分区统计；认证状态与剩余票数尚未核实。','Published precinct tabulation; certification and remaining votes are unverified.')}</Note><Row label={t('文件中覆盖县数','Counties in file')} value={race.counties}/>
      <Evidence><Link href="https://www.ncsbe.gov/results-data/election-results/historical-election-results-data">NCSBE</Link><p>{t('分区重分配文件不作为官方结果认证证据；不由报告比例推算剩余票，不宣布获胜者。','Precinct-sorted files are not certification evidence. No remaining-vote estimate or winner is inferred.')}</p></Evidence>
    </> : <Empty>{t('所选范围尚无票数记录。','No vote records for this scope.')}</Empty> : <Empty>{t('尚未接入当前竞选的认证、重计票与法院事件。已有票数不会自动标为认证。','Certification, recount and court events are not yet connected. Vote totals do not imply certification.')}</Empty>}
  </Shell>;
}
