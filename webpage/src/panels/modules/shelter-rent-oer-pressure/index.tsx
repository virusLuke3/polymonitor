import { fetchRuntimeShelterRentOerPressure } from '@/services/api';
import { createMacroDriverPanel } from '@/panels/shared/macro-driver';

export const panel = createMacroDriverPanel({
  panelId: 'shelter-rent-oer-pressure',
  title: 'SHELTER / OER',
  badge: 'FRED',
  glyph: 'home',
  driverLabel: 'Core CPI Driver',
  helpTitle: 'Shelter Rent OER Pressure',
  helpText: 'Uses official FRED/BLS rent, OER, shelter CPI, and housing-price series to expose the sticky core-CPI channel Polymarket traders watch before CPI prints.',
  emptyTitle: 'SHELTER WATCH WARMING',
  name: 'Shelter Rent OER Pressure',
  description: 'Rent and OER pressure for core CPI markets.',
  limit: 8,
}, fetchRuntimeShelterRentOerPressure);
