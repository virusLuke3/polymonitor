import { useMemo, useState } from 'preact/hooks';
import type { QuantPriceMarket } from '@/types';
import type { BacktestEngine, PriceSource } from '../types';
import './WorkspaceHeader.css';

type WorkspaceHeaderProps = {
  marketSlug: string;
  marketQuery: string;
  timeframe: string;
  priceSource: PriceSource;
  backtestEngine: BacktestEngine;
  loading: boolean;
  marketOptions: QuantPriceMarket[];
  onMarketSlugChange: (value: string) => void;
  onMarketQueryChange: (value: string) => void;
  onTimeframeChange: (value: string) => void;
  onPriceSourceChange: (value: PriceSource) => void;
  onBacktestEngineChange: (value: BacktestEngine) => void;
  onRunBacktest: () => void;
  onExport: (format: 'csv' | 'json') => void;
};

export function WorkspaceHeader({
  marketSlug,
  marketQuery,
  timeframe,
  priceSource,
  backtestEngine,
  loading,
  marketOptions,
  onMarketSlugChange,
  onMarketQueryChange,
  onTimeframeChange,
  onPriceSourceChange,
  onBacktestEngineChange,
  onRunBacktest,
  onExport,
}: WorkspaceHeaderProps) {
  const [marketMenuOpen, setMarketMenuOpen] = useState(false);
  const marketChoices = useMemo(() => {
    const choices = new Map<string, QuantPriceMarket>();
    for (const market of marketOptions) {
      const current = choices.get(market.marketSlug);
      if (!current || market.tokenSide === 'YES') choices.set(market.marketSlug, market);
    }
    return Array.from(choices.values()).slice(0, 24);
  }, [marketOptions]);
  const selectedMarket = useMemo(
    () => marketChoices.find((market) => market.marketSlug === marketSlug),
    [marketChoices, marketSlug],
  );

  const chooseMarket = (slug: string) => {
    onMarketSlugChange(slug);
    onMarketQueryChange(slug);
    setMarketMenuOpen(false);
  };

  const chooseFirstMarket = () => {
    const firstSlug = marketChoices[0]?.marketSlug;
    if (firstSlug) chooseMarket(firstSlug);
  };

  return (
    <header className="qtv-topbar">
      <div className="qtv-left-tools">
        <a className="qtv-logo" href="/">POLYDATA</a>
        <button type="button" title="Menu">Menu</button>
        <div
          className="qtv-symbol-search qtv-market-combobox"
          onBlur={() => window.setTimeout(() => setMarketMenuOpen(false), 120)}
        >
          <span>Search</span>
          <input
            value={marketQuery}
            onFocus={() => setMarketMenuOpen(true)}
            onInput={(event) => {
              onMarketQueryChange(event.currentTarget.value);
              setMarketMenuOpen(true);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                chooseFirstMarket();
              }
              if (event.key === 'Escape') setMarketMenuOpen(false);
            }}
            placeholder="Search market"
          />
          <button
            className="qtv-market-menu-toggle"
            type="button"
            title="Open market list"
            onClick={() => setMarketMenuOpen((current) => !current)}
          >
            ▾
          </button>
          {marketMenuOpen ? (
            <div className="qtv-market-menu" role="listbox">
              {marketChoices.length ? marketChoices.map((market) => (
                <button
                  key={market.marketSlug}
                  className={market.marketSlug === marketSlug ? 'active' : ''}
                  type="button"
                  role="option"
                  aria-selected={market.marketSlug === marketSlug}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => chooseMarket(market.marketSlug)}
                >
                  <strong>{market.marketTitle || market.marketSlug}</strong>
                  <span>{market.marketSlug}</span>
                  <em>{Number(market.blockRows || 0).toLocaleString('en-US')} block rows</em>
                </button>
              )) : (
                <div className="qtv-market-menu-empty">No matching markets</div>
              )}
            </div>
          ) : null}
        </div>
        <button className="qtv-selected-market" type="button" title={marketSlug} onClick={() => setMarketMenuOpen(true)}>
          {selectedMarket?.marketTitle || marketSlug || 'Select market'}
        </button>
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
