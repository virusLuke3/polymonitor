import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { useI18n } from '@/services/i18n';
import { usePanelRuntimeView } from '@/panels/PanelRuntimeView';
import { usePanelResource } from '@/panels/usePanelResource';
import { bookmakerPage } from './resource';
import { MoviArchive } from './MoviArchive';
import { currentWinnerQuotes, lineKey, quoteCurrent, safeLink, teamKey, type Fixture, type Payload, type Quote } from './model';

const percent = (n: number) => `${(n * 100).toFixed(1)}%`;
const short = (s: string) => s === 'soccer' ? 'FOOTBALL' : s === 'lol' ? 'LoL' : s.toUpperCase();
const same = (a: string, b: string) => teamKey(a) === teamKey(b);

function MatchBoard({ event, game }: { event: Fixture; game: boolean }) {
  const { locale, formatRelativeTime, formatDateTime } = useI18n();
  const t = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const [market, setMarket] = useState('h2h');
  const [line, setLine] = useState('');
  const [expanded, setExpanded] = useState(false);
  const choices = event.quotes.filter(q => q.market === market && q.category === 'sportsbook');
  const lines = [...new Set(choices.map(lineKey))];
  const chosenLine = lines.includes(line) ? line : lines[0];
  const quotes = choices.filter(q => lineKey(q) === chosenLine);
  const labels = (quotes[0]?.outcomes || []).map(o => o.name).sort((a, b) =>
    Number(same(b, event.home)) - Number(same(a, event.home)) || Number(same(a, 'Draw')) - Number(same(b, 'Draw')));
  const eligible = currentWinnerQuotes(event);
  const hasDraw = eligible.some(q => q.outcomes.length === 3);
  const sides = [event.home, ...(hasDraw ? ['Draw'] : []), event.away];
  const probabilities = sides.map(side => eligible.length ? eligible.reduce((sum, q) =>
    sum + (q.outcomes.find(o => same(o.name, side))?.probability || 0), 0) / eligible.length : null);
  const alternatives = event.quotes.filter(q => q.market === market && q.category !== 'sportsbook');
  function rows(items: Quote[]) {
    return items.map((q, i) => <tr key={`${q.book}:${q.market}:${i}`} className={quoteCurrent(q) ? '' : 'wm-bookmaker-aged'}>
      <th scope="row"><span>{safeLink(q.url) ? <a href={safeLink(q.url)} target="_blank" rel="noopener noreferrer">{q.label} ↗</a> : q.label}</span>
        <small>{q.suspended ? t('Suspended', '已封盘') : q.sourceCheckedAt
          ? `${t('Confirmed', '核实于')} ${formatRelativeTime(q.sourceCheckedAt)}`
          : q.sourceUpdatedAt ? formatRelativeTime(q.sourceUpdatedAt) : t('Time unknown', '报价时间未知')}</small>
        <small>{q.provider}{q.phase && ` · ${q.phase === 'inplay' ? t('In play', '滚球') : t('Pre-match', '赛前')}`}</small></th>
      {labels.map((label, j) => { const o = q.outcomes.find(o => same(o.name, label)); return <td key={label} data-side={j === 0 ? 'a' : j === labels.length - 1 ? 'b' : 'draw'}>
        <b>{q.suspended ? '—' : o?.decimal.toFixed(2) ?? '—'}</b><small>{o && !q.suspended ? `${o.point == null ? '' : `${o.point > 0 ? '+' : ''}${o.point} · `}${percent(o.probability)}` : '—'}</small>
      </td>; })}
    </tr>);
  }
  return <>
    <div className="wm-bookmaker-event-meta"><span>{event.competition}</span><time dateTime={event.startTime}>{formatDateTime(event.startTime)}</time></div>
    {event.score && <p className="wm-bookmaker-caption">{t('Bookmaker-reported score', '博彩来源报告比分')} · <strong>{event.score}</strong>
      {event.scoreUpdatedAt && ` · ${formatRelativeTime(event.scoreUpdatedAt)}`}</p>}
    <div className={`wm-bookmaker-versus ${hasDraw ? 'three-way' : ''}`}>
      {sides.map((side, i) => <div key={side} data-side={i === 0 ? 'a' : i === sides.length - 1 ? 'b' : 'draw'}>
        <strong>{side}</strong><b>{probabilities[i] == null ? '—' : percent(probabilities[i]!)}</b>
      </div>)}
    </div>
    {eligible.length > 0 && <div className="wm-bookmaker-probability-bar" aria-label={t('Average proportional no-vig probabilities', '博彩公司平均比例去水概率')}>
      {probabilities.map((p, i) => <span key={i} data-side={i === 0 ? 'a' : i === probabilities.length - 1 ? 'b' : 'draw'} style={{ width: `${(p || 0) * 100}%` }} />)}
    </div>}
    <p className="wm-bookmaker-caption">{eligible.length ? `${eligible.length} ${t('books · proportional no-vig average', '家公司 · 比例去水均值')}` : t('No recent, timestamped winner quotes', '暂无近期且带源时间的胜负报价')}
      {event.tier !== 'public-board' && ` · ${t('Supplemental feed', '补充来源')}`}</p>
    <div className="wm-bookmaker-tabs" role="group" aria-label={t('Market type', '盘口类型')}>
      {([['h2h', t(game ? 'Series winner' : 'Winner', game ? '系列赛胜负' : '胜负')], ['spreads', t('Handicap', '让分')], ['totals', t('Totals', '大小分')]]).map(([key, label]) =>
        <button type="button" key={key} aria-pressed={market === key} onClick={() => { setMarket(key || 'h2h'); setLine(''); }}>{label}</button>)}
    </div>
    {lines.length > 1 && <label className="wm-bookmaker-line">{t('Line', '盘口线')} <select aria-label={t('Exact market line', '选择相同盘口线')} value={chosenLine} onChange={e => setLine(e.currentTarget.value)}>
      {lines.map(key => <option key={key} value={key}>{market === 'h2h' ? `${key} ${t('outcomes', '项结果')}` : key.split('|').join(' / ')}</option>)}
    </select></label>}
    {quotes.length ? <>
      <table className="wm-bookmaker-table"><thead><tr><th>{t('Bookmaker', '博彩公司')}</th>{labels.map(label => <th key={label} title={label}>{label}</th>)}</tr></thead>
        <tbody>{rows(expanded ? quotes : quotes.slice(0, 8))}</tbody></table>
      {quotes.length > 8 && <button type="button" className="wm-bookmaker-more" onClick={() => setExpanded(v => !v)}>{expanded ? t('Show fewer', '收起') : `${t('All bookmakers', '全部公司')} · ${quotes.length}`}</button>}
    </> : <p className="wm-bookmaker-empty">{t('This source has no complete quotes for this market.', '此来源暂无该盘口的完整报价。')}</p>}
    {alternatives.length > 0 && <details className="wm-bookmaker-alternatives"><summary>{t('Prediction markets & exchanges', '预测市场与交易所')} · {new Set(alternatives.map(q => q.book)).size}</summary>
      <p className="wm-bookmaker-caption">{t('Provider-linked event. Settlement rules remain unverified; excluded from bookmaker average.', '聚合来源关联的比赛，结算规则尚未核实；不计入博彩公司均值。')}</p>
      {alternatives.map((q, i) => <div className="wm-bookmaker-alternative" key={`${q.book}:${i}`}>
        <strong>{safeLink(q.url) ? <a href={safeLink(q.url)} target="_blank" rel="noopener noreferrer">{q.label} ↗</a> : q.label}</strong>
        <small>{q.category === 'prediction_market' ? t('Prediction market', '预测市场') : t('Exchange', '交易所')} · {q.sourceUpdatedAt ? formatRelativeTime(q.sourceUpdatedAt) : t('Time unknown', '时间未知')}</small>
        <span>{q.outcomes.map(o => `${o.name}${o.point != null ? ` ${o.point}` : ''} ${o.decimal.toFixed(2)}`).join(' / ')}</span>
      </div>)}
    </details>}
    <details className="wm-bookmaker-method"><summary>{t('Prices & coverage', '报价与覆盖口径')}</summary>
      <p>{t('Decimal odds; the smaller percentage below each price removes that bookmaker’s margin proportionally. Older or undated quotes are excluded from the headline. Full match/series only; bookmaker rules can differ.', '上方为十进制赔率，下方为该公司比例去水概率。旧报价和时间未知报价不计入主数字。这里只比较完整比赛或系列赛，博彩公司结算规则可能不同。')}</p>
      <p>{t('MoviOdds keeps market confirmation separate from price changes. Suspended, unconfirmed and disconnected stream quotes do not enter the average; in-play confirmations older than two minutes are excluded.', 'MoviOdds 的市场核实与变价时间分开。封盘、未核实或流已断开的报价不计入均值；滚球核实时间超过两分钟即退出当前均值。')}</p>
      <p>{[...new Set(event.quotes.map(q => q.provider))].join(' + ')} · {t('Received', '采集于')} {formatDateTime(event.fetchedAt)}</p>
    </details>
  </>;
}

function FullCatalog({ game, sport, provider, close }: { game: boolean; sport: string; provider: string; close: () => void }) {
  const { locale } = useI18n();
  const t = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const [pages, setPages] = useState([0]);
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState('');
  const [selected, setSelected] = useState('');
  const offset = pages[pages.length - 1]!;
  const resource = usePanelResource(bookmakerPage(game, { sport, provider, search, offset, limit: 20 }));
  const board = resource.data?.bookmakerBoard;
  const event = board?.fixtures.find(f => f.id === selected) || board?.fixtures[0];
  return <>
    <form className="wm-bookmaker-search" onSubmit={e => { e.preventDefault(); setSearch(draft.trim()); setPages([0]); setSelected(''); }}>
      <input aria-label={t('Search stored matches', '搜索已采集比赛')} placeholder={t('Team or competition', '队伍或赛事名称')} maxLength={100} value={draft} onInput={e => setDraft(e.currentTarget.value)} />
      <button type="submit">{t('Search', '搜索')}</button>
    </form>
    <div className="wm-bookmaker-pagination">
      <button type="button" disabled={pages.length < 2} onClick={() => { setPages(p => p.slice(0, -1)); setSelected(''); }}>{t('Previous', '上一页')}</button>
      <span>{board ? `${board.fixtures.length ? offset + 1 : 0}–${offset + board.fixtures.length} / ${board.matchedFixtures}` : t('Loading…', '加载中…')}</span>
      <button type="button" disabled={board?.nextOffset == null} onClick={() => { if (board?.nextOffset != null) { setPages(p => [...p, board.nextOffset!]); setSelected(''); } }}>{t('Next', '下一页')}</button>
    </div>
    {resource.error && <p className="wm-bookmaker-caption">{t('Could not refresh this page.', '本页刷新失败。')} <button type="button" onClick={() => void resource.refresh()}>{t('Retry', '重试')}</button></p>}
    {event ? <><label className="wm-bookmaker-event-select"><select aria-label={t('Select match', '选择比赛')} value={event.id} onChange={e => setSelected(e.currentTarget.value)}>
      {board!.fixtures.map(f => <option key={f.id} value={f.id}>{f.home} / {f.away} · {f.competition}</option>)}
    </select></label><MatchBoard key={`${event.id}:${provider}`} event={event} game={game} /></> :
      <p className="wm-bookmaker-empty">{board ? t('No retained matches for these filters.', '此筛选条件下没有保留的比赛。') : resource.error ? t('Match data could not be loaded.', '比赛数据读取失败。') : t('Loading stored matches…', '正在读取已采集比赛…')}</p>}
    <button type="button" className="wm-bookmaker-more" onClick={close}>{t('Back to overview', '返回概览')}</button>
  </>;
}

export function BookmakerPanel({ payload, game = false }: { payload?: Payload; game?: boolean }) {
  const { locale, formatDateTime, formatRelativeTime } = useI18n();
  const t = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const runtime = usePanelRuntimeView();
  const [sport, setSport] = useState(game ? 'lol' : 'nba');
  const [eventId, setEventId] = useState('');
  const [tab, setTab] = useState('odds');
  const [provider, setProvider] = useState('');
  const [browse, setBrowse] = useState(false);
  const board = payload?.bookmakerBoard;
  const fixtures = useMemo(() => (board?.fixtures || []).filter(f => f.sport === sport &&
    (!provider || f.quotes.some(q => q.provider === provider))), [board, sport, provider]);
  const providers = [...new Set([...(board?.bookmakerCoverage || []).filter(c => c.sports.includes(sport)).flatMap(c => c.providers),
    ...(board?.fixtures || []).filter(f => f.sport === sport).flatMap(f => f.quotes.map(q => q.provider))])].sort();
  const coverage = (board?.bookmakerCoverage || []).filter(c => c.sports.includes(sport));
  const event = fixtures.find(f => f.id === eventId) || fixtures[0];
  const sports = [...new Set([...(game ? ['lol', 'valorant', 'cs2', 'dota2'] : ['nba', 'soccer', 'nfl', 'nhl', 'mlb', 'tennis']),
    ...(board?.bookmakerCoverage || []).flatMap(c => c.sports), ...(board?.fixtures.map(f => f.sport) || [])])];
  const source = board?.sources.find(s => s.id === `bookmakers:board:${sport}:v1`);
  return <Panel title={game ? 'GAME' : 'SPORTS'} dataPanelId={game ? 'esports-intel' : 'sports-odds'}
    className={`wm-bookmaker-panel ${game ? 'wm-bookmaker-game' : 'wm-bookmaker-sports'}`}
    controls={<button type="button" className="wm-panel-action-button" aria-label={t('Refresh snapshot', '刷新快照')} onClick={() => runtime?.refresh?.()}>↻</button>}>
    <div className="wm-bookmaker-sports-tabs" role="group" aria-label={t('Sport or game', '体育或游戏项目')}>
      {sports.map(key => <button type="button" key={key} aria-pressed={sport === key} onClick={() => { setSport(key); setEventId(''); setProvider(''); }}>{short(key)}<small>{board?.projectCounts?.[key] ?? board?.fixtures.filter(f => f.sport === key).length ?? '·'}</small></button>)}
    </div>
    <div className="wm-bookmaker-tabs" role="group" aria-label={t('View', '视图')}>
      {[['odds', t('Odds', '赔率')], ['archive', t('History & results', '历史与赛果')], ['coverage', t('All books', '全部公司')], ['facts', t(game ? 'Official scores' : 'Standings', game ? '官方赛况' : '排名与赛程')], ...(game ? [['props', t('Player props', '选手道具')]] : [])].map(([key, label]) =>
        <button type="button" key={key} aria-pressed={tab === key} onClick={() => setTab(key || 'odds')}>{label}</button>)}
    </div>
    {tab === 'archive' && <MoviArchive key={sport} sport={sport} />}
    {tab === 'odds' && <>
      {providers.length > 1 && <label className="wm-bookmaker-event-select"><select aria-label={t('Odds provider', '赔率数据通道')} value={provider} onChange={e => { setProvider(e.currentTarget.value); setEventId(''); }}>
        <option value="">{t('All providers', '全部数据通道')}</option>{providers.map(p => <option key={p} value={p}>{p}</option>)}
      </select></label>}
      {browse ? <FullCatalog key={`${sport}:${provider}`} game={game} sport={sport} provider={provider} close={() => setBrowse(false)} /> : <>
      {board && <button type="button" className="wm-bookmaker-more" onClick={() => setBrowse(true)}>{t('Browse all stored matches', '浏览全部已采集比赛')}</button>}
      {event ? <><label className="wm-bookmaker-event-select"><select aria-label={t('Select match', '选择比赛')} value={event.id} onChange={e => setEventId(e.currentTarget.value)}>
        {fixtures.map(f => <option key={f.id} value={f.id}>{f.home} / {f.away} · {f.provider}</option>)}
      </select></label><MatchBoard key={`${event.id}:${provider}`} event={provider
        ? { ...event, quotes: event.quotes.filter(q => q.provider === provider) } : event} game={game} /></> :
        <div className="wm-bookmaker-empty"><strong>{short(sport)}</strong><p>{!payload ? runtime?.status?.error
          ? t('The saved data could not be loaded. Retry the connection.', '已采集数据读取失败，请重试连接。') : t('Loading saved source data…', '正在读取已采集的数据…') : source?.usable ?
          t('No fixtures in the public board’s current window.', '公开看板当前时间窗内没有比赛记录。') : t('Source data is temporarily unavailable.', '来源数据暂时不可用。')}</p>
          {source?.usable && <small>{t('Window: 4 hours after start to 36 hours before start.', '窗口：开赛后 4 小时至开赛前 36 小时。')}</small>}</div>}
      </>}
    </>}
    {tab === 'coverage' && <div className="wm-bookmaker-facts">
      <p className="wm-bookmaker-caption">{short(sport)} · {coverage.filter(c => c.category === 'sportsbook').length} {t('bookmakers in retained source data', '家博彩公司有保留报价')}</p>
      <p className="wm-bookmaker-caption">{t('Counts cover stored feeds, including aged quotes. They are not a count of current executable offers.', '计数来自完整存储，包含保留的旧报价；不代表当前可成交报价数量。')}</p>
      {coverage.map(c => <div className="wm-bookmaker-fact-row" key={c.book}><span><strong>{c.label}</strong><small>{c.providers.join(' · ')}</small>
        {c.category !== 'sportsbook' && <small>{c.category === 'exchange' ? t('Exchange', '交易所') : t('Prediction market', '预测市场')}</small>}</span>
        <b>{c.fixturesBySport?.[sport] ?? c.fixtures} <small>{t('matches', '场')}</small></b></div>)}
      {!coverage.length && <p className="wm-bookmaker-empty">{t('No acquired bookmaker quotes for this project.', '此项目目前没有已采集的博彩公司报价。')}</p>}
    </div>}
    {tab === 'facts' && <div className="wm-bookmaker-facts">
      {game && <><p className="wm-bookmaker-caption">{t('GRID · official series state; CS2 / Dota coverage depends on access.', 'GRID 官方系列赛赛况；CS2 / Dota 覆盖取决于账号权限。')}</p>
        {(payload?.items || []).filter(i => sport === 'cs2' ? /counter|cs2/i.test(i.gameTitle || '') : sport === 'dota2' ? /dota/i.test(i.gameTitle || '') : sport === 'lol' ? /league/i.test(i.gameTitle || '') : /valorant/i.test(i.gameTitle || '')).map(i =>
          <article key={i.id}><div><small>{i.gameTitle} · {i.state}</small><b>{i.score || '—'}</b></div><strong>{i.teamA || '—'} <em>vs</em> {i.teamB || '—'}</strong>
            <p>{i.currentMap || i.tournament || '—'}</p><small>{payload?.officialGeneratedAt ? formatRelativeTime(payload.officialGeneratedAt) : t('Time unknown', '时间未知')}</small></article>)}
        {(sport === 'lol' || sport === 'valorant') && <p className="wm-bookmaker-empty">{t('This GRID account has no verified state feed for this game. Bookmaker odds are available independently.', '当前 GRID 账号尚未取得此游戏的赛况权限；博彩公司赔率是独立数据链路。')}</p>}
      </>}
      {(payload?.sportsContext || []).filter(c => game ? sport === 'dota2' : sport === 'nba' ? c.source.id.includes('standings') : sport === 'tennis' && c.source.id.includes('tournament')).map(c =>
        <section key={c.source.id}><p className="wm-bookmaker-caption">{c.source.label} · {c.source.lastSuccessAt ? formatRelativeTime(c.source.lastSuccessAt) : '—'}</p>
          {c.rows.length ? c.rows.map((r, i) => <div className="wm-bookmaker-fact-row" key={i}><span><strong>{r.title}</strong><small>{r.detail}</small></span><b>{r.value}</b></div>) :
            <p className="wm-bookmaker-empty">{t('No retained records from this source.', '此来源暂无保留的有效记录。')}</p>}</section>)}
      {!game && !['nba', 'tennis'].includes(sport) && <p className="wm-bookmaker-empty">{t('Official standings are not connected for this sport; use Bookmakers for available prices.', '此项目尚未接入官方排名；已有赔率请查看博彩公司页。')}</p>}
    </div>}
    {tab === 'props' && <div className="wm-bookmaker-props"><p className="wm-bookmaker-caption">{t('KashRock · public demo sample, not a live prop feed', 'KashRock 公开演示样本，并非实时道具流')}</p>
      {(board?.props || []).filter(p => p.sport === sport).map(p => <article key={p.id}><small>{p.book} · {p.stat}</small><h4>{p.player}</h4>
        <div><strong>{p.direction.toUpperCase()} {p.line}</strong><b>{p.decimal.toFixed(2)}</b></div>
        <p>{t('Quote time unknown · opposite side unavailable', '报价时间未知 · 缺少另一侧赔率')}</p>
        {p.startTime && <small>{formatDateTime(p.startTime)}</small>}</article>)}
      {!(board?.props || []).some(p => p.sport === sport) && <p className="wm-bookmaker-empty">{t('No public player-prop sample for this game.', '当前游戏没有公开道具样本。')}</p>}
    </div>}
    {board && <details className="wm-bookmaker-sources"><summary>{t('Sources & coverage', '来源与覆盖')} · {board.availableFixtures} {t('fixtures', '场比赛')}</summary>
      {board.sources.map(s => <div key={s.id}><strong>{s.label}</strong><span>{s.usable ? s.stale || s.error ? t('Saved data', '保留数据') : t('Acquired', '已采集') : t('Unavailable', '暂不可用')}</span><small>{s.lastSuccessAt ? formatDateTime(s.lastSuccessAt) : '—'}
        {s.fixtureCount !== undefined && ` · ${s.fixtureCount} ${t('matches', '场')} · ${s.quoteCount || 0} ${t('markets', '盘口')}`}</small></div>)}
      {board.omittedFixtures > 0 && <p>{board.omittedFixtures} {t('fixtures omitted by response size limit.', '场比赛未包含在本次有界响应中。')}</p>}
    </details>}
  </Panel>;
}
