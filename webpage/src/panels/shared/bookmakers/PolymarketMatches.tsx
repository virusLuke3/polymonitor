import { useI18n } from '@/services/i18n';
import { catalogCurrent, matchCurrent } from './matching';
import { safeLink, type Fixture, type Quote } from './model';

export function PolymarketMatches({ event, market, selectedQuote }: { event: Fixture; market: string; selectedQuote?: Quote }) {
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
  const ruleLabels: Record<string, string> = {
    overtime: t('Overtime', '加时赛'), postponement_or_no_result: t('Postponed / no result', '延期／无结果'),
    equal_to_line: t('Exactly on the line', '恰好等于盘口线'), did_not_play: t('Did not play', '未出场'),
    refund_except_playoffs_48h: t('Refund, except playoff window', '退款，季后赛有宽限期'),
    refund_except_listed_24h: t('Refund, except listed 24h window', '退款，指定赛事有24小时宽限期'),
    stake_refund: t('Stake refunded', '退还本金'), split: t('50¢ redemption', '每份兑付50¢'),
    predicate: t('Contract no-result clause', '按合约无结果条款'), no: t('No wins', 'No胜出'),
    yes: t('Yes wins', 'Yes胜出'), under: t('Under wins', '小于等于方胜出'), unknown: t('Unverified', '待核实'),
    included: t('Included', '计入'), regulation: t('Regulation only', '仅常规时间'),
  };
  const ruleLabel = (value: string) => ruleLabels[value] || value;
  const markets = m.markets.filter(x => x.type === market && (market !== 'player_totals' || !selectedQuote || x.player === selectedQuote.player && x.metric === selectedQuote.metric && Number(x.line) === selectedQuote.outcomes[0]?.point));
  const verified = m.verifiedAt ?? m.checkedAt;
  return <details className="wm-bookmaker-alternatives" open={m.state === 'linked'}>
    <summary>Polymarket · {labels[m.state]}{m.state === 'linked' && !matchCurrent(m) ? ` · ${t('Recheck due', '待重新核实')}` : ''}</summary>
    {!!verified && <p className="wm-bookmaker-caption">{t('Last successful check', '最近成功检查')} {formatRelativeTime(new Date(verified * 1000).toISOString())}</p>}
    {m.state === 'linked' || m.state === 'unavailable' && m.markets.length > 0 ? <>
      {m.state === 'unavailable' && <p className="wm-bookmaker-caption">{t('Recheck failed. Keeping the previous link while the worker retries.', '重新检查失败，保留此前的关联；后台正在重试。')}</p>}
      <p className="wm-bookmaker-caption">{t('Event, selection and line are checked separately from settlement. Prices below are saved references, not executable offers.', '赛事、选项和盘口线分别核对；结算差异在各盘口中列出。下方为已存参考价，不是可成交报价。')}</p>
      {markets.map(p => <div className="wm-bookmaker-alternative" key={p.conditionId}>
        <strong>{safeLink(p.url) ? <a href={safeLink(p.url)} target="_blank" rel="noopener noreferrer">{p.title} ↗</a> : p.title}</strong>
        <span>{p.outcomes.map(o => `${o.label} ${o.catalogPrice == null ? '—' : `${(o.catalogPrice * 100).toFixed(1)}¢`}`).join(' / ')}</span>
        <small>{p.books.length ? `${new Set(p.books.map(b => b.book)).size} ${t('books with matching selections and line', '家公司有相同选项及盘口线')}` : t('No verified matching bookmaker line', '尚无核实一致的博彩公司盘口线')}</small>
        {p.books.filter(b => b.ruleCheck?.scenarios.length).map(b => <small key={`${b.book}:${b.provider}`}>
          {b.book} · {t('Settlement differences', '结算差异')}: {b.ruleCheck!.scenarios.map(s => `${ruleLabel(s.case)}: ${ruleLabel(s.bookmaker)} / PM ${ruleLabel(s.polymarket)}`).join('; ')}
        </small>)}
        {p.books.length > 0 && <small>{p.settlement === 'conflict' ? t('Rule conflict — no arbitrage signal', '规则存在差异，不输出套利信号') : t('Remaining rule evidence required', '仍需补充规则证据')}</small>}
        <small>{t('PM catalog' , 'PM 目录')} · {p.observedAt ? formatRelativeTime(p.observedAt) : t('Time unknown', '时间未知')}{!catalogCurrent(p) ? ` · ${t('Saved reference', '历史参考值')}` : ''}</small>
      </div>)}
      {!markets.length && <p className="wm-bookmaker-caption">{t('No supported Polymarket selection for this market type.', '此盘口类型尚无支持的 Polymarket 选项映射。')}</p>}
    </> : <p className="wm-bookmaker-caption">{reasons[m.reason] || (m.state === 'unavailable'
      ? t('The background worker will retry. This is not proof that no market exists.', '后台会自动重试；读取失败不代表没有对应市场。')
      : t('Only evidence-backed matches are linked automatically.', '只有证据充分的匹配才会自动关联。'))}</p>}
    {m.state !== 'linked' && m.candidates?.map(c => <div className="wm-bookmaker-alternative" key={c.eventId}><strong>{c.title}</strong><small>{reasons[c.reason] || c.reason}</small></div>)}
  </details>;
}
