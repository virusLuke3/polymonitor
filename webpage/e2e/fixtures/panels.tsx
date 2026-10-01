import { render } from 'preact';
import { useState } from 'preact/hooks';
import { FocusedMarketStrip } from '../../src/components/FocusedMarketStrip';
import { PANEL_MODULES } from '../../src/panels/registry';
import { LocaleProvider } from '../../src/services/i18n';
import type { PanelRenderContext } from '../../src/types';
import '../../src/styles/fonts.css';
import '../../src/styles/base-layer.css';
import '../../src/styles/panel-layout-stability.css';

const root = document.getElementById('root')!;
const noop = () => {};
const context: PanelRenderContext = {
  bootstrap: null, markets: [], marketGroups: [], marketGroupSort: 'active',
  setMarketGroupSort: noop, marketCatalogRefreshing: false, marketCatalogError: null,
  refreshMarketCatalog: async () => {}, selectedMarketId: null, setSelectedMarketId: noop,
  prefetchMarketFocus: noop, focusMarketGroup: noop, selectedMarketGroupId: null,
  selectedMarketGroup: null, selectedMarketGroupOutcomeKey: null, setSelectedMarketGroupOutcomeKey: noop,
  selectedMarketGroupDetail: null, selectedMarketGroupChart: null, selectedMarketGroupChartRange: '1d',
  setSelectedMarketGroupChartRange: noop, selectedMarket: null, selectedWeatherCityId: null,
  setSelectedWeatherCityId: noop, bundle: null, health: null, globalTrades: [], globalOracle: [], latestContent: [], runtimeData: {},
};

function FocusFixture({ data }: { data: Partial<PanelRenderContext> }) {
  const [range, setRange] = useState<PanelRenderContext['selectedMarketGroupChartRange']>('1d');
  const ctx = { ...context, ...data, selectedMarketGroupChartRange: range, setSelectedMarketGroupChartRange: setRange };
  return <LocaleProvider><main className="wm-dashboard"><section className="wm-focused-market-row">
    <div className="wm-focused-market-list">{PANEL_MODULES.find(p => p.id === 'active-markets')!.render!(ctx)}</div>
    <div className="wm-focused-market-right"><FocusedMarketStrip {...ctx} renderPanelSlot={(id, className, panel) => (
      <div className={`wm-panel-slot ${className}`} data-workspace-panel-id={id}>{panel}</div>
    )} /></div>
    <div className="wm-focused-oracle-feed">{PANEL_MODULES.find(p => p.id === 'oracle-feed')!.render!(ctx)}</div>
  </section></main></LocaleProvider>;
}
const api = {
  ids: PANEL_MODULES.filter(p => p.render && !['active-markets', 'global-orderfilled', 'oracle-feed'].includes(p.id)).map(p => p.id),
  mount(id: string, runtimeData: Record<string, unknown> = {}, data: Partial<PanelRenderContext> = {}) {
    render(null, root);
    api.update(id, runtimeData, data);
  },
  update(id: string, runtimeData: Record<string, unknown> = {}, data: Partial<PanelRenderContext> = {}) {
    const panel = PANEL_MODULES.find(p => p.id === id)!;
    render(<LocaleProvider><main className="wm-dashboard"><div className="wm-panels-grid">
      <div className="wm-panel-slot" data-workspace-panel-id={id}>
        {panel.render!({ ...context, ...data, runtimeData })}
      </div>
    </div></main></LocaleProvider>, root);
  },
  mountFocus(data: Partial<PanelRenderContext>) {
    render(null, root);
    render(<FocusFixture data={data} />, root);
  },
};
declare global { interface Window { panelHarness: typeof api } }
window.panelHarness = api;
