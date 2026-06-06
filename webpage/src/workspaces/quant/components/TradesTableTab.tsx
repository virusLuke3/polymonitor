import type { Trade, TradeFilter } from '../types';
import { fmtCurrency, fmtPrice, statusClass } from '../utils/formatters';

type TradesTableTabProps = {
  trades: Trade[];
  filters: Set<TradeFilter>;
  selectedTradeId: string | null;
  onToggleFilter: (filter: TradeFilter) => void;
  onSelectTrade: (tradeId: string) => void;
};

const FILTERS: Array<[TradeFilter, string]> = [
  ['profitable', 'Profitable only'],
  ['losing', 'Losing only'],
  ['yes', 'YES only'],
  ['no', 'NO only'],
  ['longHolding', 'Long holding'],
  ['shortHolding', 'Short holding'],
];

export function TradesTableTab({ trades, filters, selectedTradeId, onToggleFilter, onSelectTrade }: TradesTableTabProps) {
  return (
    <div className="qtv-table-wrap">
      <div className="qtv-filter-strip">
        {FILTERS.map(([id, label]) => (
          <button key={id} className={filters.has(id) ? 'active' : ''} type="button" onClick={() => onToggleFilter(id)}>{label}</button>
        ))}
        <span>{trades.length} trades</span>
      </div>
      <table className="qtv-table">
        <thead>
          <tr><th>Trade #</th><th>Entry Time</th><th>Exit Time</th><th>Market</th><th>Outcome</th><th>Side</th><th>Entry</th><th>Exit</th><th>Size</th><th>Notional</th><th>PnL</th><th>PnL %</th><th>Holding</th><th>Exit Reason</th></tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.id} className={selectedTradeId === trade.id ? 'selected' : ''} onClick={() => onSelectTrade(trade.id)}>
              <td>{trade.id}</td>
              <td>{trade.entryTime}</td>
              <td>{trade.exitTime}</td>
              <td>{trade.market}</td>
              <td>{trade.outcome}</td>
              <td>{trade.side}</td>
              <td>{fmtPrice(trade.entryPrice)}</td>
              <td>{fmtPrice(trade.exitPrice)}</td>
              <td>{trade.size}</td>
              <td>{fmtCurrency(trade.notional)}</td>
              <td className={statusClass(trade.pnl)}>{fmtCurrency(trade.pnl)}</td>
              <td className={statusClass(trade.pnlPct)}>{trade.pnlPct.toFixed(2)}%</td>
              <td>{trade.holdingTime}</td>
              <td>{trade.exitReason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
