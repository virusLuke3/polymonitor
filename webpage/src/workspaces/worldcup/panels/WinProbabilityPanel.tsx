import { SourceRequired } from '../components/SourceRequired';
import { WorldCupPanel as Panel } from '../components/WorldCupPanel';
import type { WorldCupMatch, WorldCupOddsSnapshot, WorldCupPolymarketMarket } from '../types';

type WorldCupProbabilityRow = {
  team: string;
  poly: number | null;
  book: number | null;
  edge: number | null;
  volume: number;
};

type WorldCupBookmakerProbabilityRow = {
  key: string;
  title: string;
  lastUpdate: string;
  outcomes: Array<{
    team: string;
    probability: number | null;
    decimalOdds: number | null;
  }>;
};

function percentLabel(value?: number | null, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  return `${Number(value).toFixed(digits)}%`;
}

function percentFromUnknown(value?: number | string | null) {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return numeric >= 0 && numeric <= 1 ? numeric * 100 : numeric;
}

function outcomeMatchesTeam(name: string | undefined, team: string) {
  const left = String(name || '').trim().toLowerCase();
  const right = String(team || '').trim().toLowerCase();
  if (!left || !right) return false;
  if (team === 'Draw') return /draw|tie|\bx\b/i.test(left);
  if (left === right) return true;
  const leftTokens = new Set(left.split(/[^a-z0-9]+/).filter(Boolean));
  const rightTokens = right.split(/[^a-z0-9]+/).filter((part) => part.length > 1);
  return rightTokens.some((token) => leftTokens.has(token));
}

function snapshotOutcomePercent(snapshot: WorldCupOddsSnapshot | undefined, team: string) {
  if (!snapshot) return null;
  const direct = (snapshot.outcomes || []).find((outcome) => outcomeMatchesTeam(outcome.name, team));
  if (direct) return percentFromUnknown(direct.impliedProbability ?? direct.price ?? null);
  const probability = (snapshot.probabilities || []).find((row) => outcomeMatchesTeam(row.outcome || row.name, team));
  return percentFromUnknown(probability?.impliedProbability ?? probability?.price ?? null);
}

function buildBookmakerProbabilityRows(snapshot: WorldCupOddsSnapshot | undefined, match: WorldCupMatch | null): WorldCupBookmakerProbabilityRow[] {
  if (!snapshot || !match) return [];
  const teams = [match.homeTeam, 'Draw', match.awayTeam];
  return (snapshot.bookmakers || [])
    .map((bookmaker, index) => {
      const outcomes = teams.map((team) => {
        const outcome = (bookmaker.outcomes || []).find((row) => outcomeMatchesTeam(row.name, team));
        return {
          team,
          probability: percentFromUnknown(outcome?.impliedProbability ?? null),
          decimalOdds: outcome?.decimalOdds == null ? null : Number(outcome.decimalOdds),
        };
      });
      return {
        key: bookmaker.key || `${bookmaker.title}-${index}`,
        title: bookmaker.title || bookmaker.key || 'Book',
        lastUpdate: bookmaker.lastUpdate || snapshot.generatedAt || '',
        outcomes,
      };
    })
    .filter((row) => row.outcomes.some((outcome) => outcome.probability != null));
}

function compactTimeLabel(value: string) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
    timeZoneName: 'short',
  }).format(date);
}

function buildWinProbabilityRows(markets: WorldCupPolymarketMarket[], odds: WorldCupOddsSnapshot[], match: WorldCupMatch | null): WorldCupProbabilityRow[] {
  if (!match) return [];
  const market = markets[0];
  const bookmakerSnapshot = odds.find((snapshot) => snapshot.providerType !== 'prediction_market');
  const predictionSnapshot = odds.find((snapshot) => snapshot.providerType === 'prediction_market' || /polymarket/i.test(snapshot.provider || snapshot.source || ''));
  const teams = [match.homeTeam, 'Draw', match.awayTeam];
  return teams.map((team) => {
    const marketOutcome = market?.outcomes.find((outcome) => outcome.name.toLowerCase() === team.toLowerCase() || (team === 'Draw' && /draw/i.test(outcome.name)));
    const poly = marketOutcome?.yesPrice == null
      ? snapshotOutcomePercent(predictionSnapshot, team)
      : percentFromUnknown(marketOutcome.yesPrice);
    const book = snapshotOutcomePercent(bookmakerSnapshot, team);
    if (poly == null && book == null) return null;
    return {
      team,
      poly,
      book,
      edge: poly != null && book != null ? poly - book : null,
      volume: market?.volume24h || 0,
    };
  }).filter((row): row is WorldCupProbabilityRow => Boolean(row));
}

export function WinProbabilityPanel({
  markets,
  odds,
  match,
}: {
  markets: WorldCupPolymarketMarket[];
  odds: WorldCupOddsSnapshot[];
  match: WorldCupMatch | null;
}) {
  const rows = buildWinProbabilityRows(markets, odds, match);
  const bookmakerSnapshot = odds.find((snapshot) => snapshot.providerType !== 'prediction_market');
  const bookmakerRows = buildBookmakerProbabilityRows(bookmakerSnapshot, match);
  const outcomeLabels = match ? [match.homeTeam, 'Draw', match.awayTeam] : [];
  const pricedRows = rows.filter((row) => row.poly != null);
  const probabilityRows = pricedRows.length ? pricedRows : rows.filter((row) => row.book != null);
  const leader = probabilityRows.length
    ? probabilityRows.reduce((best, row) => ((row.poly ?? row.book) || 0) > ((best.poly ?? best.book) || 0) ? row : best, probabilityRows[0]!)
    : null;
  const hasPolymarket = rows.some((row) => row.poly != null);
  const hasBook = rows.some((row) => row.book != null);
  return (
    <Panel title="WIN PROBABILITY" count={bookmakerRows.length || rows.length} className="wm-worldcup-panel wm-worldcup-win-probability-panel">
      {rows.length ? (
        <>
          <div className="wm-worldcup-prob-headline">
            <span><em>{hasPolymarket ? 'MARKET LEADER' : 'BOOK LEADER'}</em><strong>{leader?.team || '--'}</strong><b>{percentLabel(leader?.poly ?? leader?.book)}</b></span>
            <span><em>{hasPolymarket && hasBook ? 'EDGE' : 'SOURCE'}</em><strong className={(leader?.edge || 0) >= 0 ? 'green' : 'red'}>{leader?.edge == null ? (hasBook ? 'BOOK' : 'POLY') : `${leader.edge >= 0 ? '+' : ''}${percentLabel(leader.edge)}`}</strong><b>{hasPolymarket && hasBook ? 'poly-book' : 'real odds'}</b></span>
          </div>
          <div className="wm-worldcup-prob-table">
            <header><span>OUTCOME</span><span>POLY</span><span>BOOK</span><span>EDGE</span></header>
            {rows.map((row) => (
              <div key={row.team}>
                <strong>{row.team}</strong>
                <span><b>{percentLabel(row.poly)}</b><i style={{ width: row.poly == null ? '0%' : `${row.poly}%` }} /></span>
                <span><b>{percentLabel(row.book)}</b><i style={{ width: row.book == null ? '0%' : `${row.book}%` }} /></span>
                <em className={(row.edge || 0) >= 0 ? 'green' : 'red'}>{row.edge == null ? '--' : `${row.edge >= 0 ? '+' : ''}${percentLabel(row.edge)}`}</em>
              </div>
            ))}
          </div>
          {bookmakerRows.length ? (
            <div className="wm-worldcup-bookmaker-board">
              <header>
                <span>BOOKMAKER</span>
                {outcomeLabels.map((label) => <span key={label}>{label}</span>)}
                <span>UPDATE</span>
              </header>
              {bookmakerRows.map((bookmaker) => (
                <article key={bookmaker.key}>
                  <strong title={bookmaker.title}>{bookmaker.title}</strong>
                  {bookmaker.outcomes.map((outcome) => (
                    <span key={outcome.team}>
                      <b>{percentLabel(outcome.probability)}</b>
                      <em>{outcome.decimalOdds == null || !Number.isFinite(outcome.decimalOdds) ? '--' : outcome.decimalOdds.toFixed(2)}</em>
                      <i style={{ width: outcome.probability == null ? '0%' : `${Math.max(2, Math.min(100, outcome.probability))}%` }} />
                    </span>
                  ))}
                  <time dateTime={bookmaker.lastUpdate}>{compactTimeLabel(bookmaker.lastUpdate)}</time>
                </article>
              ))}
            </div>
          ) : null}
        </>
      ) : (
        <SourceRequired
          detail="Win probabilities require real Polymarket outcome prices, bookmaker probabilities, or both. No hash/model fallback is rendered."
          rows={[
            { source: 'Polymarket local DB / Gamma', status: markets.length ? 'linked without prices' : 'not matched', detail: 'yesPrice per outcome' },
            { source: 'Bookmaker odds API', status: odds.length ? 'available' : 'not connected', detail: 'impliedProbability per outcome' },
          ]}
        />
      )}
    </Panel>
  );
}
