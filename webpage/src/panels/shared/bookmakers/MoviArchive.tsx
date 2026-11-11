import { useState } from 'preact/hooks';
import { usePanelResource } from '@/panels/usePanelResource';
import { useI18n } from '@/services/i18n';
import { archiveResource, type PricePoint } from './archive';

function Curve({ points }: { points: PricePoint[] }) {
  const valid = points.filter(p => !p.suspended && p.odds_dec != null);
  if (valid.length < 2) return null;
  const min = Math.min(...valid.map(p => p.odds_dec!)), max = Math.max(...valid.map(p => p.odds_dec!));
  const start = Date.parse(valid[0]!.ts), end = Date.parse(valid[valid.length - 1]!.ts);
  let move = true;
  const path = points.map(p => {
    if (p.suspended || p.odds_dec == null) { move = true; return ''; }
    const command = move ? 'M' : 'L'; move = false;
    return `${command}${4 + 312 * (Date.parse(p.ts) - start) / Math.max(1, end - start)},${76 - 68 * (p.odds_dec - min) / Math.max(.01, max - min)}`;
  }).join(' ');
  return <svg className="wm-movi-history-curve" viewBox="0 0 320 84" role="img" aria-label="Recorded decimal odds"><path d={path} fill="none" stroke="currentColor" strokeWidth="2" /></svg>;
}

function Detail({ fixture, sport }: { fixture: string; sport: string }) {
  const { locale, formatDateTime } = useI18n();
  const t = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const [selection, setSelection] = useState('');
  const [offset, setOffset] = useState(0);
  const [tab, setTab] = useState('history');
  const r = usePanelResource(archiveResource({ sport, fixture, selection, offset, limit: 100 }));
  const d = r.data, historyTask = d?.tasks?.find(task => task.kind === 'history');
  return <>
    <div className="wm-bookmaker-tabs" role="group" aria-label={t('Archived data', '档案类型')}>
      {[['history', t('History', '历史赔率')], ['closing', t('Closing', '收盘价')], ['result', t('Result', '赛果')]].map(([key, title]) => <button type="button" key={key} aria-pressed={tab === key} onClick={() => setTab(key!)}>{title}</button>)}
    </div>
    {r.error && <p className="wm-bookmaker-caption">{t('Archive read failed; saved records retain their original times.', '档案读取失败；保留记录仍使用原始时间。')}</p>}
    {!d ? <p className="wm-bookmaker-empty">{t('Loading stored archive…', '正在读取已存档案…')}</p> : tab === 'history' ? <>
      <select className="wm-movi-selection" aria-label={t('Historical selection', '历史报价选项')} value={selection} onChange={e => { setSelection(e.currentTarget.value); setOffset(0); }}>
        <option value="">{t('All recorded selections', '全部已记录选项')}</option>{d.selections?.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
      </select>
      <p className="wm-bookmaker-caption">{historyTask?.error ? t('History backfill failed; recorded points remain.', '历史补录失败；已记录点位仍保留。') : historyTask?.cursor.complete
        ? t('Primary-market history window acquired', '主盘口历史窗口已取得') : t('Primary-market history backfill pending / incomplete', '主盘口历史补录等待中／尚未完整')}
        {' · '}{d.total} {t('stored points', '个已存点位')}</p>
      {selection && <Curve points={d.points || []} />}
      <table className="wm-bookmaker-table"><thead><tr><th>{t('Source time / selection', '源时间／选项')}</th><th>{t('Decimal', '十进制赔率')}</th></tr></thead><tbody>
        {d.points?.map((p, i) => <tr key={`${p.ts}:${i}`}><th><span>{p.side || p.label || p.sel_id}{p.handicap ? ` ${p.handicap}` : ''}</span><small>{formatDateTime(p.ts)}</small><small>{p.channel === 'ws' ? t('Stream observation', '流式观测') : t('Retrospective archive', '事后补录')} · {t('Received', '取得于')} {formatDateTime(p.firstReceivedAt)}</small></th><td>{p.suspended ? t('Suspended', '封盘') : p.odds_dec?.toFixed(3)}</td></tr>)}
      </tbody></table>
      {!d.points?.length && <p className="wm-bookmaker-empty">{t('No acquired points for this selection yet.', '此选项尚无已取得点位。')}</p>}
      <div className="wm-bookmaker-pagination"><button type="button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>{t('Newer', '较新')}</button><span>{offset + (d.points?.length ? 1 : 0)}–{offset + (d.points?.length || 0)} / {d.total}</span><button type="button" disabled={d.nextOffset == null} onClick={() => setOffset(d.nextOffset!)}>{t('Older', '更早')}</button></div>
    </> : tab === 'closing' ? d.closing ? <>
      <p className="wm-bookmaker-caption">{d.closing.data.closed ? t('Closed · pre-match close and final recorded price', '已收盘 · 赛前收盘与最后记录价') : t('Provisional · match has not closed', '暂定价格 · 尚未收盘')} · {d.closing.data.pre_close_basis}</p>
      <table className="wm-bookmaker-table"><thead><tr><th>{t('Selection', '选项')}</th><th>{t('Pre-close', '赛前收盘')}</th><th>{t('Last', '最后记录')}</th></tr></thead><tbody>{d.closing.data.selections.map((s, i) => <tr key={`${s.sel_id}:${i}`}><th><span>{s.side || s.label || s.sel_id} {s.handicap}</span><small>{s.group_name} · {s.line}</small></th><td>{s.pre_close?.suspended ? t('Suspended', '封盘') : s.pre_close?.odds_dec?.toFixed(3) ?? '—'}{s.pre_close && <small>{formatDateTime(s.pre_close.ts)}</small>}</td><td>{s.last?.suspended ? t('Suspended', '封盘') : s.last?.odds_dec?.toFixed(3) ?? '—'}{s.last && <small>{formatDateTime(s.last.ts)}</small>}</td></tr>)}</tbody></table>
      {d.closing.omittedSelections > 0 && <p className="wm-bookmaker-caption">{d.closing.omittedSelections} {t('additional selections stored; first 200 shown.', '个额外选项已存储；本页显示前 200 项。')}</p>}
    </> : <p className="wm-bookmaker-empty">{t('Closing data has not been acquired for this match.', '此场比赛尚未取得收盘档案。')}</p> : d.result ? <>
      <div className="wm-movi-result"><strong>{d.result.data.final_score || '—'}</strong><span>{d.result.data.status === 'finished' ? t('Reported finished', '来源报告已结束') : t('Finish unconfirmed', '结束状态未确认')}</span></div>
      <p className="wm-bookmaker-caption">{formatDateTime(d.result.data.finished_at)} · MoviOdds / bet365</p>
      {d.result.data.periods?.map((p, i) => <div className="wm-bookmaker-fact-row" key={i}><span>{p.name}</span><b>{p.score}</b></div>)}
      {d.result.data.note && <p className="wm-bookmaker-caption">{d.result.data.note}</p>}
      {d.result.data.archiveSource === 'memory' && <p className="wm-bookmaker-caption">{t('Upstream returned its recent-memory archive; older coverage is limited.', '上游返回近期内存档案，较早赛果覆盖受限。')}</p>}
      <p className="wm-bookmaker-caption">{t('Provider result; not a Polymarket settlement decision.', '来源赛果，不等于 Polymarket 结算决定。')}</p>
    </> : <p className="wm-bookmaker-empty">{t('No acquired result; the match may not have finished.', '尚无已取得赛果；比赛可能尚未结束。')}</p>}
  </>;
}

export function MoviArchive({ sport }: { sport: string }) {
  const { locale } = useI18n();
  const t = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const [offset, setOffset] = useState(0), [chosen, setChosen] = useState('');
  const r = usePanelResource(archiveResource({ sport, fixture: '', selection: '', offset, limit: 50 }));
  const d = r.data, selected = d?.items?.find(i => i.id === chosen) || d?.items?.[0];
  return <>
    <p className="wm-bookmaker-caption">{t('bet365 · MoviOdds history, closing lines & results', 'bet365 · MoviOdds 历史赔率、收盘与赛果')}</p>
    {r.error && <p className="wm-bookmaker-caption">{t('Archive unavailable.', '档案暂不可用。')} <button type="button" onClick={() => void r.refresh()}>{t('Retry', '重试')}</button></p>}
    <div className="wm-bookmaker-pagination"><button type="button" disabled={!offset} onClick={() => { setOffset(Math.max(0, offset - 50)); setChosen(''); }}>{t('Previous', '上一页')}</button><span>{d ? `${offset + (d.items?.length ? 1 : 0)}–${offset + (d.items?.length || 0)} / ${d.total}` : '…'}</span><button type="button" disabled={d?.nextOffset == null} onClick={() => { setOffset(d!.nextOffset!); setChosen(''); }}>{t('Next', '下一页')}</button></div>
    {selected ? <><label className="wm-bookmaker-event-select"><select aria-label={t('Archived match', '已存档比赛')} value={selected.id} onChange={e => setChosen(e.currentTarget.value)}>{d?.items?.map(i => <option key={i.id} value={i.id}>{i.home} / {i.away} · {i.league}</option>)}</select></label><Detail key={selected.id} fixture={selected.id} sport={sport} /></> : <p className="wm-bookmaker-empty">{d ? t('No acquired archive entries for this sport yet.', '此项目尚无已取得的档案记录。') : t('Loading archive…', '正在读取档案…')}</p>}
  </>;
}
