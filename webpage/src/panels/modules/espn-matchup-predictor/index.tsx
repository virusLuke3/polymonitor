import type { PanelInputs } from '../../types';
import type { RuntimeNbaMatchupPredictorPayload } from '@/types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { emptyState } from '@/panels/shared/renderers';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { fetchRuntimeNbaMatchupPredictor } from '@/services/api';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

type Inputs = PanelInputs;

function formatProbability(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  return `${Number(value).toFixed(1)}%`;
}

function clampPercent(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 0;
  return Math.min(100, Math.max(0, Number(value)));
}

function formatNumber(value?: number | null, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  return Number(value).toFixed(digits);
}

function formatMargin(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  const numeric = Number(value);
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${numeric.toFixed(1)}`;
}

function nbaMatchupPredictorPanel(ctx: Inputs, copy: ReturnType<typeof useSpecialistCopy>['copy'], shared: ReturnType<typeof useSpecialistCopy>['shared'], formatDateTime: ReturnType<typeof useSpecialistCopy>['formatDateTime']) {
  const items = (ctx.runtimeData['espn-matchup-predictor'] as RuntimeNbaMatchupPredictorPayload | undefined)?.items || [];
  if (!items.length) return emptyState(copy('empty', 'No ESPN Matchup Predictor data loaded.'));
  return (
    <div className="wm-matchup-predictor-list">
      {items.map((game, index) => {
        const awayWidth = clampPercent(game.awayWinProbability);
        const homeWidth = clampPercent(game.homeWinProbability);
        return (
          <article className="wm-score-card wm-matchup-card" key={`${game.eventId || game.shortName}-${index}`}>
            <div className="wm-score-card-head">
              <strong>{game.shortName || `${game.awayTeam || shared('awayTitle', 'Away')} @ ${game.homeTeam || shared('homeTitle', 'Home')}`}</strong>
              <span>{game.state || game.status || 'pre'}</span>
            </div>
            <div className="wm-score-card-meta">
              <span>{formatDateTime(game.tipoff || '')}</span>
              <span>{game.status || 'ESPN BPI'}</span>
            </div>
            <div className="wm-matchup-prob-stack">
              <div className="wm-matchup-prob-row">
                <div className="wm-matchup-prob-label">
                  <span>{game.awayTeam || shared('awayTitle', 'Away')}</span>
                  <strong>{formatProbability(game.awayWinProbability)}</strong>
                </div>
                <div className="wm-matchup-prob-track">
                  <div className="wm-matchup-prob-fill away" style={{ width: `${awayWidth}%` }} />
                </div>
              </div>
              <div className="wm-matchup-prob-row">
                <div className="wm-matchup-prob-label">
                  <span>{game.homeTeam || shared('homeTitle', 'Home')}</span>
                  <strong>{formatProbability(game.homeWinProbability)}</strong>
                </div>
                <div className="wm-matchup-prob-track">
                  <div className="wm-matchup-prob-fill home" style={{ width: `${homeWidth}%` }} />
                </div>
              </div>
            </div>
            <div className="wm-matchup-metrics">
              <div>
                <span>{copy('quality', 'QUALITY')}</span>
                <strong>{formatNumber(game.matchupQuality, 1)}</strong>
              </div>
              <div>
                <span>{copy('awayMargin', 'AWAY MARGIN')}</span>
                <strong>{formatMargin(game.projectedMargin)}</strong>
              </div>
              <div>
                <span>{copy('expected', 'EXPECTED')}</span>
                <strong>{formatNumber(game.awayExpectedPoints, 1)} - {formatNumber(game.homeExpectedPoints, 1)}</strong>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function EspnPredictorPanel({ ctx }: { ctx: Inputs }) {
  const { copy, shared, formatDateTime } = useSpecialistCopy('espn-matchup-predictor');
  return <Panel title={copy('title', 'ESPN MATCHUP PREDICTOR')} badge="BPI" status="live" count={(ctx.runtimeData['espn-matchup-predictor'] as RuntimeNbaMatchupPredictorPayload | undefined)?.items.length || 0} className="wm-market-panel wm-matchup-predictor-panel" dataPanelId="espn-matchup-predictor">{nbaMatchupPredictorPanel(ctx, copy, shared, formatDateTime)}</Panel>;
}

const renderers: PanelRenderMap = {
  'espn-matchup-predictor': {
    size: 'wide',
    render: (ctx) => <EspnPredictorPanel ctx={ctx} />,
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'espn-matchup-predictor',
  title: 'ESPN Matchup Predictor',
  eyebrow: 'sports',
  description: 'ESPN BPI win probability, matchup quality, projected margin, and expected score.',
  size: 'wide',
  defaultEnabled: true,
}, {
  tier: 'slow',
  limit: 8,
  fetchData: (context, limit) => fetchRuntimeNbaMatchupPredictor(limit, context?.signal),
});
