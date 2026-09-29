import type { PanelInputs } from '../../types';
import type { RuntimeNbaIntelPayload } from '@/types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { emptyState } from '@/panels/shared/renderers';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { fetchRuntimeNbaIntel } from '@/services/api';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

type Inputs = PanelInputs;

function nbaIntelPanel(ctx: Inputs, copy: ReturnType<typeof useSpecialistCopy>['copy'], shared: ReturnType<typeof useSpecialistCopy>['shared'], formatDateTime: ReturnType<typeof useSpecialistCopy>['formatDateTime']) {
  const intel = (ctx.runtimeData['nba-intel'] as RuntimeNbaIntelPayload | undefined);
  if (!intel || (!intel.items.length && !intel.lineups.length)) {
    return emptyState(copy('empty', 'No NBA intel loaded.'));
  }
  return (
    <div className="wm-panel-stack">
      {!!intel.lineups.length && (
        <section className="wm-subpanel">
          <div className="wm-subpanel-title">{copy('lineups', 'LINEUPS')}</div>
          <div className="wm-panel-list">
            {intel.lineups.slice(0, 3).map((game, index) => (
              <article className="wm-lineup-card" key={`${game.gameId || game.label}-${index}`}>
                <div className="wm-lineup-head">
                  <strong>{game.label || copy('matchup', 'NBA matchup')}</strong>
                  <span>{game.status || '--'}</span>
                </div>
                <div className="wm-lineup-columns">
                  {['HOME', 'AWAY'].map((side) => (
                    <div className="wm-lineup-team" key={side}>
                      <div className="wm-lineup-team-label">{side === 'HOME' ? shared('home', 'HOME') : shared('away', 'AWAY')}</div>
                      <div className="wm-lineup-players">
                        {(game.starters || []).filter((player) => player.side === side).slice(0, 5).map((player, playerIndex) => (
                          <div className="wm-lineup-player" key={`${side}-${player.playerName}-${playerIndex}`}>
                            <span>{player.playerName || '--'}</span>
                            <em>{player.position || player.lineupStatus || ''}</em>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
      {!!intel.items.length && (
        <section className="wm-subpanel">
          <div className="wm-subpanel-title">{copy('beatIntel', 'ESPN / BEAT INTEL')}</div>
          <div className="wm-panel-list">
            {intel.items.slice(0, 8).map((item, index) => (
              <a className="wm-news-card" href={item.url || '#'} target="_blank" rel="noreferrer" key={`${item.url || item.headline}-${index}`}>
                <div className="wm-news-source">{item.source || 'ESPN'}</div>
                <div className="wm-news-title">{item.headline || copy('intelItem', 'NBA intel item')}</div>
                <div className="wm-news-meta">{formatDateTime(item.publishedAt || '')}</div>
              </a>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function NbaIntelPanel({ ctx }: { ctx: Inputs }) {
  const { copy, shared, formatDateTime } = useSpecialistCopy('nba-intel');
  return <Panel title={copy('title', 'NBA INTEL')} badge="ESPN" status="live" count={(ctx.runtimeData['nba-intel'] as RuntimeNbaIntelPayload | undefined)?.items.length || 0} className="wm-market-panel wm-nba-intel-panel" dataPanelId="nba-intel">{nbaIntelPanel(ctx, copy, shared, formatDateTime)}</Panel>;
}

const renderers: PanelRenderMap = {
  'nba-intel': {
    size: 'wide',
    render: (ctx) => <NbaIntelPanel ctx={ctx} />,
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'nba-intel',
  title: 'NBA Intel',
  eyebrow: 'sports',
  description: 'ESPN news, starting lineups, and pregame rumors.',
  size: 'wide',
  defaultEnabled: true,
}, {
  tier: 'slow',
  limit: 12,
  fetchData: (context, limit) => fetchRuntimeNbaIntel(limit, context?.signal),
});
