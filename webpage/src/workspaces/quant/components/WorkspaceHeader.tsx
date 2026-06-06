import type { PriceSource } from '../types';

type WorkspaceHeaderProps = {
  marketSlug: string;
  timeframe: string;
  priceSource: PriceSource;
  loading: boolean;
  onMarketSlugChange: (value: string) => void;
  onTimeframeChange: (value: string) => void;
  onPriceSourceChange: (value: PriceSource) => void;
  onRunBacktest: () => void;
  onExport: (format: 'csv' | 'json') => void;
};

export function WorkspaceHeader({
  marketSlug,
  timeframe,
  priceSource,
  loading,
  onMarketSlugChange,
  onTimeframeChange,
  onPriceSourceChange,
  onRunBacktest,
  onExport,
}: WorkspaceHeaderProps) {
  return (
    <header className="qtv-topbar">
      <div className="qtv-left-tools">
        <a className="qtv-logo" href="/">POLYDATA</a>
        <button type="button" title="Menu">Menu</button>
        <label className="qtv-symbol-search">
          <span>Search</span>
          <input value={marketSlug} onInput={(event) => onMarketSlugChange(event.currentTarget.value)} placeholder="market_slug" />
        </label>
        <button type="button" title="Add market">+</button>
        <div className="qtv-timeframes">
          {['1m', '5m', '15m', '1h', '4h', '1d'].map((item) => (
            <button key={item} className={timeframe === item ? 'active' : ''} type="button" onClick={() => onTimeframeChange(item)}>{item}</button>
          ))}
        </div>
        <button type="button" title="Candles">Candles</button>
        <button type="button" title="Indicators">Indicators</button>
        <button type="button" title="Compare">Layout</button>
        <button type="button" title="Undo">Undo</button>
      </div>

      <div className="qtv-right-tools">
        <select value={priceSource} onChange={(event) => onPriceSourceChange(event.currentTarget.value as PriceSource)}>
          <option value="frontend">Frontend price-history</option>
          <option value="orderfilled">OrderFilled block close</option>
          <option value="orderbook">Orderbook mid</option>
          <option value="conservative">Conservative bid/ask</option>
        </select>
        <button type="button">Save</button>
        <button type="button" onClick={() => onExport('json')}>Snapshot</button>
        <button type="button" onClick={() => onExport('csv')}>CSV</button>
        <button className="primary" type="button" onClick={onRunBacktest}>{loading ? 'Running...' : 'Run Backtest'}</button>
      </div>
    </header>
  );
}
