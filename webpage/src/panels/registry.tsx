import { PANEL_MODULES } from './modules';
import type { PanelModule, RegistryEntry } from './types';

export type { PanelModule, RegistryEntry } from './types';
export { PANEL_MODULES } from './modules';

export const PANEL_LIBRARY = PANEL_MODULES.map(({
  render,
  fetchData,
  refreshPolicy,
  maxBatchSize,
  ...definition
}) => definition);

function assertUniquePanelIds(panels: PanelModule[]) {
  const seen = new Set<string>();
  for (const panel of panels) {
    if (seen.has(panel.id)) {
      throw new Error(`Duplicate panel module id: ${panel.id}`);
    }
    seen.add(panel.id);
    if (panel.fetchData && !panel.refreshPolicy?.tier) {
      throw new Error(`Runtime panel ${panel.id} must declare refreshPolicy.tier`);
    }
    if (panel.dataSourceId && (panel.fetchData || !panels.find((owner) => owner.id === panel.dataSourceId)?.fetchData)) {
      throw new Error(`Panel ${panel.id} must consume one registered data owner`);
    }
    if (panel.dataDependencies?.some((id) => !panels.find((owner) => owner.id === id)?.fetchData)) {
      throw new Error(`Panel ${panel.id} has an unregistered data dependency`);
    }
  }
}

assertUniquePanelIds(PANEL_MODULES);

export const DEFAULT_PANEL_IDS = PANEL_MODULES
  .filter((panel) => panel.defaultEnabled !== false)
  .map((panel) => panel.id);

export const RUNTIME_PANEL_MODULES = PANEL_MODULES.filter((panel) => typeof panel.fetchData === 'function' || panel.dataSourceId || panel.dataDependencies?.length);

export const PANEL_REGISTRY: Record<string, RegistryEntry> = Object.fromEntries(
  PANEL_MODULES.map((panel) => [panel.id, panel]),
);
