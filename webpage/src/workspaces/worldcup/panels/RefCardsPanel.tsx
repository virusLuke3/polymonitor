import { SignalRow, type WorldCupSignalItem } from '../components/SignalRow';
import { SourceRequired } from '../components/SourceRequired';
import { WorldCupPanel as Panel } from '../components/WorldCupPanel';

export function RefCardsPanel({ refVenue }: { refVenue: WorldCupSignalItem[] }) {
  return (
    <Panel title="REF / CARDS" count={refVenue.length} className="wm-worldcup-panel wm-worldcup-ref-cards-panel">
      {refVenue.length ? (
        <div className="wm-worldcup-ref-list">
          {refVenue.slice(0, 5).map((item) => <SignalRow item={item} key={item.id} />)}
        </div>
      ) : (
        <SourceRequired
          detail="Card profile requires assigned referee history and match-official data. No yellow/red/foul values are generated."
          rows={[{ source: 'FIFA referee appointments / historical referee stats', status: 'required', detail: 'cards, fouls, penalties and VAR tendency' }]}
        />
      )}
    </Panel>
  );
}
