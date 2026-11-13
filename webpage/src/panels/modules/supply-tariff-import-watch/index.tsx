import { fetchRuntimeSupplyTariffImportWatch } from '@/services/api';
import { createMacroDriverPanel } from '@/panels/shared/macro-driver';

export const panel = createMacroDriverPanel({
  panelId: 'supply-tariff-import-watch',
  title: 'SUPPLY / TARIFF',
  badge: 'PUBLIC',
  glyph: 'policy',
  driverLabel: 'Goods CPI Driver',
  helpTitle: 'Supply Tariff Import Watch',
  helpText: 'Tracks free FRED supply/import series and Federal Register trade-policy notices as CPI goods-price inputs for Polymarket inflation and Fed markets.',
  emptyTitle: 'SUPPLY WATCH WARMING',
  name: 'Supply Tariff Import Watch',
  description: 'Supply-chain and tariff watch for CPI goods pressure.',
  limit: 8,
}, fetchRuntimeSupplyTariffImportWatch);
