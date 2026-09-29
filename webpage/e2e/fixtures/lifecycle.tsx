import { render } from 'preact';
import { useState } from 'preact/hooks';
import { RUNTIME_PANEL_MODULES } from '../../src/panels/registry';
import { usePanelRuntime } from '../../src/panels/usePanelRuntime';
import { useMarketFocus } from '../../src/features/market-focus/useMarketFocus';
import { useMarketDossier } from '../../src/features/market-focus/useMarketDossier';
import { useNaturalHazards } from '../../src/features/world-event-map/data/useNaturalHazards';
import { useCountryGeometry } from '../../src/features/world-event-map/data/useCountryGeometry';
import { worldEventLayerById } from '../../src/features/world-event-map/config/layerRegistry';
import { useFocusedOrderBook } from '../../src/features/market-focus/useFocusedOrderBook';
import { useWorkspacePreferences, useWorkspaceSync } from '../../src/features/workspace/useWorkspacePreferences';
import { useDashboardData } from '../../src/features/workspace/useDashboardData';
import type { WorldEventRegion } from '../../src/features/world-event-map';
import type { PanelModule } from '../../src/panels/types';
import type { BootstrapPayload, MarketListItem } from '../../src/types';
import { fixtureMarkets } from './dashboard';
import { GENERATED_AT } from './world-event-map';

const root = document.getElementById('root')!;
type HarnessKind = 'runtime' | 'observed-runtime' | 'registered-runtime' | 'dashboard' | 'focus' | 'book' | 'workspace' | 'hazards' | 'dossier' | 'geometry';
type HazardView = { layers: string[]; zoom: number; center: [number, number]; active: boolean };
const noPanels: PanelModule[] = [];
const translate = (key: string) => key;
type Pending = { id: string; signal: AbortSignal; resolve: (value: unknown) => void; reject: (error: Error) => void };
const requests: Pending[] = [];
const modules: PanelModule[] = [{
  id: 'shared', title: 'Shared fixture', eyebrow: 'TEST', description: 'Lifecycle fixture',
  refreshPolicy: { tier: 'fast', intervalMs: 20_000, retry: { attempts: 2, baseDelayMs: 1000 } },
  fetchData: (context) => new Promise((resolve, reject) => {
    requests.push({ id: 'shared', signal: context!.signal, resolve, reject });
  }),
}, { id: 'shared-view', dataSourceId: 'shared', title: 'Second view', eyebrow: 'TEST', description: 'Same source' }];
const bootstrap = { generatedAt: GENERATED_AT, activeMarketsPreview: fixtureMarkets, activeMarketGroupsPreview: [] } as unknown as BootstrapPayload;
const api = {
  requests,
  runtime: null as ReturnType<typeof usePanelRuntime> | null,
  dashboard: null as ReturnType<typeof useDashboardData> | null,
  focus: null as ReturnType<typeof useMarketFocus> | null,
  dossier: null as ReturnType<typeof useMarketDossier> | null,
  hazards: null as ReturnType<typeof useNaturalHazards> | null,
  geometry: null as ReturnType<typeof useCountryGeometry> | null,
  book: null as ReturnType<typeof useFocusedOrderBook> | null,
  workspace: null as ReturnType<typeof useWorkspacePreferences> | null,
  sync: null as ReturnType<typeof useWorkspaceSync> | null,
  camera: null as { region: WorldEventRegion; mapZoom: number } | null,
  setPanels: (_ids: string[]) => {},
  selectBook: (_id: number) => {},
  selectDossier: (_id: number) => {},
  setHazardView: (_patch: Partial<HazardView>) => {},
  setGeometryEnabled: (_enabled: boolean) => {},
  mount: (kind: HarnessKind) => {
    render(kind === 'dashboard' ? <Dashboard /> : kind === 'observed-runtime' ? <Runtime observed /> : kind === 'registered-runtime' ? <Runtime registered /> : kind === 'runtime' ? <Runtime /> : kind === 'focus' ? <Focus /> : kind === 'book' ? <Book />
      : kind === 'hazards' ? <Hazards /> : kind === 'dossier' ? <Dossier /> : kind === 'geometry' ? <Geometry /> : <Workspace />, root);
  },
  unmount: () => render(null, root),
};
function Runtime({ registered = false, observed = false }: { registered?: boolean; observed?: boolean }) {
  const [ids, setIds] = useState(registered ? ['price-implications', 'oracle-timeline', 'sample-chain-trades'] : ['shared']);
  api.setPanels = setIds;
  api.runtime = usePanelRuntime({ panels: registered ? RUNTIME_PANEL_MODULES : modules, activePanelIds: ids, waitForVisibility: observed });
  return <output>runtime</output>;
}
function Dashboard() {
  const workspace = useWorkspacePreferences();
  const runtime = usePanelRuntime({ panels: noPanels, activePanelIds: [] });
  api.dashboard = useDashboardData(workspace, runtime);
  return <output>{api.dashboard.loading ? 'loading' : 'released'}</output>;
}
function Focus() {
  api.focus = useMarketFocus({ bootstrap, markets: fixtureMarkets as MarketListItem[], marketGroups: [], catalogLoaded: true });
  return <output>{api.focus.selectedMarketId}</output>;
}
function Book() {
  const [id, setId] = useState(1);
  api.selectBook = setId;
  api.book = useFocusedOrderBook({ marketId: id, selectedTokenId: `yes-${id}`, selectedNoTokenId: `no-${id}`,
    marketIsClosed: false, bookSide: 'yes', bundledLob: null, outcomeLabel: 'YES' });
  return <output>{id}</output>;
}
function Dossier() {
  const [id, setId] = useState(1);
  api.selectDossier = setId;
  api.dossier = useMarketDossier(id, translate);
  return <output>{api.dossier.bundle?.market?.id}</output>;
}
function Hazards() {
  const [view, setView] = useState<HazardView>({ layers: ['earthquakes-volcanoes', 'wildfires'], zoom: 6, center: [-70, 43], active: true });
  api.setHazardView = (patch) => setView((current) => ({ ...current, ...patch }));
  const runtime = usePanelRuntime({ panels: noPanels, activePanelIds: [] });
  api.hazards = useNaturalHazards({ ...view,
    sourceKeys: view.layers.flatMap((id) => worldEventLayerById(id)?.sourceKeys || []),
    suspended: !view.active || runtime.suspended,
  });
  return <output>{api.hazards.events.length}</output>;
}
function Geometry() {
  const [enabled, setEnabled] = useState(false);
  api.setGeometryEnabled = setEnabled;
  api.geometry = useCountryGeometry(enabled);
  return <output>{api.geometry.index?.countries.length ?? 0}</output>;
}
function Workspace() {
  const [region, setRegion] = useState<WorldEventRegion>('global');
  const [mapZoom, setMapZoom] = useState(2.2);
  api.workspace = useWorkspacePreferences();
  api.camera = { region, mapZoom };
  api.sync = useWorkspaceSync(api.workspace, { region, mapZoom, setRegion, setMapZoom });
  return <output>{api.sync.workspaceSyncStatus}</output>;
}
declare global { interface Window { frontendHarness: typeof api } }
window.frontendHarness = api;
