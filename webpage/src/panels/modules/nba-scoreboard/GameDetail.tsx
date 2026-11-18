import { useState } from 'preact/hooks';
import { usePanelResource } from '@/panels/usePanelResource';
import { fetchNbaGameDetail } from '@/services/api';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import type { RuntimeNbaGame } from '@/types';

type SourceObject = Record<string, unknown>;
type Translate = (zh: string, en: string) => string;
const asObject = (value: unknown): SourceObject =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as SourceObject : {};
const rows = (value: unknown): SourceObject[] => Array.isArray(value) ? value.map(asObject) : [];
const cells = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const label = (value: unknown): string =>
  typeof value === 'string' || typeof value === 'number' ? String(value) : '—';
const hasData = (value: unknown) => value != null && (typeof value !== 'object' || Object.keys(value).length > 0);
const tabs = ['overview', 'boxscore', 'plays', 'context', 'source'] as const;
type Tab = typeof tabs[number];

function parseDetail(value: unknown, gameId: string) {
  const data = asObject(value);
  const scoreboard = asObject(data.scoreboard);
  const summary = asObject(data.summary);
  if (data.eventId !== gameId || data.source !== 'ESPN' || data.status === 'unavailable'
    || (data.scoreboard != null && scoreboard.id !== gameId)
    || (data.summary != null && asObject(summary.header).id !== gameId)) {
    throw new Error('ESPN game detail unavailable');
  }
  return { scoreboard, summary, status: data.status, summaryFetchedAt: label(data.summaryFetchedAt),
    scoreboardFetchedAt: label(data.scoreboardFetchedAt) };
}

function SourceSections({ sections, t, includeEmpty = false }: { sections: Array<[string, unknown]>; t: Translate; includeEmpty?: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const visible = includeEmpty ? sections : sections.filter(([, value]) => hasData(value));
  if (!visible.length) return <p>{t('ESPN 暂无此类数据。', 'ESPN has not supplied data here.')}</p>;
  return <div className="wm-nba-sections">{visible.map(([name, value]) =>
    <div key={name}>
      <button type="button" aria-expanded={open === name} onClick={() => setOpen(open === name ? null : name)}>
        {name}{Array.isArray(value) ? ` · ${value.length}` : ''}
      </button>
      {open === name && <pre tabIndex={0} aria-label={t('ESPN 数据', 'ESPN data')}>{JSON.stringify(value, null, 2)}</pre>}
    </div>
  )}</div>;
}

function Context({ summary, sections, t }: { summary: SourceObject; sections: Array<[string, unknown]>; t: Translate }) {
  const injuries = rows(summary.injuries).flatMap(team =>
    rows(team.injuries).map(row => ({
      team: asObject(team.team).displayName, player: asObject(row.athlete), row, detail: asObject(row.details),
    })),
  );
  const lines = rows(summary.pickcenter);
  return <div className="wm-nba-stat-block">
    {injuries.length > 0 && <div className="wm-nba-table-wrap"><table>
      <caption>{t('伤停记录', 'Injury reports')}</caption>
      <thead><tr><th>{t('球员', 'Player')}</th><th>{t('球队', 'Team')}</th><th>{t('状态', 'Status')}</th>
        <th>{t('伤情', 'Injury')}</th><th>{t('来源日期', 'Source date')}</th></tr></thead>
      <tbody>{injuries.map(({ team, player, row, detail }, index) => <tr key={`${label(player.id)}:${index}`}>
        <th scope="row">{label(player.displayName)}</th><td>{label(team)}</td><td>{label(row.status)}</td>
        <td>{label(detail.type ?? detail.detail ?? detail.side)}</td><td>{label(row.date)}</td>
      </tr>)}</tbody>
    </table></div>}
    {lines.length > 0 && <div className="wm-nba-table-wrap"><table>
      <caption>{t('ESPN 所附参考盘口', 'ESPN sportsbook reference lines')}</caption>
      <thead><tr><th>{t('来源', 'Provider')}</th><th>{t('让分', 'Spread')}</th><th>{t('大小分', 'Total')}</th>
        <th>{t('来源更新时间', 'Source updated')}</th></tr></thead>
      <tbody>{lines.map((row, index) => <tr key={index}>
        <th scope="row">{label(asObject(row.provider).name)}</th><td>{label(row.details ?? row.spread)}</td>
        <td>{label(row.overUnder)}</td><td>{label(row.lastModified ?? row.lastUpdated)}</td>
      </tr>)}</tbody>
    </table></div>}
    <SourceSections sections={sections} t={t} />
  </div>;
}

function Overview({ game, scoreboard, summary, t }: { game: RuntimeNbaGame; scoreboard: SourceObject; summary: SourceObject; t: Translate }) {
  const info = asObject(summary.gameInfo);
  const competition = rows(scoreboard.competitions)[0] || {};
  const venue = asObject(info.venue || competition.venue);
  const lastPlay = asObject(asObject(competition.situation).lastPlay);
  const periods = [...new Set([...(game.awayPeriods ?? []), ...(game.homePeriods ?? [])].map(row => row.period))].sort((a, b) => a - b);
  const categories: Record<string, string> = {
    points: t('得分', 'PTS'), rebounds: t('篮板', 'REB'), assists: t('助攻', 'AST'),
    rating: t('ESPN 评分', 'ESPN rating'), pointsPerGame: t('场均得分', 'PPG'),
    reboundsPerGame: t('场均篮板', 'RPG'), assistsPerGame: t('场均助攻', 'APG'),
  };
  return <div className="wm-nba-stat-block">
    {venue.fullName != null && <p>{t('场馆', 'Venue')} · {label(venue.fullName)}</p>}
    {game.broadcast && <p>{t('转播', 'Broadcast')} · {game.broadcast}</p>}
    {rows(info.officials).length > 0 && <p>{t('裁判', 'Officials')} · {rows(info.officials).map(row => label(row.displayName ?? row.fullName)).join(' / ')}</p>}
    {lastPlay.text != null && <p>{t('最近回合', 'Last play')} · {label(lastPlay.text)}</p>}
    {periods.length > 0 && <div className="wm-nba-table-wrap"><table>
      <thead><tr><th>{t('球队', 'Team')}</th>{periods.map(period => <th key={period}>{period <= 4 ? `Q${period}` : `OT${period - 4}`}</th>)}<th>{t('总分', 'Total')}</th></tr></thead>
      <tbody>{[
        { name: game.awayTeam, score: game.awayScore, periods: game.awayPeriods },
        { name: game.homeTeam, score: game.homeScore, periods: game.homePeriods },
      ].map(row => <tr key={row.name}><th scope="row">{row.name}</th>
        {periods.map(period => <td key={period}>{label(row.periods?.find(value => value.period === period)?.value)}</td>)}<td>{label(row.score)}</td>
      </tr>)}</tbody>
    </table></div>}
    {(game.leaders?.length ?? 0) > 0 && <div className="wm-nba-table-wrap"><table>
      <thead><tr><th>{t('领跑球员', 'Leaders')}</th><th>{t('球队', 'Team')}</th><th>{t('项目', 'Stat')}</th><th>{t('数值', 'Value')}</th></tr></thead>
      <tbody>{game.leaders?.map((row, index) => <tr key={`${row.side}:${row.category}:${row.athleteId ?? index}`}>
        <th scope="row">{row.name}</th><td>{row.side === 'away' ? game.awayTeam : game.homeTeam}</td>
        <td>{categories[row.category] ?? row.category}</td><td>{row.value == null ? '—' : Number(row.value.toFixed(2))}</td>
      </tr>)}</tbody>
    </table></div>}
  </div>;
}

function BoxScore({ summary, t }: { summary: SourceObject; t: Translate }) {
  const box = asObject(summary.boxscore);
  const teams = rows(box.teams);
  const players = rows(box.players);
  if (!teams.length && !players.length) return <p>{t('ESPN 暂无技术统计。', 'ESPN has not supplied box scores.')}</p>;
  return <div className="wm-nba-stat-block">
    {teams.map(team => <div key={label(asObject(team.team).id)} className="wm-nba-table-wrap">
      <table><caption>{label(asObject(team.team).displayName ?? asObject(team.team).abbreviation)} · {t('球队统计', 'Team stats')}</caption>
        <tbody>{rows(team.statistics).map(stat => <tr key={label(stat.name)}>
          <th scope="row" title={label(stat.name)}>{label(stat.label ?? stat.name)}</th><td>{label(stat.displayValue ?? stat.value)}</td>
        </tr>)}</tbody>
      </table>
    </div>)}
    {players.map(team => rows(team.statistics).map((group, index) => {
      const columns = cells(group.labels ?? group.names);
      return <div key={`${label(asObject(team.team).id)}:${index}`} className="wm-nba-table-wrap">
        <table><caption>{label(asObject(team.team).displayName ?? asObject(team.team).abbreviation)} · {t('球员统计', 'Player stats')}</caption>
          <thead><tr><th>{t('球员', 'Player')}</th><th>{t('出场', 'Role')}</th>{columns.map((col, i) => <th key={i}>{label(col)}</th>)}</tr></thead>
          <tbody>{rows(group.athletes).map((row, i) => {
            const athlete = asObject(row.athlete);
            const values = cells(row.stats);
            const role = row.didNotPlay ? t('未上场', 'DNP') : row.starter ? t('首发', 'Starter') : t('替补', 'Bench');
            return <tr key={label(athlete.id ?? i)}>
              <th scope="row">{label(athlete.displayName ?? athlete.shortName)}</th>
              <td>{role}{row.ejected ? ` · ${t('驱逐', 'Ejected')}` : ''}{row.reason ? ` · ${label(row.reason)}` : ''}</td>
              {columns.map((_, j) => <td key={j}>{label(values[j])}</td>)}
            </tr>;
          })}</tbody>
        </table>
      </div>;
    }))}
  </div>;
}

function Plays({ summary, t, formatDateTime }: { summary: SourceObject; t: Translate; formatDateTime: (value: string) => string }) {
  const [older, setOlder] = useState(false);
  const [limit, setLimit] = useState(40);
  const plays = rows(summary.plays);
  const probabilities = new Map(rows(summary.winprobability).map(row => [label(row.playId), row.homeWinPercentage]));
  if (!plays.length) return <p>{t('ESPN 暂无逐回合记录。', 'ESPN has not supplied play-by-play.')}</p>;
  const ordered = older ? plays : plays.slice().reverse();
  return <div className="wm-nba-stat-block">
    <button type="button" onClick={() => { setOlder(!older); setLimit(40); }}>
      {older ? t('最早在前', 'Oldest first') : t('最新在前', 'Newest first')} · {plays.length}
    </button>
    <div className="wm-nba-table-wrap"><table>
      <thead><tr><th>{t('节次 / 时间', 'Period / Clock')}</th><th>{t('事件', 'Play')}</th><th>{t('客–主', 'Away–Home')}</th>
        <th>{t('主队胜率', 'Home win probability')}</th><th>{t('投篮坐标', 'Shot coordinates')}</th></tr></thead>
      <tbody>{ordered.slice(0, limit).map((play, index) => {
        const probability = probabilities.get(label(play.id));
        const coordinate = asObject(play.coordinate);
        const x = coordinate.x;
        const y = coordinate.y;
        const located = play.shootingPlay && typeof x === 'number' && typeof y === 'number' && Math.abs(x) < 150 && Math.abs(y) < 150;
        return <tr key={label(play.id ?? index)}>
          <td>Q{label(asObject(play.period).number)} · {label(asObject(play.clock).displayValue)}
            {typeof play.wallclock === 'string' && <small>{formatDateTime(play.wallclock)}</small>}</td>
          <td>{label(play.text ?? play.shortDescription)}</td><td>{label(play.awayScore)}–{label(play.homeScore)}</td>
          <td>{typeof probability === 'number' && probability >= 0 && probability <= 1 ? `${(100 * probability).toFixed(1)}%` : '—'}</td>
          <td>{located ? `${x}, ${y}` : '—'}</td>
        </tr>;
      })}</tbody>
    </table></div>
    {limit < plays.length && <button type="button" onClick={() => setLimit(limit + 40)}>{t('显示更多回合', 'Show more plays')}</button>}
  </div>;
}

export function GameDetail({ game, gameId }: { game: RuntimeNbaGame; gameId: string }) {
  const [tab, setTab] = useState<Tab>('overview');
  const { locale, formatDateTime } = useSpecialistCopy('nba-scoreboard');
  const t: Translate = (zh, en) => locale === 'zh' ? zh : en;
  const live = game.state === 'in';
  const detail = usePanelResource({
    key: `nba-game-detail:${gameId}:v1`, title: t('ESPN 比赛详情', 'ESPN game detail'), cache: null,
    maxAgeMs: live ? 180000 : 1200000, staleAgeMs: 86400000, acceptStale: true,
    refreshPolicy: { tier: 'fast', intervalMs: live ? 60000 : 600000, requestTimeoutMs: 23000 },
    fetch: context => fetchNbaGameDetail(gameId, context?.signal),
    parse: value => parseDetail(value, gameId),
    updatedAt: value => Date.parse(value.summaryFetchedAt) || Date.parse(value.scoreboardFetchedAt),
  });
  const text: Record<Tab, string> = {
    overview: t('概览', 'Overview'), boxscore: t('技术统计', 'Box score'), plays: t('逐回合', 'Play-by-play'),
    context: t('伤停、盘口与资料', 'Injuries, lines & context'), source: t('全部 ESPN 字段', 'All ESPN fields'),
  };
  const value = detail.data;
  const summary = value?.summary ?? {};
  const scoreboard = value?.scoreboard ?? {};
  const context: Array<[string, unknown]> = [
    [t('伤停', 'Injuries'), summary.injuries], [t('比赛资料与裁判', 'Game information and officials'), summary.gameInfo],
    [t('赛季交锋', 'Season series'), summary.seasonseries], [t('排行榜', 'Standings'), summary.standings],
    [t('球队战绩和当前数据', 'Team records and scoreboard stats'), rows(scoreboard.competitions)[0]?.competitors],
    [t('博彩公司参考盘口', 'Sportsbook reference lines'), summary.pickcenter],
    [t('盘口记录', 'Odds'), summary.odds], [t('让分战绩', 'Against the spread'), summary.againstTheSpread],
    [t('转播', 'Broadcasts'), summary.broadcasts], [t('新闻', 'News'), summary.news], [t('集锦', 'Highlights'), summary.videos],
  ];
  return <section className="wm-nba-detail" aria-label={t('比赛详情', 'Game detail')}>
    <div className="wm-nba-detail-tabs">
      {tabs.map(id => <button key={id} aria-pressed={tab === id} onClick={() => setTab(id)} type="button">{text[id]}</button>)}
    </div>
    {value && <p className="wm-nba-source-time">
      ESPN · {value.summaryFetchedAt === '—' ? t('单场详情待采集', 'Detail pending') : formatDateTime(value.summaryFetchedAt)}
      {value.status === 'stale' && ` · ${t('保留的历史快照', 'Retained snapshot')}`}
    </p>}
    {!value && <p role="status">{detail.error ? t('ESPN 详情暂不可用。', 'ESPN detail is unavailable.') : t('正在读取 ESPN 比赛详情…', 'Loading ESPN game detail…')}</p>}
    {tab === 'overview' && <Overview game={game} scoreboard={scoreboard} summary={summary} t={t} />}
    {tab === 'boxscore' && value && <BoxScore summary={summary} t={t} />}
    {tab === 'plays' && value && <Plays summary={summary} t={t} formatDateTime={formatDateTime} />}
    {tab === 'context' && value && <Context summary={summary} sections={context} t={t} />}
    {tab === 'source' && value && <SourceSections key="source" t={t} includeEmpty
      sections={[...Object.entries(scoreboard).map(([key, row]): [string, unknown] => [`Scoreboard · ${key}`, row]),
        ...Object.entries(summary).map(([key, row]): [string, unknown] => [`Summary · ${key}`, row])]} />}
  </section>;
}
