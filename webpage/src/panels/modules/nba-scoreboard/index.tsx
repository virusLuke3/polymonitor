import { useState } from 'preact/hooks';
import { publicFeedSnapshot } from '@/panels/shared/public-feed-snapshot';
import type { PanelInputs } from '../../types';
import type { RuntimeNbaPayload } from '@/types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { emptyState } from '@/panels/shared/renderers';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { fetchRuntimeNba } from '@/services/api';
import { runtimePanelFromRenderer } from '@/panels/definePanel';
import { GameDetail } from './GameDetail';
import './style.css';

type Inputs = PanelInputs;

function NbaGames({ items }: { items: RuntimeNbaPayload['items'] }) {
  const { locale, copy, shared, formatDateTime } = useSpecialistCopy('nba-scoreboard');
  const [expanded, setExpanded] = useState<string | null>(null);
  const zh = locale === 'zh';
  if (!items.length) return emptyState(copy('empty', 'No NBA games loaded.'));
  return (
    <div className="wm-scoreboard-list">
      {items.map((game) => {
        const inProgress = game.state === 'in';
        const scheduled = game.state === 'pre';
        const period = game.period ?? 0;
        const stage = period > 4 ? `OT${period - 4}` : period > 0 ? `Q${period}` : '';
        const status = inProgress ? [stage, game.displayClock].filter(Boolean).join(' · ') || (zh ? '进行中' : 'Live')
          : game.state === 'post' ? (zh ? '完赛' : 'Final') : game.status || game.state;
        const gameId = game.id;
        const isOpen = Boolean(gameId && expanded === gameId);
        return (
        <article className="wm-score-card" key={game.id || game.name}>
          <div className="wm-score-card-head">
            <strong>{game.awayTeam} @ {game.homeTeam}</strong>
            <span>{status}</span>
          </div>
          <div className="wm-score-card-body">
            <div className="wm-score-team-row">
              <span>{game.awayTeam || shared('awayTitle', 'Away')}</span>
              <strong>{scheduled ? '—' : game.awayScore ?? '—'}</strong>
            </div>
            <div className="wm-score-team-row">
              <span>{game.homeTeam || shared('homeTitle', 'Home')}</span>
              <strong>{scheduled ? '—' : game.homeScore ?? '—'}</strong>
            </div>
          </div>
          <div className="wm-score-card-meta">
            {game.tipoff && <span>{zh ? '计划开球' : 'Scheduled tipoff'} · {formatDateTime(game.tipoff)}</span>}
            {game.broadcast && <span>{game.broadcast}</span>}
          </div>
          {gameId && <button className="wm-nba-detail-toggle" type="button" aria-expanded={isOpen}
            onClick={() => setExpanded(isOpen ? null : gameId)}>
            {isOpen ? (zh ? '收起详情' : 'Hide details') : (zh ? '比赛详情' : 'Game details')}
          </button>}
          {isOpen && gameId && <GameDetail key={gameId} gameId={gameId} game={game} />}
        </article>
        );
      })}
    </div>
  );
}

function NbaScoreboardPanel({ ctx }: { ctx: Inputs }) {
  const { copy, locale } = useSpecialistCopy('nba-scoreboard');
  const snapshot = ctx.runtimeData['nba-scoreboard'] as RuntimeNbaPayload | undefined;
  const items = snapshot?.items ?? [];
  return <Panel title={copy('title', 'NBA SCOREBOARD')} badge="SPORTS" status={snapshot?.status === 'ok' ? 'live' : 'muted'}
    count={items.length} className="wm-market-panel wm-nba-scoreboard-panel" dataPanelId="nba-scoreboard">
    {snapshot?.status === 'stale' && <p role="status">{locale === 'zh' ? '比分板快照已过期' : 'Scoreboard snapshot is stale'}</p>}
    <NbaGames items={items} />
  </Panel>;
}

const renderers: PanelRenderMap = {
  'nba-scoreboard': {
    render: (ctx) => <NbaScoreboardPanel ctx={ctx} />,
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'nba-scoreboard',
  snapshot: publicFeedSnapshot('nba-scoreboard', 20),
  title: 'NBA Scoreboard',
  eyebrow: 'sports',
  description: 'Upcoming and live NBA games.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 60000,
  limit: 20,
  fetchData: (context, limit) => fetchRuntimeNba(limit, context?.signal),
});
