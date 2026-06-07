import { useMemo, useState } from 'preact/hooks';
import type {
  BacktestResult,
  PerformanceSortKey,
  SortDirection,
  TesterTab,
  TradeFilter,
} from '../types';
import { EquityDrawdownChart } from './EquityDrawdownChart';
import { MetricCard } from './MetricCard';
import { PerformanceSummaryTab } from './PerformanceSummaryTab';
import { PropertiesTab } from './PropertiesTab';
import { TradesTableTab } from './TradesTableTab';

type ToolTab = 'screener' | 'editor' | 'tester' | 'replay' | 'trading';

const TOOL_TABS: Array<[ToolTab, string]> = [
  ['screener', 'Market Screener'],
  ['editor', 'Strategy Editor'],
  ['tester', 'Strategy Tester'],
  ['replay', 'Replay Trading'],
  ['trading', 'Trading Panel'],
];

type StrategyTesterPanelProps = {
  result: BacktestResult;
  testerTab: TesterTab;
  deepBacktest: boolean;
  selectedTradeId: string | null;
  performanceSearch: string;
  performanceSortKey: PerformanceSortKey;
  performanceSortDirection: SortDirection;
  tradeFilters: Set<TradeFilter>;
  filteredPerformanceRows: BacktestResult['performanceRows'];
  filteredTrades: BacktestResult['trades'];
  onTesterTabChange: (tab: TesterTab) => void;
  onDeepBacktestChange: () => void;
  onRefresh: () => void;
  onExport: (format: 'csv' | 'json') => void;
  onPerformanceSearchChange: (value: string) => void;
  onPerformanceSortChange: (key: PerformanceSortKey) => void;
  onTradeFilterToggle: (filter: TradeFilter) => void;
  onTradeSelect: (tradeId: string) => void;
};

export function StrategyTesterPanel({
  result,
  testerTab,
  deepBacktest,
  selectedTradeId,
  performanceSearch,
  performanceSortKey,
  performanceSortDirection,
  tradeFilters,
  filteredPerformanceRows,
  filteredTrades,
  onTesterTabChange,
  onDeepBacktestChange,
  onRefresh,
  onExport,
  onPerformanceSearchChange,
  onPerformanceSortChange,
  onTradeFilterToggle,
  onTradeSelect,
}: StrategyTesterPanelProps) {
  const [toolTab, setToolTab] = useState<ToolTab>('tester');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const hasCompletedRun = result.runId > 0 && result.metrics.length > 0;
  const summaryRows = useMemo(() => result.metrics.slice(0, 6), [result.metrics]);
  const latestTrade = result.trades[result.trades.length - 1];
  const selectedTrade = result.trades.find((trade) => trade.id === selectedTradeId) || latestTrade;

  return (
    <section className="qtv-bottom-panel">
      <nav className="qtv-tool-tabs" aria-label="Backtest tools">
        {TOOL_TABS.map(([id, label]) => (
          <button key={id} className={toolTab === id ? 'active' : ''} type="button" onClick={() => setToolTab(id)}>{label}</button>
        ))}
        <span className="qtv-powered">PolyData</span>
      </nav>

      <div className="qtv-tester-head">
        <div className="qtv-strategy-title">
          <strong>Momentum Probability Strategy</strong>
          <button
            className={settingsOpen ? 'active' : ''}
            type="button"
            title="Strategy settings"
            onClick={() => setSettingsOpen((current) => !current)}
          >
            Settings
          </button>
          <button type="button" onClick={onRefresh} title="Refresh strategy data">Refresh</button>
        </div>
        <div className="qtv-tester-actions">
          <label><input type="checkbox" checked readOnly /> Backtest mode</label>
          <label><input type="checkbox" checked={deepBacktest} onChange={onDeepBacktestChange} /> Deep Backtest</label>
          <button type="button" onClick={() => onExport('json')}>Export JSON</button>
        </div>
      </div>

      {toolTab === 'tester' ? (
        <nav className="qtv-subtabs" aria-label="Strategy tester tabs">
          {[
            ['overview', 'Overview'],
            ['performance', 'Performance Summary'],
            ['trades', 'List of Trades'],
            ['properties', 'Properties'],
          ].map(([id, label]) => (
            <button key={id} className={testerTab === id ? 'active' : ''} type="button" onClick={() => onTesterTabChange(id as TesterTab)}>{label}</button>
          ))}
        </nav>
      ) : (
        <div className="qtv-subtabs qtv-subtabs-static">
          <span>{TOOL_TABS.find(([id]) => id === toolTab)?.[1]}</span>
        </div>
      )}

      {settingsOpen ? (
        <div className="qtv-settings-strip">
          <span>entry threshold <b>{result.propertyGroups[1]?.rows.find((row) => row.label === 'Entry Threshold')?.value || '-'}</b></span>
          <span>exit threshold <b>{result.propertyGroups[1]?.rows.find((row) => row.label === 'Exit Threshold')?.value || '-'}</b></span>
          <span>framework <b>{result.propertyGroups[1]?.rows.find((row) => row.label === 'Backtest Engine')?.value || '-'}</b></span>
          <span>run <b>{result.runId ? `#${result.runId}` : '-'}</b></span>
        </div>
      ) : null}

      {toolTab === 'screener' ? (
        <div className="qtv-tool-panel">
          <div className="qtv-tool-grid">
            {summaryRows.length ? summaryRows.map((metric) => <MetricCard key={`screener-${metric.name}`} metric={metric} />) : (
              <div className="qtv-tool-empty">
                <strong>No screened backtest</strong>
                <span>Run a real backtest to populate market screening metrics.</span>
              </div>
            )}
          </div>
          <div className="qtv-mini-table qtv-tool-mini">
            <strong>Market Screener</strong>
            {result.performanceRows.slice(0, 8).map((row) => (
              <div key={`screener-${row.metric}`}>
                <span>{row.metric}</span>
                <b>{row.all}</b>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {toolTab === 'editor' ? (
        <div className="qtv-tool-panel qtv-tool-panel-single">
          <PropertiesTab groups={result.propertyGroups} />
        </div>
      ) : null}

      {toolTab === 'replay' ? (
        <div className="qtv-tool-panel">
          <div className="qtv-table-wrap">
            <table className="qtv-table">
              <thead>
                <tr>
                  <th>Trade</th>
                  <th>Entry Block</th>
                  <th>Exit Block</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>PnL</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {result.trades.map((trade) => (
                  <tr key={`replay-${trade.id}`} className={trade.id === selectedTradeId ? 'selected' : ''} onClick={() => onTradeSelect(trade.id)}>
                    <td>{trade.id}</td>
                    <td>{trade.entryX?.toLocaleString('en-US') || trade.entryTime}</td>
                    <td>{trade.exitX?.toLocaleString('en-US') || trade.exitTime}</td>
                    <td>{trade.entryPrice.toFixed(3)}</td>
                    <td>{trade.exitPrice.toFixed(3)}</td>
                    <td className={trade.pnl >= 0 ? 'positive' : 'negative'}>{trade.pnl.toFixed(2)}</td>
                    <td>{trade.exitReason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!result.trades.length ? <div className="qtv-tool-empty"><strong>No replay trades</strong><span>Run a completed backtest first.</span></div> : null}
          </div>
          <div className="qtv-mini-table qtv-tool-mini">
            <strong>Replay Cursor</strong>
            <div><span>Selected Trade</span><b>{selectedTrade?.id || '-'}</b></div>
            <div><span>Entry</span><b>{selectedTrade?.entryX?.toLocaleString('en-US') || selectedTrade?.entryTime || '-'}</b></div>
            <div><span>Exit</span><b>{selectedTrade?.exitX?.toLocaleString('en-US') || selectedTrade?.exitTime || '-'}</b></div>
            <div><span>Holding</span><b>{selectedTrade ? `${selectedTrade.holdingBars} bars` : '-'}</b></div>
          </div>
        </div>
      ) : null}

      {toolTab === 'trading' ? (
        <div className="qtv-tool-panel qtv-tool-panel-single">
          <div className="qtv-properties">
            <section>
              <h3>Trading Panel</h3>
              <div><span>Mode</span><strong>Backtest simulation</strong></div>
              <div><span>Selected Trade</span><strong>{selectedTrade?.id || '-'}</strong></div>
              <div><span>Outcome</span><strong>{selectedTrade?.outcome || 'YES'}</strong></div>
              <div><span>Size</span><strong>{selectedTrade ? selectedTrade.size.toLocaleString('en-US') : '100'}</strong></div>
              <div><span>Notional</span><strong>{selectedTrade ? `${selectedTrade.notional.toFixed(2)} USDC` : '-'}</strong></div>
              <div><span>Last PnL</span><strong className={selectedTrade && selectedTrade.pnl >= 0 ? 'positive' : 'negative'}>{selectedTrade ? `${selectedTrade.pnl.toFixed(2)} USDC` : '-'}</strong></div>
            </section>
          </div>
        </div>
      ) : null}

      {toolTab === 'tester' && testerTab === 'overview' ? (
        hasCompletedRun ? (
          <div className="qtv-overview">
            <div className="qtv-metrics-row">
              {result.metrics.map((metric) => <MetricCard key={metric.name} metric={metric} />)}
            </div>
            <div className="qtv-result-grid">
              <div className="qtv-equity-wrap">
                <div className="qtv-prediction-metrics">
                  {result.predictionMetrics.map((metric) => <MetricCard key={metric.name} metric={metric} />)}
                </div>
                <EquityDrawdownChart points={result.equity} />
              </div>
              <div className="qtv-mini-table">
                <strong>Strategy Report</strong>
                {result.performanceRows.slice(0, 8).map((row) => (
                  <div key={row.metric}>
                    <span>{row.metric}</span>
                    <b>{row.all}</b>
                  </div>
                ))}
                <button type="button" onClick={() => onExport('csv')}>Export CSV</button>
              </div>
            </div>
          </div>
        ) : (
          <div className="qtv-tester-empty">
            <strong>No completed real backtest</strong>
            <span>Select a market with rows, choose a framework, then run backtest.</span>
          </div>
        )
      ) : null}

      {toolTab === 'tester' && testerTab === 'performance' ? (
        <PerformanceSummaryTab
          rows={filteredPerformanceRows}
          search={performanceSearch}
          sortKey={performanceSortKey}
          sortDirection={performanceSortDirection}
          onSearchChange={onPerformanceSearchChange}
          onSortChange={onPerformanceSortChange}
        />
      ) : null}

      {toolTab === 'tester' && testerTab === 'trades' ? (
        <TradesTableTab
          trades={filteredTrades}
          filters={tradeFilters}
          selectedTradeId={selectedTradeId}
          onToggleFilter={onTradeFilterToggle}
          onSelectTrade={onTradeSelect}
        />
      ) : null}

      {toolTab === 'tester' && testerTab === 'properties' ? <PropertiesTab groups={result.propertyGroups} /> : null}
    </section>
  );
}
