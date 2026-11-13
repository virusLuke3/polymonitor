import { fetchRuntimeLaborWageServicesPressure } from '@/services/api';
import { createMacroDriverPanel } from '@/panels/shared/macro-driver';

export const panel = createMacroDriverPanel({
  panelId: 'labor-wage-services-pressure',
  title: 'LABOR / WAGES',
  badge: 'BLS',
  glyph: 'labor',
  driverLabel: 'Services CPI Driver',
  helpTitle: 'Labor Wage Services Pressure',
  helpText: 'Combines public payrolls, unemployment, wages, claims, and JOLTS to show whether services inflation and Fed odds are being pulled hotter or cooler.',
  emptyTitle: 'LABOR WATCH WARMING',
  name: 'Labor Wage Services Pressure',
  description: 'Labor-market and wage pressure for services CPI and Fed markets.',
  limit: 8,
}, fetchRuntimeLaborWageServicesPressure);
