import { useEffect, useMemo, useState } from 'preact/hooks';
import {
  fetchQuantBlockClosePrices,
  fetchQuantBuildStatus,
  fetchQuantFrontendPrices,
  type QuantPriceQuery,
} from '@/services/api';
import type { QuantBlockClosePoint, QuantBuildRun, QuantFrontendPricePoint } from '@/types';

type QuantSource = 'frontend' | 'block';

type ChartPoint = {
  x: number;
  y: number;
  label: string;
};

function toNumber(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatPrice(value: unknown) {
  const numeric = toNumber(value);
  if (!numeric) return '0.0000';
  return numeric.toFixed(4);
}

function formatCompact(value: unknown) {
  const numeric = toNumber(value);
  if (Math.abs(numeric) >= 1_000_000) return `${(numeric / 1_000_000).toFixed(1)}M`;
  if (Math.abs(numeric) >= 1_000) return `${(numeric / 1_000).toFixed(1)}K`;
  return numeric.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

function shortToken(value?: string | null) {
  const text = String(value || '');
  if (text.length <= 14) return text || '-';
  return `${text.slice(0, 6)}...${text.slice(-6)}`;
}

function buildFrontendChart(rows: QuantFrontendPricePoint[]) {
  return rows.map((row) => ({
    x: Number(row.timestamp),
    y: toNumber(row.price),
    label: row.tsMinute || String(row.timestamp),
  }));
}

function buildBlockChart(rows: QuantBlockClosePoint[]) {
  return rows.map((row) => ({
    x: Number(row.blockNumber),
    y: toNumber(row.closePrice),
    label: String(row.blockNumber),
  }));
}

function QuantLineChart({ points, xLabel }: { points: ChartPoint[]; xLabel: string }) {
  const width = 920;
  const height = 280;
  const padding = 28;
  const clean = points.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  const xValues = clean.map((point) => point.x);
  const yValues = clean.map((point) => point.y);
  const minX = Math.min(...xValues, 0);
  const maxX = Math.max(...xValues, 1);
  const minY = Math.min(...yValues, 0);
  const maxY = Math.max(...yValues, 1);
  const xSpan = Math.max(1, maxX - minX);
  const ySpan = Math.max(0.01, maxY - minY);
  const path = clean
    .map((point, index) => {
      const x = padding + ((point.x - minX) / xSpan) * (width - padding * 2);
      const y = height - padding - ((point.y - minY) / ySpan) * (height - padding * 2);
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
  const last = clean[clean.length - 1];

  return (
    <div className="qm-chart-shell">
      <svg className="qm-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${xLabel} price chart`}>
        <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} />
        <line x1={padding} y1={padding} x2={padding} y2={height - padding} />
        <text x={padding} y={20}>{maxY.toFixed(2)}</text>
        <text x={padding} y={height - 8}>{minY.toFixed(2)}</text>
        {path ? <path d={path} /> : null}
        {last ? (
          <circle
            cx={padding + ((last.x - minX) / xSpan) * (width - padding * 2)}
            cy={height - padding - ((last.y - minY) / ySpan) * (height - padding * 2)}
            r="4"
          />
        ) : null}
      </svg>
      <div className="qm-chart-axis">
        <span>{clean[0]?.label || xLabel}</span>
        <strong>{xLabel}</strong>
        <span>{last?.label || xLabel}</span>
      </div>
    </div>
  );
}

function QuantMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="qm-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function QuantWorkspace() {
  const [source, setSource] = useState<QuantSource>('frontend');
  const [marketSlug, setMarketSlug] = useState('');
  const [tokenSide, setTokenSide] = useState('YES');
  const [tokenId, setTokenId] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [fromBlock, setFromBlock] = useState('');
  const [toBlock, setToBlock] = useState('');
  const [frontendRows, setFrontendRows] = useState<QuantFrontendPricePoint[]>([]);
  const [blockRows, setBlockRows] = useState<QuantBlockClosePoint[]>([]);
  const [runs, setRuns] = useState<QuantBuildRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const activeRows = source === 'frontend' ? frontendRows : blockRows;
  const chartPoints = useMemo(
    () => (source === 'frontend' ? buildFrontendChart(frontendRows) : buildBlockChart(blockRows)),
    [blockRows, frontendRows, source],
  );
  const latestPrice = source === 'frontend'
    ? formatPrice(frontendRows[frontendRows.length - 1]?.price)
    : formatPrice(blockRows[blockRows.length - 1]?.closePrice);
  const latestX = source === 'frontend'
    ? (frontendRows[frontendRows.length - 1]?.tsMinute || '-')
    : (blockRows[blockRows.length - 1]?.blockNumber || '-');
  const rowsWritten = runs.reduce((sum, run) => sum + toNumber(run.rowsWritten), 0);

  const loadQuantData = async () => {
    setLoading(true);
    setError('');
    const query: QuantPriceQuery = {
      marketSlug,
      tokenSide,
      tokenId,
      from,
      to,
      fromBlock,
      toBlock,
      limit: 360,
    };
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
    let cancelled = false;
    setLoading(true);
    Promise.allSettled([
      fetchQuantFrontendPrices({ tokenSide: 'YES', limit: 180 }),
      fetchQuantBlockClosePrices({ tokenSide: 'YES', limit: 180 }),
      fetchQuantBuildStatus('', 12),
    ]).then(([frontendResult, blockResult, statusResult]) => {
      if (cancelled) return;
      if (frontendResult.status === 'fulfilled') setFrontendRows(frontendResult.value.items || []);
      if (blockResult.status === 'fulfilled') setBlockRows(blockResult.value.items || []);
      if (statusResult.status === 'fulfilled') setRuns(statusResult.value.items || []);
      const rejected = [frontendResult, blockResult, statusResult].find((result) => result.status === 'rejected');
      if (rejected?.status === 'rejected') {
        setError(rejected.reason instanceof Error ? rejected.reason.message : 'Quant API unavailable');
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="wm-shell qm-shell">
      <div className="wm-promo">
        <span className="wm-pro-badge">QUANT</span>
        <span className="wm-promo-copy">frontend time series and OrderFilled block close prices are separated at the API boundary.</span>
        <a className="wm-promo-cta qm-back-link" href="/">Open monitor</a>
      </div>

      <header className="wm-toolbar qm-toolbar">
        <div className="wm-toolbar-left">
          <a className="qm-brand-mark" href="/">POLYDATA</a>
          <div className="wm-brand">QUANT PRICE SERVICE <span>v0.1</span></div>
          <div className="wm-live-dot">Read API</div>
        </div>
        <nav className="wm-site-nav" aria-label="quant resources">
          <a href="/blog/">Blog</a>
          <a href="/docs/documentation/">Docs</a>
          <a href="https://arxiv.org/pdf/2604.20421" target="_blank" rel="noopener noreferrer">Paper</a>
          <a href="https://github.com/virusLuke3/polymonitor" target="_blank" rel="noopener noreferrer">GitHub</a>
          <a className="active" href="/quant">Quant</a>
        </nav>
        <div className="wm-toolbar-right">
          <button className="wm-tool-button" type="button" onClick={() => void loadQuantData()}>{loading ? 'Loading' : 'Refresh'}</button>
        </div>
      </header>

      <main className="qm-main">
        <section className="qm-header-band">
          <div>
            <span className="wm-map-kicker">Production Quant Data</span>
            <h1>Price Build Workbench</h1>
          </div>
          <div className="qm-source-toggle" aria-label="Quant source">
            <button className={source === 'frontend' ? 'active' : ''} type="button" onClick={() => setSource('frontend')}>frontend</button>
            <button className={source === 'block' ? 'active' : ''} type="button" onClick={() => setSource('block')}>block close</button>
          </div>
        </section>

        <form
          className="qm-query-bar"
          onSubmit={(event) => {
            event.preventDefault();
            void loadQuantData();
          }}
        >
          <label>
            <span>market_slug</span>
            <input value={marketSlug} onInput={(event) => setMarketSlug(event.currentTarget.value)} />
          </label>
          <label>
            <span>token_side</span>
            <select value={tokenSide} onChange={(event) => setTokenSide(event.currentTarget.value)}>
              <option value="">ALL</option>
              <option value="YES">YES</option>
              <option value="NO">NO</option>
            </select>
          </label>
          <label>
            <span>token_id</span>
            <input value={tokenId} onInput={(event) => setTokenId(event.currentTarget.value)} />
          </label>
          {source === 'frontend' ? (
            <>
              <label>
                <span>from</span>
                <input value={from} onInput={(event) => setFrom(event.currentTarget.value)} placeholder="ISO or unix" />
              </label>
              <label>
                <span>to</span>
                <input value={to} onInput={(event) => setTo(event.currentTarget.value)} placeholder="ISO or unix" />
              </label>
            </>
          ) : (
            <>
              <label>
                <span>from_block</span>
                <input value={fromBlock} onInput={(event) => setFromBlock(event.currentTarget.value)} inputMode="numeric" />
              </label>
              <label>
                <span>to_block</span>
                <input value={toBlock} onInput={(event) => setToBlock(event.currentTarget.value)} inputMode="numeric" />
              </label>
            </>
          )}
          <button type="submit">Run</button>
        </form>

        {error ? <div className="qm-error">{error}</div> : null}

        <section className="qm-metrics">
          <QuantMetric label="source" value={source === 'frontend' ? 'frontend' : 'orderfilled_block_close'} />
          <QuantMetric label="rows" value={formatCompact(activeRows.length)} />
          <QuantMetric label={source === 'frontend' ? 'latest ts_minute' : 'latest block'} value={String(latestX)} />
          <QuantMetric label="latest price" value={latestPrice} />
          <QuantMetric label="run rows" value={formatCompact(rowsWritten)} />
        </section>

        <section className="qm-grid">
          <div className="qm-panel qm-chart-panel">
            <div className="qm-panel-title">
              <span>{source === 'frontend' ? 'FRONTEND PRICE 1M' : 'ORDERFILLED BLOCK CLOSE'}</span>
              <em>{loading ? 'SYNCING' : 'READY'}</em>
            </div>
            <QuantLineChart points={chartPoints} xLabel={source === 'frontend' ? 'ts_minute' : 'block_number'} />
          </div>

          <div className="qm-panel">
            <div className="qm-panel-title">
              <span>BUILD RUNS</span>
              <em>{runs.length}</em>
            </div>
            <div className="qm-run-list">
              {runs.length ? runs.map((run) => (
                <div className="qm-run-row" key={run.runId}>
                  <strong>{run.source}</strong>
                  <span>{run.status}</span>
                  <em>{formatCompact(run.rowsWritten)}</em>
                </div>
              )) : <div className="qm-empty">No build runs</div>}
            </div>
          </div>
        </section>

        <section className="qm-panel qm-table-panel">
          <div className="qm-panel-title">
            <span>{source === 'frontend' ? 'frontend rows' : 'block close rows'}</span>
            <em>{activeRows.length}</em>
          </div>
          <div className="qm-table-wrap">
            <table className="qm-table">
              <thead>
                <tr>
                  <th>market</th>
                  <th>side</th>
                  <th>token</th>
                  <th>{source === 'frontend' ? 'ts_minute' : 'block'}</th>
                  <th>price</th>
                  <th>{source === 'frontend' ? 'timestamp' : 'trades'}</th>
                </tr>
              </thead>
              <tbody>
                {source === 'frontend'
                  ? frontendRows.slice(-160).map((row) => (
                    <tr key={`${row.tokenId}:${row.timestamp}`}>
                      <td>{row.marketSlug || row.marketId}</td>
                      <td>{row.tokenSide}</td>
                      <td>{shortToken(row.tokenId)}</td>
                      <td>{row.tsMinute || '-'}</td>
                      <td>{formatPrice(row.price)}</td>
                      <td>{row.timestamp}</td>
                    </tr>
                  ))
                  : blockRows.slice(-160).map((row) => (
                    <tr key={`${row.tokenId}:${row.blockNumber}`}>
                      <td>{row.marketSlug || row.marketId}</td>
                      <td>{row.tokenSide}</td>
                      <td>{shortToken(row.tokenId)}</td>
                      <td>{row.blockNumber}</td>
                      <td>{formatPrice(row.closePrice)}</td>
                      <td>{formatCompact(row.tradeCount)}</td>
                    </tr>
                  ))}
                {!activeRows.length ? (
                  <tr>
                    <td colSpan={6}>No rows</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
