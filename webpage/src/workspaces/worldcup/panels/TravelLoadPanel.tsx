import { SourceRequired } from '../components/SourceRequired';
import { WorldCupPanel as Panel } from '../components/WorldCupPanel';
import type { WorldCupDashboardPayload, WorldCupMatch } from '../types';

export function TravelLoadPanel({ payload, match }: { payload: WorldCupDashboardPayload; match: WorldCupMatch | null }) {
  const teams = match ? [match.homeTeam, match.awayTeam] : payload.rosters.slice(0, 2).map((roster) => roster.team);
  return (
    <Panel title="TRAVEL LOAD" count={0} className="wm-worldcup-panel wm-worldcup-travel-load-panel">
      <SourceRequired
        detail={`Travel load for ${teams.join(' / ') || 'selected teams'} requires actual team-base, previous-match and travel itinerary data. Distances and rest windows are not synthesized.`}
        rows={[
          { source: 'Official team base / federation logistics', status: 'required', detail: 'team camp location and travel dates' },
          { source: 'FIFA fixture history', status: payload.matches.length ? 'partial schedule only' : 'required', detail: 'previous fixture and recovery window' },
        ]}
      />
    </Panel>
  );
}
