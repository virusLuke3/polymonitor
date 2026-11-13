import { fetchRuntimeGoodsTariffSupplyWatch } from '@/services/api';
import { createMacroRegistryPanel } from '@/panels/shared/macro-registry';

export const panel = createMacroRegistryPanel({
  panelId: 'goods-tariff-supply-watch',
  title: 'GOODS / TARIFF',
  helpTitle: 'Goods Tariff Supply Watch',
  helpText: 'Tracks seeded FRED goods/upstream series and Federal Register trade-policy events as CPI goods-price inputs.',
  emptyTitle: 'GOODS WATCH WARMING',
  name: 'Goods / Tariff / Supply Chain Watch',
  description: 'Goods inflation, tariff, import-price, and supply-chain registry.',
  limit: 36,
  defaultEnabled: true,
}, fetchRuntimeGoodsTariffSupplyWatch);
