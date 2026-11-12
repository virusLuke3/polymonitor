import { useI18n } from '@/services/i18n';
import { catalogCurrent, matchCurrent } from './matching';
import { safeLink, type Fixture } from './model';

export function PolymarketMatches({ event, market }: { event: Fixture; market: string }) {
  const { locale, formatRelativeTime } = useI18n();
  const t = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const m = event.polymarketMatch;
  if (!m) return null;
  const labels = { linked: t('Event linked', '赛事已关联'), pending: t('Awaiting check', '等待检查'),
    review: t('Needs review', '需要复核'), unmatched: t('No confirmed match', '尚无确认匹配'),
    incomplete: t('Search incomplete', '查询范围未完整'), unavailable: t('Catalog unavailable', '目录暂不可用'),
    unsupported: t('Sport not yet supported', '此项目尚未支持匹配') };
  const reasons: Record<string, string> = {
    team_alias_unverified: t('Team aliases need evidence.', '队伍别名尚待证据确认。'),
    kickoff_conflict: t('Scheduled start times disagree.', '双方记录的开赛时间不一致。'),
    competition_unverified: t('Competition identity needs evidence.', '赛事身份尚待核实。'),
    ambiguous_event: t('More than one event fits; no automatic selection.', '多个赛事符合条件，尚未自动选定。'),
    no_candidate_in_catalog: t('No candidate found in the stored catalog for this team block.', '在已存目录的队伍查询范围内未找到候选。'),
    candidate_search_truncated: t('Candidate query reached its bound.', '候选查询达到上限，不能确认唯一性。'),
  };
  const markets = m.markets.filter(x => x.type === market);
  return <details className="wm-bookmaker-alternatives" open={m.state === 'linked'}>
    <summary>Polymarket · {labels[m.state]}{m.state === 'linked' && !matchCurrent(m) ? ` · ${t('Recheck due', '待重新核实')}` : ''}</summary>
    {m.checkedAt && <p className="wm-bookmaker-caption">{t('Identity checked', '身份核实于')} {formatRelativeTime(new Date(m.checkedAt * 1000).toISOString())}</p>}
    {m.state === 'linked' ? <>
      <p className="wm-bookmaker-caption">{t('Same event. Settlement rules are not yet verified; catalog prices are reference values, not executable spreads.', '已关联同一赛事。结算规则尚未核实；目录价格仅供参考，不计算可执行价差。')}</p>
      {markets.map(p => <div className="wm-bookmaker-alternative" key={p.conditionId}>
        <strong>{safeLink(p.url) ? <a href={safeLink(p.url)} target="_blank" rel="noopener noreferrer">{p.title} ↗</a> : p.title}</strong>
        <span>{p.outcomes.map(o => `${o.label} ${o.catalogPrice == null ? '—' : `${(o.catalogPrice * 100).toFixed(1)}¢`}`).join(' / ')}</span>
        <small>{p.books.length ? `${new Set(p.books.map(b => b.book)).size} ${t('books with matching selections and line', '家公司有相同选项及盘口线')}` : t('No verified matching bookmaker line', '尚无核实一致的博彩公司盘口线')}</small>
        <small>{t('PM catalog', 'PM 目录')} · {p.observedAt ? formatRelativeTime(p.observedAt) : t('Time unknown', '时间未知')}{!catalogCurrent(p) ? ` · ${t('Saved reference', '历史参考值')}` : ''}</small>
      </div>)}
      {!markets.length && <p className="wm-bookmaker-caption">{t('No supported Polymarket selection for this market type.', '此盘口类型尚无支持的 Polymarket 选项映射。')}</p>}
    </> : <p className="wm-bookmaker-caption">{reasons[m.reason] || (m.state === 'unavailable'
      ? t('The background worker will retry. This is not proof that no market exists.', '后台会自动重试；读取失败不代表没有对应市场。')
      : t('Only evidence-backed matches are linked automatically.', '只有证据充分的匹配才会自动关联。'))}</p>}
    {m.state !== 'linked' && m.candidates?.map(c => <div className="wm-bookmaker-alternative" key={c.eventId}><strong>{c.title}</strong><small>{reasons[c.reason] || c.reason}</small></div>)}
  </details>;
}
