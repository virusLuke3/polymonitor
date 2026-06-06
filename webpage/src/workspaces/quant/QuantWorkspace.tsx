import { useEffect, useMemo, useState } from 'preact/hooks';
import {
  fetchQuantBlockClosePrices,
  fetchQuantBuildStatus,
  fetchQuantFrontendPrices,
  type QuantPriceQuery,
} from '@/services/api';
import type { QuantBlockClosePoint, QuantBuildRun, QuantFrontendPricePoint } from '@/types';

type TesterTab = 'overview' | 'performance' | 'trades' | 'properties';
type PriceSource = 'frontend' | 'orderfilled' | 'orderbook' | 'conservative';

type BacktestPricePoint = {
  timestamp: number;
  close: number;
  volume: number;
  source: string;
};

type BacktestSignal = {
  id: string;
  timestamp: number;
  action: 'OPEN' | 'CLOSE' | 'BUY' | 'SELL';
  outcome: 'YES' | 'NO';
  price: number;
  size: number;
  notional: number;
  reason: string;
  tradeId: string;
};

type BacktestTrade = {
  id: string;
  entryTime: string;
  exitTime: string;
  market: string;
  outcome: 'YES' | 'NO';
  side: 'LONG' | 'SHORT';
  entryPrice: number;
  exitPrice: number;
  size: number;
  notional: number;
  pnl: number;
  pnlPct: number;
  holdingTime: string;
  exitReason: string;
};

type EquityPoint = {
  index: number;
  equity: number;
  drawdown: number;
  drawdownPct: number;
};

const MOCK_PRICES: BacktestPricePoint[] = Array.from({ length: 96 }, (_, index) => {
  const wave = Math.sin(index / 7) * 0.035 + Math.cos(index / 13) * 0.018;
  const shock = index > 42 && index < 54 ? -0.12 + (index - 42) * 0.01 : 0;
  const drift = index * 0.0009;
  return {
    timestamp: 1_717_584_000 + index * 300,
    close: Math.max(0.08, Math.min(0.92, 0.49 + wave + shock + drift)),
    volume: 1200 + Math.round(Math.abs(Math.sin(index / 5)) * 4200),
    source: 'mock',
  };
});

function mockTs(index: number) {
  return MOCK_PRICES[index]?.timestamp || MOCK_PRICES[0]?.timestamp || 0;
}

const MOCK_SIGNALS: BacktestSignal[] = [
  { id: 's1', timestamp: mockTs(12), action: 'OPEN', outcome: 'YES', price: 0.48, size: 240, notional: 115.2, reason: 'Momentum breakout', tradeId: 'T-118' },
  { id: 's2', timestamp: mockTs(25), action: 'CLOSE', outcome: 'YES', price: 0.57, size: 240, notional: 136.8, reason: 'Target reached', tradeId: 'T-118' },
  { id: 's3', timestamp: mockTs(47), action: 'SELL', outcome: 'NO', price: 0.62, size: 180, notional: 111.6, reason: 'Breakdown confirmation', tradeId: 'T-119' },
  { id: 's4', timestamp: mockTs(61), action: 'CLOSE', outcome: 'NO', price: 0.54, size: 180, notional: 97.2, reason: 'Trailing stop', tradeId: 'T-119' },
  { id: 's5', timestamp: mockTs(75), action: 'OPEN', outcome: 'YES', price: 0.51, size: 320, notional: 163.2, reason: 'Mean reversion', tradeId: 'T-120' },
];

const MOCK_TRADES: BacktestTrade[] = [
  { id: 'T-118', entryTime: '2026-06-05 12:31', exitTime: '2026-06-05 13:36', market: 'Will Team A win?', outcome: 'YES', side: 'LONG', entryPrice: 0.48, exitPrice: 0.57, size: 240, notional: 115.2, pnl: 21.6, pnlPct: 18.75, holdingTime: '1h 05m', exitReason: 'Target reached' },
  { id: 'T-119', entryTime: '2026-06-05 15:26', exitTime: '2026-06-05 16:36', market: 'Will Team A win?', outcome: 'NO', side: 'SHORT', entryPrice: 0.62, exitPrice: 0.54, size: 180, notional: 111.6, pnl: 14.4, pnlPct: 12.9, holdingTime: '1h 10m', exitReason: 'Trailing stop' },
  { id: 'T-120', entryTime: '2026-06-05 17:46', exitTime: '2026-06-05 18:41', market: 'Will Team A win?', outcome: 'YES', side: 'LONG', entryPrice: 0.51, exitPrice: 0.47, size: 320, notional: 163.2, pnl: -12.8, pnlPct: -7.84, holdingTime: '55m', exitReason: 'Stop loss' },
  { id: 'T-121', entryTime: '2026-06-05 19:06', exitTime: '2026-06-05 20:11', market: 'Will Team B qualify?', outcome: 'YES', side: 'LONG', entryPrice: 0.37, exitPrice: 0.43, size: 410, notional: 151.7, pnl: 24.6, pnlPct: 16.22, holdingTime: '1h 05m', exitReason: 'Resolution risk filter' },
];

const MOCK_EQUITY: EquityPoint[] = Array.from({ length: 120 }, (_, index) => {
  const equity = 100_000 + index * 145 + Math.sin(index / 6) * 980 - (index > 62 && index < 82 ? (82 - Math.abs(index - 72)) * 190 : 0);
  const peak = 100_000 + index * 170 + 900;
  const drawdown = Math.min(0, equity - peak);
  return { index: index + 1, equity, drawdown, drawdownPct: (drawdown / peak) * 100 };
});

const PERFORMANCE_ROWS = [
  ['Net Profit', '+4,782.40 USDC', '+4,128.10', '+654.30', 'Closed and realized strategy return'],
  ['Gross Profit', '7,914.20 USDC', '6,420.90', '1,493.30', 'Sum of profitable trades'],
  ['Gross Loss', '-3,131.80 USDC', '-2,292.80', '-839.00', 'Sum of losing trades'],
  ['Max Drawdown', '-3,754.52 USDC', '-2,980.10', '-774.42', 'Largest equity peak-to-trough loss'],
  ['Sharpe Ratio', '1.41', '1.55', '0.92', 'Risk-adjusted return'],
  ['Profit Factor', '1.198', '1.31', '1.08', 'Gross profit divided by gross loss'],
  ['Percent Profitable', '35.55%', '39.10%', '30.20%', 'Winning closed trades share'],
  ['Avg Bars in Trades', '5', '5', '4', 'Average holding period in chart bars'],
];

const PROPERTY_GROUPS = [
  ['Strategy Parameters', ['Entry threshold 0.58', 'Exit threshold 0.44', 'Stop loss 7.5%', 'Take profit 16%', 'Max holding time 8h', 'Position sizing risk-weighted']],
  ['Backtest Assumptions', ['Initial capital 100,000 USDC', 'Commission 0.00%', 'Slippage 0.4%', 'Fill model block close', 'Time range selected market history']],
  ['Market Data', ['Source frontend / OrderFilled', 'Resolution 1m or block_number', 'Missing prices forward fill', 'Settlement PnL enabled']],
];

function toNumber(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function fmtPrice(value: unknown) {
  return toNumber(value).toFixed(3);
}

function fmtCurrency(value: unknown) {
  const numeric = toNumber(value);
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${numeric.toLocaleString('en-US', { maximumFractionDigits: 2 })} USDC`;
}

function statusClass(value: number) {
  if (value > 0) return 'positive';
  if (value < 0) return 'negative';
  return 'neutral';
}

function frontendToPrices(rows: QuantFrontendPricePoint[]): BacktestPricePoint[] {
  return rows.map((row) => ({
    timestamp: Number(row.timestamp),
    close: toNumber(row.price),
    volume: 0,
    source: 'frontend',
  })).filter((row) => row.timestamp && row.close);
}

function blockToPrices(rows: QuantBlockClosePoint[]): BacktestPricePoint[] {
  return rows.map((row) => ({
    timestamp: Number(row.blockNumber),
    close: toNumber(row.closePrice),
    volume: toNumber(row.volume),
    source: 'orderfilled_block_close',
  })).filter((row) => row.timestamp && row.close);
}

function buildPath(points: Array<{ x: number; y: number }>, width: number, height: number, padding: number, yMin: number, yMax: number) {
  const xMin = Math.min(...points.map((point) => point.x), 0);
  const xMax = Math.max(...points.map((point) => point.x), 1);
  const xSpan = Math.max(1, xMax - xMin);
  const ySpan = Math.max(0.001, yMax - yMin);
  return points.map((point, index) => {
    const x = padding + ((point.x - xMin) / xSpan) * (width - padding * 2);
    const y = height - padding - ((point.y - yMin) / ySpan) * (height - padding * 2);
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(' ');
}

function PriceChartPanel({
  prices,
  selectedTradeId,
}: {
  prices: BacktestPricePoint[];
  selectedTradeId: string | null;
}) {
  const width = 1100;
  const height = 420;
  const padding = 34;
  const points = prices.length ? prices : MOCK_PRICES;
  const chartPoints = points.map((point) => ({ x: point.timestamp, y: point.close }));
  const pricePath = buildPath(chartPoints, width, height, padding, 0, 1);
  const xMin = Math.min(...chartPoints.map((point) => point.x));
  const xMax = Math.max(...chartPoints.map((point) => point.x));
  const xSpan = Math.max(1, xMax - xMin);
  const firstPoint = points[0] || MOCK_PRICES[0] || { timestamp: 0, close: 0, volume: 0, source: 'empty' };
  const markerSignals = MOCK_SIGNALS.map((signal) => {
    const nearest = points.reduce((best, point) => (
      Math.abs(point.timestamp - signal.timestamp) < Math.abs(best.timestamp - signal.timestamp) ? point : best
    ), firstPoint);
    return {
      ...signal,
      x: padding + ((nearest.timestamp - xMin) / xSpan) * (width - padding * 2),
      y: height - padding - nearest.close * (height - padding * 2),
    };
  });

  return (
    <section className="qb-chart-area">
      <div className="qb-chart-head">
        <div>
          <div className="qb-market-title">Will Team A win?</div>
          <div className="qb-market-meta">
            <span>Sports</span>
            <span>YES {fmtPrice(points[points.length - 1]?.close || 0.614)}</span>
            <span className="positive">+0.012 / +1.9%</span>
          </div>
        </div>
        <div className="qb-symbol-strip">
          <span>condition 0x8f...41c</span>
          <span>liquidity 284.2K</span>
          <span>resolved pending</span>
        </div>
      </div>
      <svg className="qb-price-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Prediction market probability chart">
        {Array.from({ length: 9 }, (_, index) => <line key={`h-${index}`} x1={padding} x2={width - padding} y1={padding + index * 43} y2={padding + index * 43} />)}
        {Array.from({ length: 12 }, (_, index) => <line key={`v-${index}`} y1={padding} y2={height - padding} x1={padding + index * 86} x2={padding + index * 86} />)}
        <path className="qb-price-line" d={pricePath} />
        <path className="qb-ma-line" d={buildPath(chartPoints.filter((_, index) => index % 2 === 0), width, height, padding, 0, 1)} />
        <line className="qb-resolution-line" x1={width * 0.78} x2={width * 0.78} y1={padding} y2={height - padding} />
        <text className="qb-axis-label" x={width - 62} y={padding + 8}>1.00</text>
        <text className="qb-axis-label" x={width - 62} y={height - padding}>0.00</text>
        {markerSignals.map((signal) => (
          <g key={signal.id} className={`qb-signal ${signal.action === 'OPEN' || signal.action === 'BUY' ? 'open' : 'close'} ${selectedTradeId === signal.tradeId ? 'selected' : ''}`}>
            <title>{`Action: ${signal.action} ${signal.outcome}\nPrice: ${signal.price}\nSize: ${signal.size} shares\nNotional: ${signal.notional} USDC\nReason: ${signal.reason}`}</title>
            <path d={signal.action === 'OPEN' || signal.action === 'BUY' ? `M ${signal.x} ${signal.y - 24} l 7 11 h -14 z` : `M ${signal.x} ${signal.y + 24} l 7 -11 h -14 z`} />
            <rect x={signal.x - 26} y={signal.action === 'OPEN' || signal.action === 'BUY' ? signal.y - 49 : signal.y + 27} width="52" height="22" rx="4" />
            <text x={signal.x} y={signal.action === 'OPEN' || signal.action === 'BUY' ? signal.y - 34 : signal.y + 42}>{signal.action === 'SELL' ? 'Sell' : signal.action}</text>
          </g>
        ))}
      </svg>
      <div className="qb-chart-footer">
        {['1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', 'All'].map((item) => <button key={item} type="button">{item}</button>)}
        <span>UTC</span>
      </div>
    </section>
  );
}

function EquityDrawdownChart({ points }: { points: EquityPoint[] }) {
  const width = 1100;
  const height = 230;
  const padding = 32;
  const equityPoints = points.map((point) => ({ x: point.index, y: point.equity }));
  const drawdownPoints = points.map((point) => ({ x: point.index, y: point.drawdown }));
  const equityMin = Math.min(...equityPoints.map((point) => point.y));
  const equityMax = Math.max(...equityPoints.map((point) => point.y));
  const equityPath = buildPath(equityPoints, width, height, padding, equityMin, equityMax);
  const drawdownPath = buildPath(drawdownPoints, width, height, padding, -5000, 0);
  return (
    <svg className="qb-equity-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Equity and drawdown curve">
      {Array.from({ length: 6 }, (_, index) => <line key={index} x1={padding} x2={width - padding} y1={padding + index * 34} y2={padding + index * 34} />)}
      <path className="qb-drawdown-fill" d={`${drawdownPath} L ${width - padding} ${padding} L ${padding} ${padding} Z`} />
      <path className="qb-equity-fill" d={`${equityPath} L ${width - padding} ${height - padding} L ${padding} ${height - padding} Z`} />
      <path className="qb-equity-line" d={equityPath} />
      <path className="qb-drawdown-line" d={drawdownPath} />
    </svg>
  );
}

function MetricCard({ name, value, delta, status, tooltip }: { name: string; value: string; delta: string; status: 'positive' | 'negative' | 'neutral'; tooltip: string }) {
  return (
    <div className="qb-metric" title={tooltip}>
      <span>{name}</span>
      <strong className={status}>{value}</strong>
      <em className={status}>{delta}</em>
    </div>
  );
}

export function QuantWorkspace() {
  const [frontendRows, setFrontendRows] = useState<QuantFrontendPricePoint[]>([]);
  const [blockRows, setBlockRows] = useState<QuantBlockClosePoint[]>([]);
  const [runs, setRuns] = useState<QuantBuildRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [timeframe, setTimeframe] = useState('5m');
  const [priceSource, setPriceSource] = useState<PriceSource>('frontend');
  const [testerTab, setTesterTab] = useState<TesterTab>('overview');
  const [deepBacktest, setDeepBacktest] = useState(false);
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>('T-118');
  const [marketSlug, setMarketSlug] = useState('');

  const activePrices = useMemo(() => {
    if (priceSource === 'orderfilled') return blockToPrices(blockRows);
    if (priceSource === 'frontend') return frontendToPrices(frontendRows);
    return [];
  }, [blockRows, frontendRows, priceSource]);
  const renderedPrices = activePrices.length ? activePrices : MOCK_PRICES;
  const latestPrice = renderedPrices[renderedPrices.length - 1]?.close || 0;
  const netPnl = MOCK_TRADES.reduce((sum, trade) => sum + trade.pnl, 0);
  const query: QuantPriceQuery = { marketSlug, tokenSide: 'YES', limit: 360 };

  const loadQuantData = async () => {
    setLoading(true);
    setError('');
    const [frontendResult, blockResult, statusResult] = await Promise.allSettled([
      fetchQuantFrontendPrices(query),
      fetchQuantBlockClosePrices(query),
      fetchQuantBuildStatus('', 12),
    ]);
    if (frontendResult.status === 'fulfilled') setFrontendRows(frontendResult.value.items || []);
    if (blockResult.status === 'fulfilled') setBlockRows(blockResult.value.items || []);
    if (statusResult.status === 'fulfilled') setRuns(statusResult.value.items || []);
    const rejected = [frontendResult, blockResult, statusResult].find((result) => result.status === 'rejected');
    if (rejected?.status === 'rejected') {
      setError(rejected.reason instanceof Error ? rejected.reason.message : 'Quant API unavailable');
    }
    setLoading(false);
  };

  useEffect(() => {
    void loadQuantData();
  }, []);

  return (
    <div className="qb-shell">
      <header className="qb-topbar">
        <div className="qb-brand">
          <a href="/">POLYDATA</a>
          <span>Strategy Tester Workspace</span>
        </div>
        <div className="qb-timeframes">
          {['1m', '5m', '15m', '1h', '4h', '1d'].map((item) => (
            <button key={item} className={timeframe === item ? 'active' : ''} type="button" onClick={() => setTimeframe(item)}>{item}</button>
          ))}
        </div>
        <div className="qb-actions">
          <select value={priceSource} onChange={(event) => setPriceSource(event.currentTarget.value as PriceSource)}>
            <option value="frontend">Frontend price-history</option>
            <option value="orderfilled">OrderFilled block close</option>
            <option value="orderbook">Orderbook mid</option>
            <option value="conservative">Conservative bid/ask</option>
          </select>
          <input value={marketSlug} onInput={(event) => setMarketSlug(event.currentTarget.value)} placeholder="market_slug" />
          <button className="primary" type="button" onClick={() => void loadQuantData()}>{loading ? 'Running...' : 'Run Backtest'}</button>
        </div>
      </header>

      {error ? <div className="qb-error">{error}</div> : null}

      <main className="qb-workspace">
        <PriceChartPanel prices={renderedPrices} selectedTradeId={selectedTradeId} />

        <section className="qb-bottom">
          <nav className="qb-tool-tabs" aria-label="Backtest tools">
            {['Market Screener', 'Strategy Editor', 'Strategy Tester', 'Replay', 'Trading Panel'].map((item) => (
              <button key={item} className={item === 'Strategy Tester' ? 'active' : ''} type="button">{item}</button>
            ))}
            <span className="qb-powered">PolyData</span>
          </nav>

          <div className="qb-tester-head">
            <div>
              <strong>Momentum Probability Strategy</strong>
              <button type="button" title="Strategy settings">⚙</button>
              <button type="button" onClick={() => void loadQuantData()} title="Refresh strategy data">↻</button>
            </div>
            <div className="qb-tester-actions">
              <label><input type="checkbox" checked /> Backtest mode</label>
              <label><input type="checkbox" checked={deepBacktest} onChange={() => setDeepBacktest((current) => !current)} /> Deep Backtest</label>
              <button type="button">Export</button>
            </div>
          </div>

          <nav className="qb-subtabs" aria-label="Strategy tester tabs">
            {[
              ['overview', 'Overview'],
              ['performance', 'Performance Summary'],
              ['trades', 'List of Trades'],
              ['properties', 'Properties'],
            ].map(([id, label]) => (
              <button key={id} className={testerTab === id ? 'active' : ''} type="button" onClick={() => setTesterTab(id as TesterTab)}>{label}</button>
            ))}
          </nav>

          {testerTab === 'overview' ? (
            <>
              <div className="qb-metrics-row">
                <MetricCard name="Net Profit" value={fmtCurrency(netPnl)} delta="+4.79%" status={statusClass(netPnl)} tooltip="Closed realized strategy PnL" />
                <MetricCard name="Total Return" value="+4.78%" delta="+0.42 beta adj" status="positive" tooltip="Return on initial capital" />
                <MetricCard name="Max Drawdown" value="-3,754.52 USDC" delta="-3.45%" status="negative" tooltip="Largest peak-to-trough equity loss" />
                <MetricCard name="Win Rate" value="35.55%" delta="878 / 2,470" status="positive" tooltip="Percent profitable closed trades" />
                <MetricCard name="Profit Factor" value="1.198" delta="gross P/L" status="neutral" tooltip="Gross profit divided by gross loss" />
                <MetricCard name="Total Trades" value="2,470" delta={`${runs.length} runs`} status="neutral" tooltip="Closed strategy trades" />
                <MetricCard name="Avg Trade" value="7.77 USDC" delta="+0.01%" status="positive" tooltip="Average closed trade PnL" />
                <MetricCard name="Avg Holding" value="5 bars" delta={timeframe} status="neutral" tooltip="Average bars held per trade" />
              </div>
              <div className="qb-equity-wrap">
                <EquityDrawdownChart points={MOCK_EQUITY} />
              </div>
            </>
          ) : null}

          {testerTab === 'performance' ? (
            <div className="qb-table-wrap">
              <table className="qb-table">
                <thead><tr><th>Metric</th><th>All Trades</th><th>Long / YES</th><th>Short / NO</th><th>Description</th></tr></thead>
                <tbody>{PERFORMANCE_ROWS.map((row) => <tr key={row[0]}>{row.map((cell) => <td key={cell}>{cell}</td>)}</tr>)}</tbody>
              </table>
            </div>
          ) : null}

          {testerTab === 'trades' ? (
            <div className="qb-table-wrap">
              <div className="qb-filter-strip">
                {['Profitable only', 'Losing only', 'YES only', 'NO only', 'Long holding', 'Short holding'].map((item) => <button key={item} type="button">{item}</button>)}
              </div>
              <table className="qb-table">
                <thead><tr><th>Trade #</th><th>Entry Time</th><th>Exit Time</th><th>Market</th><th>Outcome</th><th>Side</th><th>Entry</th><th>Exit</th><th>Size</th><th>Notional</th><th>PnL</th><th>PnL %</th><th>Holding</th><th>Exit Reason</th></tr></thead>
                <tbody>
                  {MOCK_TRADES.map((trade) => (
                    <tr key={trade.id} className={selectedTradeId === trade.id ? 'selected' : ''} onClick={() => setSelectedTradeId(trade.id)}>
                      <td>{trade.id}</td><td>{trade.entryTime}</td><td>{trade.exitTime}</td><td>{trade.market}</td><td>{trade.outcome}</td><td>{trade.side}</td><td>{fmtPrice(trade.entryPrice)}</td><td>{fmtPrice(trade.exitPrice)}</td><td>{trade.size}</td><td>{fmtCurrency(trade.notional)}</td><td className={statusClass(trade.pnl)}>{fmtCurrency(trade.pnl)}</td><td className={statusClass(trade.pnlPct)}>{trade.pnlPct.toFixed(2)}%</td><td>{trade.holdingTime}</td><td>{trade.exitReason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {testerTab === 'properties' ? (
            <div className="qb-properties">
              {PROPERTY_GROUPS.map(([group, values]) => (
                <section key={group}>
                  <h3>{group}</h3>
                  {(values as string[]).map((value) => <div key={value}><span>{value.split(' ')[0]}</span><strong>{value}</strong></div>)}
                </section>
              ))}
            </div>
          ) : null}
        </section>
      </main>
      <div className="qb-statusbar">
        <span>source {priceSource}</span>
        <span>latest YES {fmtPrice(latestPrice)}</span>
        <span>frontend rows {frontendRows.length}</span>
        <span>block close rows {blockRows.length}</span>
      </div>
    </div>
  );
}
