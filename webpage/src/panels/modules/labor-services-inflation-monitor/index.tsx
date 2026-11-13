import { fetchRuntimeLaborServicesInflationMonitor } from '@/services/api';
import { createMacroRegistryPanel } from '@/panels/shared/macro-registry';

export const panel = createMacroRegistryPanel({
  panelId: 'labor-services-inflation-monitor',
  title: 'LABOR / SERVICES',
  helpTitle: 'Labor Services Inflation Monitor',
  helpText: 'Combines payrolls, unemployment, wages, claims, JOLTS, and services-inflation bridges into one registry for Fed/CPI reaction judgment.',
  emptyTitle: 'LABOR SERVICES WARMING',
  name: 'Labor / Services Inflation Monitor',
  description: 'Labor, wage, claims, and services CPI pressure registry.',
  limit: 36,
  defaultEnabled: true,
}, fetchRuntimeLaborServicesInflationMonitor);
