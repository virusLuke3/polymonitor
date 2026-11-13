import { fetchRuntimeCpiComponentsPressureRegistry } from '@/services/api';
import { createMacroRegistryPanel } from '@/panels/shared/macro-registry';

export const panel = createMacroRegistryPanel({
  panelId: 'cpi-components-pressure-registry',
  title: 'CPI COMPONENTS',
  helpTitle: 'CPI Components Pressure Registry',
  helpText: 'Merges energy, food, and shelter/OER seeds into one dense component-pressure registry for headline and core CPI judgment.',
  emptyTitle: 'COMPONENTS WARMING',
  name: 'CPI Components Pressure Registry',
  description: 'Energy, food, shelter, and CPI component pressure registry.',
  limit: 48,
  defaultEnabled: true,
}, fetchRuntimeCpiComponentsPressureRegistry);
