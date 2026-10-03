import { useMapSignals } from '../../src/features/world-event-map/data/useMapSignals';
import { useMapInfrastructure } from '../../src/features/world-event-map/data/useMapInfrastructure';
import { useAviationViewport } from '../../src/features/world-event-map/data/useAviationViewport';
import { render } from 'preact';
import { useMemo, useState } from 'preact/hooks';
import { RUNTIME_PANEL_MODULES } from '../../src/panels/registry';
import { usePanelRuntime } from '../../src/panels/usePanelRuntime';
import { ApiHttpError } from '../../src/services/api';
import { PanelResourceProvider } from '../../src/panels/usePanelResource';
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
type HarnessKind = 'runtime' | 'runtime-policy' | 'runtime-batch-policy' | 'observed-runtime' | 'registered-runtime' | 'dashboard' | 'focus' | 'book' | 'workspace' | 'hazards' | 'dossier' | 'geometry' | 'aviation' | 'map-signals' | 'map-infrastructure';
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
const policyModules: PanelModule[] = ['frequent', 'blocked'].map(id => ({
  id, title: id, eyebrow: 'TEST', description: 'Independent scheduling fixture', batch: false,
  refreshPolicy: { tier: 'slow', intervalMs: 5000, requestTimeoutMs: id === 'blocked' ? 10_000 : 30_000,
    retry: { attempts: 2, baseDelayMs: 1000 } },
  fetchData: context => new Promise((resolve, reject) => requests.push({ id, signal: context!.signal, resolve, reject })),
}));
const batchPolicyModules: PanelModule[] = policyModules.map(panel => ({ ...panel, batch: true }));
const bootstrap = { generatedAt: GENERATED_AT, activeMarketsPreview: fixtureMarkets, activeMarketGroupsPreview: [] } as unknown as BootstrapPayload;
const api = {
  requests,
  rejectVerification: (index: number) => requests[index].reject(new ApiHttpError(503, 'fixture', '1', true)),
  signals: null as ReturnType<typeof useMapSignals> | null,
  infrastructure: null as ReturnType<typeof useMapInfrastructure> | null,
  setMapSourceActive: (_active:boolean) => {},
  runtime: null as ReturnType<typeof usePanelRuntime> | null,
  dashboard: null as ReturnType<typeof useDashboardData> | null,
  focus: null as ReturnType<typeof useMarketFocus> | null,
  dossier: null as ReturnType<typeof useMarketDossier> | null,
  aviation: null as ReturnType<typeof useAviationViewport> | null,
  setAviationView: (_patch: Partial<HazardView>) => {},
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
    render(kind === 'map-signals' ? <Signals /> : kind === 'map-infrastructure' ? <Infrastructure /> : kind === 'dashboard' ? <PanelResourceProvider><Dashboard /></PanelResourceProvider> : kind === 'observed-runtime' ? <Runtime observed /> : kind === 'registered-runtime' ? <Runtime registered /> : kind === 'runtime-batch-policy' ? <Runtime policy batch /> : kind === 'runtime-policy' ? <Runtime policy /> : kind === 'runtime' ? <Runtime /> : kind === 'focus' ? <Focus /> : kind === 'book' ? <Book />
      : kind === 'aviation' ? <Aviation /> : kind === 'hazards' ? <Hazards /> : kind === 'dossier' ? <Dossier /> : kind === 'geometry' ? <Geometry /> : <Workspace />, root);
  },
  unmount: () => render(null, root),
};
function Signals() {
  const [active,setActive]=useState(true);api.setMapSourceActive=setActive;
  api.signals=useMapSignals(['airport-disruptions'],!active);
  return <output>{api.signals.events.length}</output>;
}
function Infrastructure() {
  const [active,setActive]=useState(true);api.setMapSourceActive=setActive;
  const viewport=useMemo(()=>({center:[180,10] as [number,number],zoom:9,widthCssPx:900,heightCssPx:600,revision:1,
    bounds:[[178,9,180,11],[-180,9,-178,11]] as [number,number,number,number][]}),[]);
  api.infrastructure=useMapInfrastructure(active,viewport);
  return <output>{api.infrastructure.events.length}</output>;
}
function Runtime({ registered = false, observed = false, policy = false, batch = false }: { registered?: boolean; observed?: boolean; policy?: boolean; batch?: boolean }) {
  const [ids, setIds] = useState(registered ? ['price-implications', 'oracle-timeline', 'sample-chain-trades'] : policy ? ['frequent', 'blocked'] : ['shared']);
  api.setPanels = setIds;
  api.runtime = usePanelRuntime({ panels: registered ? RUNTIME_PANEL_MODULES : batch ? batchPolicyModules : policy ? policyModules : modules, activePanelIds: ids, waitForVisibility: observed });
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
function Aviation() {
  const [view, setView] = useState<HazardView>({ layers: [], zoom: 3, center: [-70, 43], active: true });
  api.setAviationView = patch => setView(current => ({ ...current, ...patch }));
  const viewport = useMemo(()=>({center:view.center,zoom:view.zoom,widthCssPx:960,heightCssPx:620,revision:1,
    bounds:[[view.center[0]-20,view.center[1]-12,view.center[0]+20,view.center[1]+12] as [number,number,number,number]]}),[view.center,view.zoom]);
  api.aviation = useAviationViewport(view.active, viewport);
  return <output>{api.aviation.payload?.generatedAt}</output>;
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
