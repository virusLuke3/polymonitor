import { useMemo, useState } from 'preact/hooks';
import type { QuantBacktestRun } from '@/types';
import type {
  BacktestResult,
  BatchBacktestRow,
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

const STRATEGY_PRESETS_KEY = 'polydata.quant.strategyPresets';

function formatPct(value: number, digits = 2) {
  if (!Number.isFinite(value)) return '--';
  return `${value.toFixed(digits)}%`;
}

function formatNumber(value: number, digits = 2) {
  if (!Number.isFinite(value)) return '--';
  return value.toLocaleString('en-US', { maximumFractionDigits: digits });
}

function statusForRisk(value: boolean) {
  return value ? 'ready' : 'review';
}

type SavedStrategyPreset = {
  name: string;
  parameters: StrategyParameters;
  savedAt: string;
};

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
  onBatchBacktest: () => void;
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
  batchRows?: BatchBacktestRow[];
  batchStatus?: string;
  recentBacktestRuns?: QuantBacktestRun[];
  backtestRunsStatus?: string;
  onRunLoad?: (runId: number) => void;
};

function loadSavedPresets(): SavedStrategyPreset[] {
  if (typeof window === 'undefined') return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STRATEGY_PRESETS_KEY) || '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item) => item && typeof item.name === 'string' && item.parameters);
  } catch {
    return [];
  }
}

function persistSavedPresets(presets: SavedStrategyPreset[]) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(STRATEGY_PRESETS_KEY, JSON.stringify(presets));
}

function hashText(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

function compactRunTime(value?: string | null) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function compactRows(value?: string | number | null) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '-';
  return numeric.toLocaleString('en-US');
}

async function copyText(value: string) {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  if (typeof document === 'undefined') return;
  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
}

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
  onBatchBacktest,
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
  batchRows = [],
  batchStatus = 'idle',
  recentBacktestRuns = [],
  backtestRunsStatus = 'idle',
  onRunLoad,
}: StrategyTesterPanelProps) {
  const [toolTab, setToolTab] = useState<ToolTab>('tester');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [parameterPreset, setParameterPreset] = useState('Custom live config');
  const [savedPresets, setSavedPresets] = useState<SavedStrategyPreset[]>(loadSavedPresets);
  const [presetDraftName, setPresetDraftName] = useState('Momentum live');
  const [copyNotice, setCopyNotice] = useState('');
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
  const runPayload = useMemo(() => ({
    runId: result.runId || null,
    market: marketTitle,
    source: dataSource,
    engine,
    rows: rowCount,
    status: backtestStatus,
    generatedAt: result.generatedAt,
    strategy: strategyParameters,
    lastRun: {
      marketSlug: propertyValue('market slug'),
      tokenSide: propertyValue('token side'),
      outcome: propertyValue('outcome'),
      fromBlock: propertyValue('from block'),
      toBlock: propertyValue('to block'),
      rowsProcessed: propertyValue('rows processed'),
    },
  }), [backtestStatus, dataSource, engine, marketTitle, result.generatedAt, result.runId, rowCount, strategyParameters]);
  const runPayloadText = useMemo(() => JSON.stringify(runPayload, null, 2), [runPayload]);
  const runFingerprint = useMemo(() => hashText(runPayloadText), [runPayloadText]);
  const parameterDiagnostics = useMemo(() => {
    const spread = strategyParameters.entryThreshold - strategyParameters.exitThreshold;
    const roundTripCostBps = (strategyParameters.feeBps * 2) + (strategyParameters.slippageBps * 2);
    const roundTripCost = roundTripCostBps / 10000;
    const breakEvenMove = Math.max(0, roundTripCost);
    const exposurePct = strategyParameters.initialCapital > 0
      ? (strategyParameters.positionSize / strategyParameters.initialCapital) * 100
      : 0;
    const capacity = (strategyParameters.positionSize * strategyParameters.liquidityCapPct) / 100;
    const warnings = [
      spread <= 0 ? 'Entry threshold must stay above exit threshold.' : '',
      spread <= breakEvenMove ? 'Entry/exit spread is tighter than estimated round-trip cost.' : '',
      exposurePct > 20 ? 'Position size uses more than 20% of initial capital.' : '',
      strategyParameters.liquidityCapPct < 5 ? 'Liquidity cap is very low; fills may be sparse.' : '',
      rowCount < 100 ? 'Loaded rows are thin for a stable backtest.' : '',
    ].filter(Boolean);
    const health = warnings.length ? 'review' : 'ready';
    return {
      spread,
      roundTripCostBps,
      breakEvenMove,
      exposurePct,
      capacity,
      health,
      warnings,
    };
  }, [rowCount, strategyParameters]);
  const copied = (message: string) => {
    setCopyNotice(message);
    window.setTimeout(() => setCopyNotice(''), 1800);
  };
  const copyRunPayload = async () => {
    await copyText(runPayloadText);
    copied('Run payload copied');
  };
  const copyStrategyParameters = async () => {
    await copyText(JSON.stringify(strategyParameters, null, 2));
    copied('Strategy parameters copied');
  };
  const savePreset = () => {
    const name = presetDraftName.trim() || `Preset ${savedPresets.length + 1}`;
    const nextPreset = { name, parameters: strategyParameters, savedAt: new Date().toISOString() };
    const nextPresets = [nextPreset, ...savedPresets.filter((preset) => preset.name !== name)].slice(0, 12);
    setSavedPresets(nextPresets);
    persistSavedPresets(nextPresets);
    setParameterPreset(`saved:${name}`);
    copied(`Saved ${name}`);
  };
  const deletePreset = (name: string) => {
    const nextPresets = savedPresets.filter((preset) => preset.name !== name);
    setSavedPresets(nextPresets);
    persistSavedPresets(nextPresets);
    if (parameterPreset === `saved:${name}`) setParameterPreset('Custom live config');
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
    if (preset.startsWith('saved:')) {
      const name = preset.slice('saved:'.length);
      const saved = savedPresets.find((item) => item.name === name);
      if (saved) {
        onStrategyParametersChange(saved.parameters);
        setPresetDraftName(saved.name);
      }
      return;
    }
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
  const recentRunsForDisplay = useMemo(() => {
    const currentRunId = result.runId || 0;
    return recentBacktestRuns.slice(0, 10).map((run) => ({
      ...run,
      isCurrent: Boolean(currentRunId && run.runId === currentRunId),
    }));
  }, [recentBacktestRuns, result.runId]);

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
          <button type="button" onClick={onBatchBacktest}>{batchStatus === 'running' ? 'Batch running' : 'Batch Top 5'}</button>
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
                <button type="button" onClick={onBatchBacktest}>Batch Top 5</button>
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
              <span className={`qtv-parameter-health ${parameterDiagnostics.health}`}>
                {parameterDiagnostics.health === 'ready' ? 'Ready to run' : 'Review parameters'}
              </span>
              <select value={parameterPreset} onChange={(event) => applyPreset(event.currentTarget.value)}>
                <option>Custom live config</option>
                <option>Backend defaults</option>
                <option>Conservative</option>
                <option>Aggressive</option>
                {savedPresets.length ? (
                  <optgroup label="Saved presets">
                    {savedPresets.map((preset) => (
                      <option key={preset.name} value={`saved:${preset.name}`}>{preset.name}</option>
                    ))}
                  </optgroup>
                ) : null}
              </select>
            </header>
            <div className="qtv-parameter-summary">
              <div>
                <span>Signal spread</span>
                <strong>{parameterDiagnostics.spread.toFixed(4)}</strong>
                <em>{strategyParameters.entryThreshold.toFixed(3)} entry / {strategyParameters.exitThreshold.toFixed(3)} exit</em>
              </div>
              <div>
                <span>Round-trip cost</span>
                <strong>{formatNumber(parameterDiagnostics.roundTripCostBps, 2)} bps</strong>
                <em>fee + slippage model</em>
              </div>
              <div>
                <span>Capital at risk</span>
                <strong>{formatPct(parameterDiagnostics.exposurePct, 2)}</strong>
                <em>{formatNumber(strategyParameters.positionSize, 0)} / {formatNumber(strategyParameters.initialCapital, 0)} USDC</em>
              </div>
              <div>
                <span>Fill capacity</span>
                <strong>{formatNumber(parameterDiagnostics.capacity, 0)} USDC</strong>
                <em>{strategyParameters.liquidityCapPct}% liquidity cap</em>
              </div>
              <div>
                <span>Run fingerprint</span>
                <strong>{runFingerprint}</strong>
                <em>{engine} · {dataSource}</em>
              </div>
            </div>
            {parameterDiagnostics.warnings.length ? (
              <div className="qtv-parameter-warnings">
                {parameterDiagnostics.warnings.map((warning) => <span key={warning}>{warning}</span>)}
              </div>
            ) : null}
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
              <button type="button" onClick={copyStrategyParameters}>Copy params</button>
              <button type="button" onClick={onBatchBacktest}>Batch Top 5</button>
              <button className="primary" type="button" onClick={onRefresh}>Run Backtest</button>
            </div>
            <div className="qtv-preset-save-row">
              <input
                value={presetDraftName}
                aria-label="Preset name"
                onInput={(event) => setPresetDraftName(event.currentTarget.value)}
              />
              <button type="button" onClick={savePreset}>Save preset</button>
              <button type="button" onClick={copyRunPayload}>Copy run payload</button>
              {copyNotice ? <span>{copyNotice}</span> : null}
            </div>
            <p>These controls are bound to the real backtest request. Fee bps, slippage bps, and liquidity cap are applied by the execution model; walk-forward controls still need backend support.</p>
          </section>
          <aside className="qtv-run-health">
            <strong>Readiness</strong>
            <span className={marketTitle !== 'No market selected' ? 'ready' : ''}>Market selected</span>
            <span className={rowCount > 0 ? 'ready' : ''}>Price rows loaded</span>
            <span className={engine !== '-' ? 'ready' : ''}>Engine configured</span>
            <span className={strategyParameters.entryThreshold > strategyParameters.exitThreshold ? 'ready' : 'review'}>Entry above exit</span>
            <span className={statusForRisk(parameterDiagnostics.spread > parameterDiagnostics.breakEvenMove)}>Spread covers cost</span>
            <span className={statusForRisk(parameterDiagnostics.exposurePct <= 20)}>Capital risk under 20%</span>
            <div className="qtv-run-snapshot">
              <strong>Latest run snapshot</strong>
              {runSnapshotRows.map(([label, value]) => (
                <div key={label}><span>{label}</span><b>{value}</b></div>
              ))}
            </div>
            <div className="qtv-saved-presets">
              <strong>Saved Presets</strong>
              {savedPresets.length ? savedPresets.slice(0, 5).map((preset) => (
                <div key={`saved-${preset.name}`}>
                  <button type="button" onClick={() => applyPreset(`saved:${preset.name}`)}>{preset.name}</button>
                  <span>{new Date(preset.savedAt).toLocaleDateString()}</span>
                  <button type="button" title={`Delete ${preset.name}`} onClick={() => deletePreset(preset.name)}>Delete</button>
                </div>
              )) : <em>No saved parameter sets yet</em>}
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
              <div><dt>Fingerprint</dt><dd>{runFingerprint}</dd></div>
              <div><dt>Status</dt><dd>{backtestStatus}</dd></div>
              <div><dt>Engine</dt><dd>{engine}</dd></div>
              <div><dt>Rows</dt><dd>{rowCount.toLocaleString('en-US')}</dd></div>
              <div><dt>Trades</dt><dd>{result.trades.length.toLocaleString('en-US')}</dd></div>
              <div><dt>Metrics</dt><dd>{result.metrics.length.toLocaleString('en-US')}</dd></div>
            </dl>
          </section>
          <section className="qtv-run-history-card">
            <div className="qtv-run-config-head">
              <strong>Recent Real Runs</strong>
              <span>{backtestRunsStatus}</span>
            </div>
            {recentRunsForDisplay.length ? (
              <div className="qtv-run-history-table">
                <div className="head">
                  <span>Run</span>
                  <span>Status</span>
                  <span>Market</span>
                  <span>Engine</span>
                  <span>Rows</span>
                  <span>Created</span>
                  <span>Action</span>
                </div>
                {recentRunsForDisplay.map((run) => (
                  <div key={`history-${run.runId}`} className={`${run.status} ${run.isCurrent ? 'current' : ''}`} title={run.error || run.marketSlug}>
                    <span>#{run.runId}{run.isCurrent ? ' current' : ''}</span>
                    <span>{run.status}</span>
                    <span>{run.marketSlug}</span>
                    <span>{run.backtestEngine || '-'}</span>
                    <span>{compactRows(run.rowsProcessed)}</span>
                    <span>{compactRunTime(run.createdAt)}</span>
                    <span>
                      <button type="button" onClick={() => onRunLoad?.(run.runId)}>{run.isCurrent ? 'Reload' : 'Load'}</button>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="qtv-tool-empty">
                <strong>No run history loaded</strong>
                <span>Run a backtest or refresh once the API returns recent quant_backtest_runs.</span>
              </div>
            )}
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
          <section className="qtv-batch-runs-card">
            <div className="qtv-run-config-head">
              <strong>Batch Backtests</strong>
              <button type="button" onClick={onBatchBacktest}>{batchStatus === 'running' ? 'Running...' : 'Run Top 5'}</button>
            </div>
            {batchRows.length ? (
              <div className="qtv-batch-table">
                <div className="head">
                  <span>Outcome</span>
                  <span>Run</span>
                  <span>Status</span>
                  <span>Rows</span>
                  <span>Trades</span>
                  <span>Net</span>
                  <span>Return</span>
                  <span>Drawdown</span>
                </div>
                {batchRows.map((row) => (
                  <div key={row.key} className={row.status === 'failed' ? 'failed' : row.status === 'succeeded' ? 'succeeded' : ''} title={row.error || row.marketSlug}>
                    <span>{row.outcome}</span>
                    <span>{row.runId ? `#${row.runId}` : '-'}</span>
                    <span>{row.status}</span>
                    <span>{row.rows.toLocaleString('en-US')}</span>
                    <span>{row.trades.toLocaleString('en-US')}</span>
                    <span>{row.netProfit}</span>
                    <span>{row.totalReturn}</span>
                    <span>{row.maxDrawdown}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="qtv-tool-empty">
                <strong>No batch runs</strong>
                <span>Run Top 5 to backtest multiple event outcomes with the current strategy parameters.</span>
              </div>
            )}
          </section>
          <section className="qtv-run-config-card">
            <div className="qtv-run-config-head">
              <strong>Reproducibility Snapshot</strong>
              <button type="button" onClick={copyRunPayload}>{copyNotice || 'Copy JSON'}</button>
            </div>
            <dl>
              <div><dt>Market slug</dt><dd>{propertyValue('market slug')}</dd></div>
              <div><dt>Outcome</dt><dd>{propertyValue('outcome')}</dd></div>
              <div><dt>Block range</dt><dd>{propertyValue('from block')} → {propertyValue('to block')}</dd></div>
              <div><dt>Rows processed</dt><dd>{propertyValue('rows processed')}</dd></div>
              <div><dt>Generated</dt><dd>{result.generatedAt || '-'}</dd></div>
            </dl>
            <pre>{runPayloadText}</pre>
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
