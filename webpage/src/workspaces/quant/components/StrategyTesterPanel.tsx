import { useMemo, useState } from 'preact/hooks';
import type {
  BacktestResult,
  PerformanceSortKey,
  SortDirection,
  StrategyParameters,
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

const TESTER_TABS: Array<[TesterTab, string]> = [
  ['overview', 'Overview'],
  ['parameters', 'Parameters'],
  ['performance', 'Performance'],
  ['trades', 'Trades'],
  ['equity', 'Equity Curve'],
  ['drawdown', 'Drawdown'],
  ['runs', 'Runs'],
  ['logs', 'Logs'],
  ['properties', 'Properties'],
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
  strategyParameters: StrategyParameters;
  onStrategyParametersChange: (parameters: StrategyParameters) => void;
  onStrategyAutoTune: () => void;
  marketTitle?: string;
  dataSource?: string;
  engine?: string;
  rowCount?: number;
  backtestStatus?: string;
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
  strategyParameters,
  onStrategyParametersChange,
  onStrategyAutoTune,
  marketTitle = 'No market selected',
  dataSource = '-',
  engine = '-',
  rowCount = 0,
  backtestStatus = 'idle',
}: StrategyTesterPanelProps) {
  const [toolTab, setToolTab] = useState<ToolTab>('tester');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [parameterPreset, setParameterPreset] = useState('Custom live config');
  const hasCompletedRun = result.runId > 0 && result.metrics.length > 0;
  const summaryRows = useMemo(() => result.metrics.slice(0, 6), [result.metrics]);
  const latestTrade = result.trades[result.trades.length - 1];
  const selectedTrade = result.trades.find((trade) => trade.id === selectedTradeId) || latestTrade;
  const propertyValue = (label: string) => {
    const target = label.toLowerCase();
    return result.propertyGroups
      .flatMap((group) => group.rows)
      .find((row) => row.label.toLowerCase() === target)?.value || '-';
  };
  const updateParameter = (key: keyof StrategyParameters, value: string) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return;
    onStrategyParametersChange({
      ...strategyParameters,
      [key]: key === 'maxHoldingBars' ? Math.round(numeric) : numeric,
    });
  };
  const applyPreset = (preset: string) => {
    setParameterPreset(preset);
    if (preset === 'Conservative') {
      onStrategyParametersChange({
        entryThreshold: 0.62,
        exitThreshold: 0.48,
        stopLoss: 0.055,
        takeProfit: 0.12,
        maxHoldingBars: 72,
        initialCapital: strategyParameters.initialCapital,
        positionSize: Math.max(1, Math.round(strategyParameters.positionSize * 0.75)),
        feeBps: strategyParameters.feeBps,
        slippageBps: Math.max(strategyParameters.slippageBps, 2),
        liquidityCapPct: Math.min(strategyParameters.liquidityCapPct, 25),
      });
      return;
    }
    if (preset === 'Aggressive') {
      onStrategyParametersChange({
        entryThreshold: 0.54,
        exitThreshold: 0.4,
        stopLoss: 0.11,
        takeProfit: 0.24,
        maxHoldingBars: 160,
        initialCapital: strategyParameters.initialCapital,
        positionSize: Math.max(1, Math.round(strategyParameters.positionSize * 1.25)),
        feeBps: strategyParameters.feeBps,
        slippageBps: strategyParameters.slippageBps,
        liquidityCapPct: Math.min(strategyParameters.liquidityCapPct, 60),
      });
      return;
    }
    if (preset === 'Backend defaults') {
      onStrategyParametersChange({
        entryThreshold: 0.58,
        exitThreshold: 0.44,
        stopLoss: 0.075,
        takeProfit: 0.16,
        maxHoldingBars: 96,
        initialCapital: 100000,
        positionSize: 100,
        feeBps: 0,
        slippageBps: 0,
        liquidityCapPct: 100,
      });
    }
  };
  const runSnapshotRows = [
    ['entry threshold', propertyValue('entry threshold')],
    ['exit threshold', propertyValue('exit threshold')],
    ['stop loss', propertyValue('stop loss')],
    ['take profit', propertyValue('take profit')],
    ['max hold', propertyValue('max hold')],
    ['position size', propertyValue('position size')],
    ['initial capital', propertyValue('initial capital')],
    ['fee bps', propertyValue('fee bps')],
    ['slippage bps', propertyValue('slippage bps')],
    ['liquidity cap', propertyValue('liquidity cap')],
  ];

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
          {TESTER_TABS.map(([id, label]) => (
            <button key={id} className={testerTab === id ? 'active' : ''} type="button" onClick={() => onTesterTabChange(id)}>{label}</button>
          ))}
        </nav>
      ) : (
        <div className="qtv-subtabs qtv-subtabs-static">
          <span>{TOOL_TABS.find(([id]) => id === toolTab)?.[1]}</span>
        </div>
      )}

      {settingsOpen ? (
        <div className="qtv-settings-strip">
          <span>entry <b>{strategyParameters.entryThreshold.toFixed(4)}</b></span>
          <span>exit <b>{strategyParameters.exitThreshold.toFixed(4)}</b></span>
          <span>stop <b>{strategyParameters.stopLoss.toFixed(4)}</b></span>
          <span>take <b>{strategyParameters.takeProfit.toFixed(4)}</b></span>
          <span>hold <b>{strategyParameters.maxHoldingBars} bars</b></span>
          <span>size <b>{strategyParameters.positionSize.toLocaleString('en-US')}</b></span>
          <span>fee <b>{strategyParameters.feeBps} bps</b></span>
          <span>slip <b>{strategyParameters.slippageBps} bps</b></span>
          <span>liq <b>{strategyParameters.liquidityCapPct}%</b></span>
          <span>framework <b>{propertyValue('engine')}</b></span>
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
            <div className="qtv-empty-terminal">
              <div>
                <strong>Strategy Tester idle</strong>
                <span>Momentum Probability Strategy</span>
              </div>
              <dl>
                <div><dt>Market</dt><dd>{marketTitle}</dd></div>
                <div><dt>Engine</dt><dd>{engine}</dd></div>
                <div><dt>Source</dt><dd>{dataSource}</dd></div>
                <div><dt>Rows</dt><dd>{rowCount.toLocaleString('en-US')}</dd></div>
                <div><dt>Status</dt><dd>{backtestStatus}</dd></div>
              </dl>
              <ul>
                <li className={marketTitle !== 'No market selected' ? 'ready' : ''}>Market selected</li>
                <li className={rowCount > 0 ? 'ready' : ''}>Price rows loaded</li>
                <li className={engine !== '-' ? 'ready' : ''}>Backtest engine ready</li>
              </ul>
              <div className="qtv-empty-actions">
                <button className="primary" type="button" onClick={onRefresh}>Run Backtest</button>
                <button type="button" onClick={() => setSettingsOpen(true)}>Settings</button>
                <button type="button" onClick={onRefresh}>Refresh</button>
              </div>
            </div>
          </div>
        )
      ) : null}

      {toolTab === 'tester' && testerTab === 'parameters' ? (
        <div className="qtv-parameters-panel">
          <section>
            <header>
              <strong>Strategy Parameters</strong>
              <select value={parameterPreset} onChange={(event) => applyPreset(event.currentTarget.value)}>
                <option>Custom live config</option>
                <option>Backend defaults</option>
                <option>Conservative</option>
                <option>Aggressive</option>
              </select>
            </header>
            <div className="qtv-parameter-grid">
              <label><span>Entry threshold</span><input type="number" min="0.001" max="0.999" step="0.001" value={strategyParameters.entryThreshold} onInput={(event) => updateParameter('entryThreshold', event.currentTarget.value)} /></label>
              <label><span>Exit threshold</span><input type="number" min="0.001" max="0.999" step="0.001" value={strategyParameters.exitThreshold} onInput={(event) => updateParameter('exitThreshold', event.currentTarget.value)} /></label>
              <label><span>Stop loss</span><input type="number" min="0.001" max="0.95" step="0.001" value={strategyParameters.stopLoss} onInput={(event) => updateParameter('stopLoss', event.currentTarget.value)} /></label>
              <label><span>Take profit</span><input type="number" min="0.001" max="5" step="0.001" value={strategyParameters.takeProfit} onInput={(event) => updateParameter('takeProfit', event.currentTarget.value)} /></label>
              <label><span>Max holding bars</span><input type="number" min="1" max="10000" step="1" value={strategyParameters.maxHoldingBars} onInput={(event) => updateParameter('maxHoldingBars', event.currentTarget.value)} /></label>
              <label><span>Position size</span><input type="number" min="1" step="1" value={strategyParameters.positionSize} onInput={(event) => updateParameter('positionSize', event.currentTarget.value)} /></label>
              <label><span>Initial capital</span><input type="number" min="1" step="100" value={strategyParameters.initialCapital} onInput={(event) => updateParameter('initialCapital', event.currentTarget.value)} /></label>
              <label><span>Fee bps</span><input type="number" min="0" max="1000" step="0.1" value={strategyParameters.feeBps} onInput={(event) => updateParameter('feeBps', event.currentTarget.value)} /></label>
              <label><span>Slippage bps</span><input type="number" min="0" max="1000" step="0.1" value={strategyParameters.slippageBps} onInput={(event) => updateParameter('slippageBps', event.currentTarget.value)} /></label>
              <label><span>Liquidity cap %</span><input type="number" min="0" max="100" step="1" value={strategyParameters.liquidityCapPct} onInput={(event) => updateParameter('liquidityCapPct', event.currentTarget.value)} /></label>
              <label><span>Engine</span><input readOnly value={engine} /></label>
              <label><span>Source rows</span><input readOnly value={rowCount.toLocaleString('en-US')} /></label>
              <label><span>Market</span><input readOnly value={marketTitle} /></label>
              <label><span>Status</span><input readOnly value={backtestStatus} /></label>
            </div>
            <div className="qtv-parameter-actions">
              <button type="button" onClick={onStrategyAutoTune}>Auto tune from loaded prices</button>
              <button type="button" onClick={() => applyPreset('Backend defaults')}>Reset defaults</button>
              <button className="primary" type="button" onClick={onRefresh}>Run Backtest</button>
            </div>
            <p>These controls are bound to the real backtest request. Fee bps, slippage bps, and liquidity cap are applied by the execution model; walk-forward controls still need backend support.</p>
          </section>
          <aside className="qtv-run-health">
            <strong>Readiness</strong>
            <span className={marketTitle !== 'No market selected' ? 'ready' : ''}>Market selected</span>
            <span className={rowCount > 0 ? 'ready' : ''}>Price rows loaded</span>
            <span className={engine !== '-' ? 'ready' : ''}>Engine configured</span>
            <span className={strategyParameters.entryThreshold > strategyParameters.exitThreshold ? 'ready' : ''}>Entry above exit</span>
            <div className="qtv-run-snapshot">
              <strong>Latest run snapshot</strong>
              {runSnapshotRows.map(([label, value]) => (
                <div key={label}><span>{label}</span><b>{value}</b></div>
              ))}
            </div>
            <button className="primary" type="button" onClick={onRefresh}>Run Backtest</button>
          </aside>
        </div>
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

      {toolTab === 'tester' && testerTab === 'equity' ? (
        <div className="qtv-chart-tab">
          <header><strong>Equity Curve</strong><span>{hasCompletedRun ? `Run #${result.runId}` : 'Run a backtest to populate equity.'}</span></header>
          {result.equity.length ? <EquityDrawdownChart points={result.equity} /> : <div className="qtv-tool-empty"><strong>No equity points</strong><span>Completed backtest equity is not available yet.</span></div>}
        </div>
      ) : null}

      {toolTab === 'tester' && testerTab === 'drawdown' ? (
        <div className="qtv-chart-tab">
          <header><strong>Drawdown</strong><span>{propertyValue('max drawdown') || 'Real drawdown appears after a completed run.'}</span></header>
          {result.equity.length ? <EquityDrawdownChart points={result.equity} /> : <div className="qtv-tool-empty"><strong>No drawdown curve</strong><span>Run a backtest with equity output first.</span></div>}
        </div>
      ) : null}

      {toolTab === 'tester' && testerTab === 'runs' ? (
        <div className="qtv-runs-panel">
          <section>
            <strong>Current Run</strong>
            <dl>
              <div><dt>Run</dt><dd>{result.runId ? `#${result.runId}` : '-'}</dd></div>
              <div><dt>Status</dt><dd>{backtestStatus}</dd></div>
              <div><dt>Engine</dt><dd>{engine}</dd></div>
              <div><dt>Rows</dt><dd>{rowCount.toLocaleString('en-US')}</dd></div>
              <div><dt>Trades</dt><dd>{result.trades.length.toLocaleString('en-US')}</dd></div>
              <div><dt>Metrics</dt><dd>{result.metrics.length.toLocaleString('en-US')}</dd></div>
            </dl>
          </section>
          <section>
            <strong>Latest Trade</strong>
            <dl>
              <div><dt>ID</dt><dd>{selectedTrade?.id || '-'}</dd></div>
              <div><dt>Outcome</dt><dd>{selectedTrade?.outcome || '-'}</dd></div>
              <div><dt>PnL</dt><dd className={selectedTrade && selectedTrade.pnl >= 0 ? 'positive' : 'negative'}>{selectedTrade ? `${selectedTrade.pnl.toFixed(2)} USDC` : '-'}</dd></div>
              <div><dt>Exit</dt><dd>{selectedTrade?.exitReason || '-'}</dd></div>
            </dl>
          </section>
        </div>
      ) : null}

      {toolTab === 'tester' && testerTab === 'logs' ? (
        <div className="qtv-logs-panel">
          <strong>Run Log</strong>
          <span>{new Date().toLocaleTimeString()} · status {backtestStatus}</span>
          <span>source {dataSource} · engine {engine} · rows {rowCount.toLocaleString('en-US')}</span>
          <span>{hasCompletedRun ? `loaded ${result.metrics.length} metrics, ${result.trades.length} trades, ${result.equity.length} equity points` : 'no completed real backtest in this panel yet'}</span>
        </div>
      ) : null}

      {toolTab === 'tester' && testerTab === 'properties' ? <PropertiesTab groups={result.propertyGroups} /> : null}
    </section>
  );
}
