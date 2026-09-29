import type { PanelInputs } from '../../types';
import type { RuntimeNbaPayload } from '@/types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { emptyState } from '@/panels/shared/renderers';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { fetchRuntimeNba } from '@/services/api';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

type Inputs = PanelInputs;

function nbaGames(items: RuntimeNbaPayload['items'], copy: ReturnType<typeof useSpecialistCopy>['copy'], shared: ReturnType<typeof useSpecialistCopy>['shared'], formatDateTime: ReturnType<typeof useSpecialistCopy>['formatDateTime']) {
  if (!items.length) return emptyState(copy('empty', 'No NBA games loaded.'));
  return (
    <div className="wm-scoreboard-list">
      {items.map((game) => (
        <article className="wm-score-card" key={game.id || game.name}>
          <div className="wm-score-card-head">
            <strong>{game.awayTeam} @ {game.homeTeam}</strong>
            <span>{game.state || 'pre'}</span>
          </div>
          <div className="wm-score-card-body">
            <div className="wm-score-team-row">
              <span>{game.awayTeam || shared('awayTitle', 'Away')}</span>
              <strong>{game.awayScore ?? '-'}</strong>
            </div>
            <div className="wm-score-team-row">
              <span>{game.homeTeam || shared('homeTitle', 'Home')}</span>
              <strong>{game.homeScore ?? '-'}</strong>
            </div>
          </div>
          <div className="wm-score-card-meta">
            <span>{formatDateTime(game.tipoff || '')}</span>
            <span>{game.status || game.broadcast || '--'}</span>
          </div>
        </article>
      ))}
    </div>
  );
}

function NbaScoreboardPanel({ ctx }: { ctx: Inputs }) {
  const { copy, shared, formatDateTime } = useSpecialistCopy('nba-scoreboard');
  return <Panel title={copy('title', 'NBA SCOREBOARD')} badge="SPORTS" status="live" count={(ctx.runtimeData['nba-scoreboard'] as RuntimeNbaPayload | undefined)?.items.length || 0} className="wm-market-panel wm-nba-scoreboard-panel" dataPanelId="nba-scoreboard">{nbaGames((ctx.runtimeData['nba-scoreboard'] as RuntimeNbaPayload | undefined)?.items || [], copy, shared, formatDateTime)}</Panel>;
}

const renderers: PanelRenderMap = {
  'nba-scoreboard': {
    render: (ctx) => <NbaScoreboardPanel ctx={ctx} />,
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'nba-scoreboard',
  title: 'NBA Scoreboard',
  eyebrow: 'sports',
  description: 'Upcoming and live NBA games.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  limit: 10,
  fetchData: (context, limit) => fetchRuntimeNba(limit, context?.signal),
});
