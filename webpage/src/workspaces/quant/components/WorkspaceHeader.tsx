import type { QuantPriceMarket } from '@/types';
import type { BacktestEngine, PriceSource } from '../types';

type WorkspaceHeaderProps = {
  marketSlug: string;
  timeframe: string;
  priceSource: PriceSource;
  backtestEngine: BacktestEngine;
  loading: boolean;
  marketOptions: QuantPriceMarket[];
  onMarketSlugChange: (value: string) => void;
  onTimeframeChange: (value: string) => void;
  onPriceSourceChange: (value: PriceSource) => void;
  onBacktestEngineChange: (value: BacktestEngine) => void;
  onRunBacktest: () => void;
  onExport: (format: 'csv' | 'json') => void;
};

export function WorkspaceHeader({
  marketSlug,
  timeframe,
  priceSource,
  backtestEngine,
  loading,
  marketOptions,
  onMarketSlugChange,
  onTimeframeChange,
  onPriceSourceChange,
  onBacktestEngineChange,
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
          <input
            value={marketSlug}
            list="qtv-market-slugs"
            onInput={(event) => onMarketSlugChange(event.currentTarget.value)}
            placeholder="market_slug"
          />
        </label>
        <datalist id="qtv-market-slugs">
          {marketOptions.map((market) => (
            <option key={`${market.marketSlug}-${market.tokenSide}`} value={market.marketSlug}>
              {market.marketTitle || market.marketSlug}
            </option>
          ))}
        </datalist>
        <select className="qtv-market-select" value={marketSlug} onChange={(event) => onMarketSlugChange(event.currentTarget.value)}>
          {marketOptions.map((market) => (
            <option key={`${market.marketSlug}-${market.tokenSide}-select`} value={market.marketSlug}>
              {market.marketTitle || market.marketSlug}
            </option>
          ))}
        </select>
        <button type="button" title="Add market">+</button>
        <div className="qtv-timeframes">
          {([
            ['500', '500blk'],
            ['1000', '1k'],
            ['2500', '2.5k'],
            ['5000', '5k'],
            ['15000', '15k'],
            ['25000', 'All'],
          ] as Array<[string, string]>).map(([value, label]) => (
            <button key={value} className={timeframe === value ? 'active' : ''} type="button" onClick={() => onTimeframeChange(value)}>{label}</button>
          ))}
        </div>
        <button type="button" title="Line">Line</button>
        <button type="button" title="Indicators">Indicators</button>
        <button type="button" title="Compare">Layout</button>
        <button type="button" title="Undo">Undo</button>
      </div>

      <div className="qtv-right-tools">
        <select value={priceSource} onChange={(event) => onPriceSourceChange(event.currentTarget.value as PriceSource)}>
          <option value="frontend">Frontend price-history</option>
          <option value="orderfilled">OrderFilled block close</option>
        </select>
        <select value={backtestEngine} onChange={(event) => onBacktestEngineChange(event.currentTarget.value as BacktestEngine)}>
          <option value="builtin">Built-in</option>
          <option value="backtrader">Backtrader</option>
          <option value="nautilus_trader">Nautilus Trader</option>
        </select>
        <button type="button">Save</button>
        <button type="button" onClick={() => onExport('json')}>Snapshot</button>
        <button type="button" onClick={() => onExport('csv')}>CSV</button>
        <button className="primary" type="button" onClick={onRunBacktest}>{loading ? 'Running...' : 'Run Backtest'}</button>
      </div>
    </header>
  );
}
