import type { ComponentChildren } from 'preact';
import { Panel } from '@/components/Panel';
import { usePanelRuntimeView } from '../../PanelRuntimeView';
import { DisclosureControls, useCopy } from '../official-disclosures';
import { safeUrl, type Base } from './model';
import './styles.css';
export { useCopy } from '../official-disclosures';
export function Link({ href, children }: { href?: string | null; children: ComponentChildren }) { return safeUrl(href) ? <a href={href} target="_blank" rel="noreferrer">{children} ↗</a> : <span>{children}</span>; }
export function Shell({ id, title, data, children, explanation }: { id: string; title: string; data?: Base; children: ComponentChildren; explanation: string }) {
  const t = useCopy(), failed = data?.sources.filter(s => s.stale || s.error) || [];
  const runtime = usePanelRuntimeView();
  const body = data === undefined
    ? <p className="pol-muted" role="status">{runtime?.status?.error || runtime?.status?.phase === 'error'
      ? t('请求失败，尚未取得可展示的数据；请重试。', 'Request failed; no snapshot is available to display. Please retry.')
      : runtime?.status?.phase === 'stale'
      ? t('保存的数据已超过保留期限，等待更新。', 'The saved snapshot has expired; awaiting an update.')
      : t('正在读取已采集的数据…', 'Loading the collected data…')}</p>
    : children;
  return <Panel title={title} dataPanelId={id} controls={<DisclosureControls><p>{explanation}</p>{data?.sources.map(s => <p key={s.id}><Link href={s.url}>{s.id}</Link><br/>{t('最近取得', 'Last acquired')}: {s.lastSuccessAt || '—'}{s.error && ` · ${s.error}`}</p>)}</DisclosureControls>}>
    <div className="pol-body">{failed.length > 0 && <Note>{failed.some(s => !s.lastSuccessAt) ? t('部分来源尚无有效记录', 'Some sources have no valid observations') : t('来源更新延迟；保留已发布记录', 'Source updates delayed; published observations retained')}</Note>}{body}</div>
  </Panel>;
}
export function Tabs({ values, value, set }: { values: [string, string][]; value: string; set: (value: string) => void }) { return <div className="wm-panel-tabs pol-tabs">{values.map(([id, label]) => <button key={id} type="button" aria-pressed={value === id} onClick={() => set(id)}>{label}</button>)}</div>; }
export function Scope({ name, tag }: { name: string; tag?: string }) { return <div className="pol-scope"><strong>{name}</strong>{tag && <span className="pol-tag pol-cyan">{tag}</span>}</div>; }
export function Note({ children, tone = 'amber' }: { children: ComponentChildren; tone?: string }) { return <div className={`pol-note pol-${tone}`}>{children}</div>; }
export function Stat({ label, value, tone = 'blue' }: { label: string; value: string; tone?: string }) { return <div className="pol-stat"><strong className={`pol-${tone}`}>{value}</strong><span>{label}</span></div>; }
export function Row({ label, value, tone = 'muted' }: { label: ComponentChildren; value: ComponentChildren; tone?: string }) { return <div className="pol-row"><span>{label}</span><b className={`pol-${tone}`}>{value}</b></div>; }
export function Evidence({ children }: { children: ComponentChildren }) { const t = useCopy(); return <details className="pol-evidence"><summary>{t('原始记录与口径', 'Evidence and methodology')}</summary><div>{children}</div></details>; }
export function Bar({ label, value, percent, tone = 'blue' }: { label: string; value: string; percent: number | null; tone?: string }) { return <div className="pol-bar"><div><span>{label}</span><b className={`pol-${tone}`}>{value}</b></div>{percent !== null && Number.isFinite(percent) && <div className="pol-track"><i className={`pol-${tone}`} style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}/></div>}</div>; }
export function Empty({ children }: { children: ComponentChildren }) { return <Note>{children}</Note>; }
