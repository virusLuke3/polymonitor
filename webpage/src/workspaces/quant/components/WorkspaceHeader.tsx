import { useEffect, useMemo, useState } from 'preact/hooks';
import type { QuantPriceMarket } from '@/types';
import type { BacktestEngine, DataStatus, PriceSource } from '../types';
import './WorkspaceHeader.css';

type WorkspaceHeaderProps = {
  marketSlug: string;
  marketQuery: string;
  timeframe: string;
  priceSource: PriceSource;
  backtestEngine: BacktestEngine;
  loading: boolean;
  marketOptions: QuantPriceMarket[];
  selectedMarket?: QuantPriceMarket;
  marketSearchStatus: DataStatus;
  onMarketSlugChange: (value: string) => void;
  onMarketQueryChange: (value: string) => void;
  onTimeframeChange: (value: string) => void;
  onPriceSourceChange: (value: PriceSource) => void;
  onBacktestEngineChange: (value: BacktestEngine) => void;
  onRunBacktest: () => void;
  onSave: () => void;
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
  selectedMarket: selectedMarketProp,
  marketSearchStatus,
  onMarketSlugChange,
  onMarketQueryChange,
  onTimeframeChange,
  onPriceSourceChange,
  onBacktestEngineChange,
  onRunBacktest,
  onSave,
  onExport,
}: WorkspaceHeaderProps) {
  const [marketMenuOpen, setMarketMenuOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const marketChoices = useMemo(() => {
    const choices = new Map<string, QuantPriceMarket>();
    if (selectedMarketProp?.marketSlug) choices.set(selectedMarketProp.marketSlug, selectedMarketProp);
    for (const market of marketOptions) {
      const current = choices.get(market.marketSlug);
      if (!current || market.tokenSide === 'YES') choices.set(market.marketSlug, market);
    }
    return Array.from(choices.values()).slice(0, 40);
  }, [marketOptions, selectedMarketProp]);
  const selectedMarket = useMemo(
    () => selectedMarketProp || marketChoices.find((market) => market.marketSlug === marketSlug),
    [marketChoices, marketSlug, selectedMarketProp],
  );
  const activeSearchText = marketQuery.trim();
  const isSearching = marketSearchStatus === 'loading';
  const hasSearchError = marketSearchStatus === 'error';

  useEffect(() => {
    setHighlightedIndex(0);
  }, [marketQuery, marketOptions]);

  const chooseMarket = (slug: string) => {
    onMarketSlugChange(slug);
    onMarketQueryChange('');
    setMarketMenuOpen(false);
  };

  const chooseHighlightedMarket = () => {
    const highlightedSlug = marketChoices[Math.min(highlightedIndex, marketChoices.length - 1)]?.marketSlug;
    if (highlightedSlug) chooseMarket(highlightedSlug);
  };

  const moveHighlight = (delta: number) => {
    setHighlightedIndex((current) => {
      if (!marketChoices.length) return 0;
      return (current + delta + marketChoices.length) % marketChoices.length;
    });
  };

  const selectedRows = Number(selectedMarket?.blockRows || selectedMarket?.frontendRows || 0);
  const selectedSubtitle = selectedMarket?.marketSlug || marketSlug || 'No market selected';
  const sourceLabel = priceSource === 'orderfilled' ? 'OrderFilled block close' : 'Frontend price-history';
  const engineLabel = backtestEngine === 'nautilus_trader' ? 'Nautilus Trader' : backtestEngine === 'backtrader' ? 'Backtrader' : 'Built-in';

  return (
    <header className="qtv-header">
      <div className="qtv-globalbar">
        <a className="qtv-logo" href="/">POLYDATA</a>
        <button className="qtv-menu-button" type="button" title="Menu">Menu</button>
        <nav className="qtv-app-tabs" aria-label="PolyData workspaces">
          {['Markets', 'Quant', 'Replay', 'Strategies', 'Data'].map((item) => (
            <button key={item} className={item === 'Quant' ? 'active' : ''} type="button">{item}</button>
          ))}
        </nav>
        <div className="qtv-global-actions">
          <button type="button" onClick={onSave}>Save</button>
          <button type="button" onClick={() => onExport('json')}>Snapshot</button>
          <button type="button" onClick={() => onExport('csv')}>CSV</button>
        </div>
      </div>

      <div className="qtv-workbar">
        <button className="qtv-market-identity" type="button" title={selectedSubtitle} onClick={() => setMarketMenuOpen(true)}>
          <span>
            <strong>{selectedMarket?.marketTitle || marketSlug || 'Select market'}</strong>
            <em>Polymarket · outcome probabilities · {sourceLabel}</em>
          </span>
          <b>{selectedRows ? `${selectedRows.toLocaleString('en-US')} rows` : 'No rows'}</b>
        </button>

        <div className="qtv-workbar-group qtv-search-group">
        <div
          className={`qtv-market-command ${marketMenuOpen ? 'open' : ''}`}
          onBlur={() => window.setTimeout(() => setMarketMenuOpen(false), 120)}
          role="combobox"
          aria-expanded={marketMenuOpen}
          aria-haspopup="listbox"
        >
          <span className="qtv-command-label">Search</span>
          <input
            value={marketQuery}
            onFocus={() => setMarketMenuOpen(true)}
            onInput={(event) => {
              onMarketQueryChange(event.currentTarget.value);
              setMarketMenuOpen(true);
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                setMarketMenuOpen(true);
                moveHighlight(1);
              }
              if (event.key === 'ArrowUp') {
                event.preventDefault();
                setMarketMenuOpen(true);
                moveHighlight(-1);
              }
              if (event.key === 'Enter') {
                event.preventDefault();
                chooseHighlightedMarket();
              }
              if (event.key === 'Escape') setMarketMenuOpen(false);
            }}
            placeholder="Search markets, slugs, token IDs..."
            aria-autocomplete="list"
            aria-controls="quant-market-search-results"
          />
          <button
            className="qtv-command-toggle"
            type="button"
            title="Open market search"
            onClick={() => setMarketMenuOpen((current) => !current)}
          >
            ▾
          </button>
          {marketMenuOpen ? (
            <div id="quant-market-search-results" className="qtv-market-palette" role="listbox">
              <div className="qtv-palette-head">
                <strong>{activeSearchText ? 'Search markets' : 'Recent quant markets'}</strong>
                <span>{activeSearchText || 'Markets with block close coverage'}</span>
              </div>
              {isSearching ? (
                <div className="qtv-market-menu-empty">
                  <strong>Searching markets...</strong>
                  <span>{activeSearchText || 'Loading recent markets'}</span>
                </div>
              ) : hasSearchError ? (
                <div className="qtv-market-menu-empty">
                  <strong>Failed to load markets</strong>
                  <span>Retry by editing the query.</span>
                </div>
              ) : marketChoices.length ? marketChoices.map((market, index) => (
                <button
                  key={market.marketSlug}
                  className={`${market.marketSlug === marketSlug ? 'selected' : ''} ${index === highlightedIndex ? 'highlighted' : ''}`}
                  type="button"
                  role="option"
                  aria-selected={market.marketSlug === marketSlug}
                  id={`quant-market-option-${index}`}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setHighlightedIndex(index)}
                  onClick={() => chooseMarket(market.marketSlug)}
                >
                  <i aria-hidden="true">{market.marketSlug === marketSlug ? '✓' : ''}</i>
                  <span className="qtv-result-main">
                    <strong>{market.marketTitle || market.marketSlug}</strong>
                    <small>{market.marketSlug}</small>
                    <em>
                      Range {market.firstBlock ? `block ${Number(market.firstBlock).toLocaleString('en-US')}` : '-'}
                      {market.lastBlock ? ` - ${Number(market.lastBlock).toLocaleString('en-US')}` : ''}
                      {' · outcome probabilities'}
                    </em>
                  </span>
                  <span className="qtv-result-meta">
                    <b>{Number(market.blockRows || market.frontendRows || 0).toLocaleString('en-US')} rows</b>
                    <small>{market.endDate ? 'Active/dated' : 'Quant'}</small>
                  </span>
                </button>
              )) : (
                <div className="qtv-market-menu-empty">
                  <strong>No matching markets</strong>
                  <span>{activeSearchText ? `No markets found for ${activeSearchText}` : 'Only markets with quant rows are listed.'}</span>
                </div>
              )}
            </div>
          ) : null}
        </div>
        <button className="qtv-icon-button" type="button" title="Add market">+</button>
        </div>

        <div className="qtv-workbar-group qtv-timeframes" aria-label="Block range">
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

        <div className="qtv-workbar-group qtv-select-group">
          <label>
            <span>Source</span>
        <select value={priceSource} onChange={(event) => onPriceSourceChange(event.currentTarget.value as PriceSource)}>
          <option value="frontend">Frontend price-history</option>
          <option value="orderfilled">OrderFilled block close</option>
        </select>
          </label>
          <label>
            <span>Engine</span>
        <select value={backtestEngine} onChange={(event) => onBacktestEngineChange(event.currentTarget.value as BacktestEngine)}>
          <option value="builtin">Built-in</option>
          <option value="backtrader">Backtrader</option>
          <option value="nautilus_trader">Nautilus Trader</option>
        </select>
          </label>
        </div>

        <div className="qtv-workbar-group qtv-run-group">
          <span>{engineLabel}</span>
          <button className="primary" type="button" onClick={onRunBacktest}>{loading ? 'Running...' : 'Run Backtest'}</button>
        </div>
      </div>
    </header>
  );
}
