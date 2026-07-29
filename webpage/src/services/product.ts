import { authRequest } from '@/services/auth';

export type AlertRule = {
  id: string;
  marketId: number;
  kind: string;
  threshold: number | null;
  enabled: boolean;
  cooldownSeconds: number;
  conditionActive: boolean;
  lastTriggeredAt: string | null;
};

export type WatchlistItem = {
  marketId: number;
  title: string;
  slug?: string | null;
  category?: string | null;
  latestPrice: number | null;
  change24h: number | null;
  volume24h: number;
  tradeCount24h: number;
  priceUpdatedAt?: string | null;
  completionStatus: string;
  oracleStage: string;
  rules: AlertRule[];
};

export type Watchlist = {
  id: string | null;
  name: string;
  items: WatchlistItem[];
  summary: { markets: number; activeRules: number; oracleGaps: number; unreadAlerts: number };
  alertKinds: string[];
};

export type AlertEvent = {
  id: string;
  marketId: number;
  marketTitle?: string | null;
  kind: string;
  severity: string;
  title: string;
  detail: string;
  observedPrice: number | null;
  oracleStatus?: string | null;
  sourceObservedAt?: string | null;
  occurredAt: string;
  readAt: string | null;
};

export type NotificationPreferences = {
  inAppEnabled: boolean;
  digestMode: 'realtime' | 'hourly' | 'daily' | 'off';
  quietStartMinute: number | null;
  quietEndMinute: number | null;
  timezone: string;
  updatedAt?: string | null;
  channels: Record<string, { available: boolean; connected: boolean; detail?: string }>;
};

export const fetchWatchlist = () => authRequest<Watchlist>('/product/watchlist');
export const addWatchlistMarket = (marketId: number, note = '') =>
  authRequest<{ item: unknown }>('/product/watchlist/markets', {
    method: 'POST',
    body: JSON.stringify({ marketId, note }),
  }, { csrf: true });
export const removeWatchlistMarket = (marketId: number) =>
  authRequest<{ status: string }>(`/product/watchlist/markets/${marketId}`, { method: 'DELETE' }, { csrf: true });
export const createAlertRule = (marketId: number, kind: string, threshold: number | null) =>
  authRequest<{ item: AlertRule }>('/product/alert-rules', {
    method: 'POST',
    body: JSON.stringify({ marketId, kind, threshold, cooldownSeconds: 3600 }),
  }, { csrf: true });
export const deleteAlertRule = (id: string) =>
  authRequest<{ status: string }>(`/product/alert-rules/${encodeURIComponent(id)}`, { method: 'DELETE' }, { csrf: true });
export const fetchAlerts = () => authRequest<{ items: AlertEvent[]; unreadCount: number }>('/product/alerts?limit=100');
export const markAlertRead = (id: string) =>
  authRequest<{ status: string }>(`/product/alerts/${encodeURIComponent(id)}/read`, { method: 'POST', body: '{}' }, { csrf: true });
export const markAllAlertsRead = () =>
  authRequest<{ status: string; count: number }>('/product/alerts/read-all', { method: 'POST', body: '{}' }, { csrf: true });
export const fetchNotificationPreferences = () =>
  authRequest<NotificationPreferences>('/product/notification-preferences');
export const updateNotificationPreferences = (value: Omit<NotificationPreferences, 'channels' | 'updatedAt'>) =>
  authRequest<NotificationPreferences>('/product/notification-preferences', {
    method: 'PUT',
    body: JSON.stringify(value),
  }, { csrf: true });
