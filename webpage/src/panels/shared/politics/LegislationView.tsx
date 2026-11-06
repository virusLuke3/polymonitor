import { useState } from 'preact/hooks';
import type { Legislation } from './model';
import { Empty, Evidence, Link, Note, Row, useCopy } from './ui';
export function LegislationView({ data }: { data?: Legislation }) {
  const t = useCopy(), [selected, set] = useState(''), rows = data?.items || [], bill = rows.find(r => r.id === selected) || rows[0];
  if (!bill) return <Empty>{t('正在等待所跟踪法案的官方行动记录。', 'Awaiting official actions for tracked bills.')}</Empty>;
  return <><select aria-label={t('选择法案', 'Select bill')} value={bill.id} onChange={e => set(e.currentTarget.value)}>{rows.map(r => <option key={r.id} value={r.id}>{r.id} · {r.title}</option>)}</select>
    <Note tone="cyan"><strong>{bill.id.toUpperCase()}</strong><span>{bill.title}</span></Note>
    <Row label={t('最近行动', 'Latest action')} value={bill.latestAction.date}/><p>{bill.latestAction.text}</p>
    <ol className="pol-timeline">{bill.actions.slice(0, 8).map((a, i) => <li key={i} data-state="done"><span>{a.date}</span><div><b>{a.text}</b>{a.votes.map(v => <p key={v}><Link href={v}>{t('逐名表决', 'Roll call')}</Link></p>)}</div><i/></li>)}</ol>
    <Evidence><Row label={t('共同提案人（不是赞成票）', 'Cosponsors (not votes)')} value={bill.cosponsors}/><p>{bill.committees.join(' · ')}</p>{bill.textVersions.map((v, i) => <p key={i}>{v.date} · {v.name} {v.urls.map(u => <Link key={u} href={u}>{t('文本版本', 'Text version')}</Link>)}</p>)}<p><Link href={bill.url}>{t('完整法案记录', 'Full bill record')}</Link></p><p>{t('覆盖近期发布及明确观察清单；不代表全部国会法案。', 'Covers recent publications and the watchlist, not all legislation.')}</p><p>{data?.acquiredCount} / {data?.targetCount} {t('已尝试读取的观察对象', 'watch targets attempted')}</p></Evidence>
  </>;
}
