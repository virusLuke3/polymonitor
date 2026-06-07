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
  const hasCompletedRun = result.runId > 0 && result.metrics.length > 0;

  return (
    <section className="qtv-bottom-panel">
      <nav className="qtv-tool-tabs" aria-label="Backtest tools">
        {['Market Screener', 'Strategy Editor', 'Strategy Tester', 'Replay Trading', 'Trading Panel'].map((item) => (
          <button key={item} className={item === 'Strategy Tester' ? 'active' : ''} type="button">{item}</button>
        ))}
        <span className="qtv-powered">PolyData</span>
      </nav>

      <div className="qtv-tester-head">
        <div className="qtv-strategy-title">
          <strong>Momentum Probability Strategy</strong>
          <button type="button" title="Strategy settings">Settings</button>
          <button type="button" onClick={onRefresh} title="Refresh strategy data">Refresh</button>
        </div>
        <div className="qtv-tester-actions">
          <label><input type="checkbox" checked readOnly /> Backtest mode</label>
          <label><input type="checkbox" checked={deepBacktest} onChange={onDeepBacktestChange} /> Deep Backtest</label>
          <button type="button" onClick={() => onExport('json')}>Export JSON</button>
        </div>
      </div>

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

      {testerTab === 'overview' ? (
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

      {testerTab === 'performance' ? (
        <PerformanceSummaryTab
          rows={filteredPerformanceRows}
          search={performanceSearch}
          sortKey={performanceSortKey}
          sortDirection={performanceSortDirection}
          onSearchChange={onPerformanceSearchChange}
          onSortChange={onPerformanceSortChange}
        />
      ) : null}

      {testerTab === 'trades' ? (
        <TradesTableTab
          trades={filteredTrades}
          filters={tradeFilters}
          selectedTradeId={selectedTradeId}
          onToggleFilter={onTradeFilterToggle}
          onSelectTrade={onTradeSelect}
        />
      ) : null}

      {testerTab === 'properties' ? <PropertiesTab groups={result.propertyGroups} /> : null}
    </section>
  );
}
