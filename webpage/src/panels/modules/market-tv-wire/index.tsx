import { mediaSnapshot } from '@/panels/shared/context-snapshots';
import { scoreLabel } from '../../shared/formatters';
import {
  panelStatus,
  categoryToneClass,
  sourceLocation,
  categoryLabel,
} from '../../shared/videoPlayback';
import { useEffect, useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeMarketTvWire } from '@/services/api';
import type { RuntimeMarketTvWireItem, RuntimeMarketTvWirePayload } from '@/types';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '@/panels/definePanel';
import { useSpecialistCopy } from '@/services/specialist-i18n';

import { MarketTvPreview } from './Playback';
import { playbackCandidates } from './playback';

function badgeLabel(payload?: RuntimeMarketTvWirePayload | null) {
  const status = String(payload?.status || '').toLowerCase();
  const cacheMode = String(payload?.cacheMode || '').toLowerCase();
  if (cacheMode.includes('stale')) return 'STALE';
  if (status === 'warming') return 'WARM';
  if (status === 'degraded') return 'DEGRADED';
  if (status === 'empty') return 'EMPTY';
  return 'LIVE';
}

function itemTitle(item: RuntimeMarketTvWireItem) {
  return item.displayName || item.name || 'Live video source';
}

function sourceTypeLabel(value?: string | null) {
  const sourceType = String(value || 'external').toLowerCase();
  if (sourceType === 'youtube') return 'YT';
  if (sourceType === 'external') return 'EXT';
  if (sourceType === 'timelapse') return 'TL';
  return 'HLS';
}

function statusClass(value?: string | null) {
  const status = String(value || 'unknown').toLowerCase();
  if (status === 'ready') return 'ready';
  if (status === 'not_24_7' || status === 'stale' || status === 'unknown') return 'stale';
  return 'blocked';
}

function statusLabel(value?: string | null) {
  const status = String(value || 'unknown').toLowerCase();
  if (status === 'not_24_7') return 'NOT 24/7';
  return status.toUpperCase();
}

function isEmbeddedPreviewable(item?: RuntimeMarketTvWireItem | null) {
  return !!item && playbackCandidates(item).length > 0;
}

function MarketTvRow({
  item,
  active,
  onPreview,
}: {
  item: RuntimeMarketTvWireItem;
  active: boolean;
  onPreview: () => void;
}) {
  const { copy, shared, formatRelativeTime } = useSpecialistCopy('market-tv-wire');
  const previewReady = isEmbeddedPreviewable(item);
  const tags = (item.matchedTerms?.length ? item.matchedTerms : item.marketTags || []).slice(0, 3);
  return (
    <article className={`wm-market-tv-row ${active ? 'active' : ''}`}>
      <button type="button" className="wm-market-tv-row-main" onClick={onPreview} title={item.marketUseCase || itemTitle(item)}>
        <span className={`wm-market-tv-dot ${statusClass(item.status)}`} />
        <div className="wm-market-tv-copy">
          <div className="wm-market-tv-meta">
            <span>{categoryLabel(item.category)}</span>
            <span>{sourceTypeLabel(item.sourceType)}</span>
            <span className={statusClass(item.status)}>{statusLabel(item.status)}</span>
            <span>{sourceLocation(item)}</span>
          </div>
          <strong>{itemTitle(item)}</strong>
          <p>{item.marketUseCase || item.sourceName || copy('liveContext', 'Live source for market context.')}</p>
          {tags.length ? (
            <div className="wm-market-tv-tags">
              {tags.map((tag) => <span key={`${item.id}-${tag}`}>{String(tag).toUpperCase()}</span>)}
            </div>
          ) : null}
        </div>
        <div className="wm-market-tv-score">
          <strong>{scoreLabel(item.relevanceScore)}</strong>
          <span>{previewReady ? shared('watch', 'WATCH') : shared('open', 'OPEN')}</span>
          <em>{formatRelativeTime(item.lastCheckedAt)}</em>
        </div>
      </button>
    </article>
  );
}

function MarketTvWirePanel({ payload }: { payload?: RuntimeMarketTvWirePayload | null }) {
  const { copy, shared } = useSpecialistCopy('market-tv-wire');
  const [showHelp, setShowHelp] = useState(false);
  const [activeCategory, setActiveCategory] = useState('all');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [categoryPayload, setCategoryPayload] = useState<{ category: string; payload: RuntimeMarketTvWirePayload } | null>(null);
  const [categoryLoading, setCategoryLoading] = useState(false);
  const [categoryError, setCategoryError] = useState<string | null>(null);
  const selectedPayload = activeCategory === 'all'
    ? payload
    : (categoryPayload?.category === activeCategory ? categoryPayload.payload : null);
  const items = selectedPayload?.items || [];
  const categories = payload?.categories || selectedPayload?.categories || [];
  const summary = payload?.summary || selectedPayload?.summary || {};
  const totalCount = Number(summary.total ?? payload?.selection?.total ?? items.length);
  const visibleItems = useMemo(() => items, [items]);
  const activeItem = visibleItems.find((item) => item.id === activeId) || null;
  const previewItem = activeItem || visibleItems.find((item) => isEmbeddedPreviewable(item)) || visibleItems[0] || null;

  useEffect(() => {
    let cancelled = false;
    setActiveId(null);
    setCategoryError(null);
    if (activeCategory === 'all') {
      setCategoryPayload(null);
      setCategoryLoading(false);
      return undefined;
    }
    setCategoryLoading(true);
    fetchRuntimeMarketTvWire(60, activeCategory)
      .then((nextPayload) => {
        if (cancelled) return;
        setCategoryPayload({ category: activeCategory, payload: nextPayload });
      })
      .catch((error) => {
        if (cancelled) return;
        setCategoryError(error instanceof Error ? error.message : copy('loadCategoryFailed', 'Failed to load category'));
      })
      .finally(() => {
        if (!cancelled) setCategoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeCategory]);

  useEffect(() => {
    if (!visibleItems.length) {
      setActiveId(null);
      return;
    }
    if (!activeId || !visibleItems.some((item) => item.id === activeId)) {
      setActiveId((visibleItems.find((item) => isEmbeddedPreviewable(item)) || visibleItems[0])?.id || null);
    }
  }, [activeId, visibleItems]);

  return (
    <Panel
      title={copy('title', 'MARKET TV WIRE')}
      titleControls={(
        <button
          type="button"
          className="wm-panel-help-button"
          aria-label={copy('explainAria', 'Explain Market TV Wire panel')}
          aria-expanded={showHelp}
          onClick={() => setShowHelp((value) => !value)}
        >
          ?
        </button>
      )}
      badge={badgeLabel(payload)}
      status={panelStatus(payload)}
      count={items.length || undefined}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>{copy('helpTitle', 'Market TV Wire')}</strong>
          <p>{copy('helpText', 'GCP-seeded live video sources ranked for Polymarket context. Stale snapshots stay visible when source refresh fails.')}</p>
        </div>
      ) : null}
      className="wm-market-panel wm-market-tv-panel"
      dataPanelId="market-tv-wire"
    >
      <div className="wm-market-tv-layout">
        <div className="wm-market-tv-control-rail">
          <div className="wm-market-tv-tabs">
            <button
              type="button"
              className={`${categoryToneClass('all')} ${activeCategory === 'all' ? 'active' : ''}`}
              onClick={() => setActiveCategory('all')}
            >
              {shared('all', 'ALL')} <span>{Number.isFinite(totalCount) ? totalCount : items.length}</span>
            </button>
            {categories.map((category) => (
              <button
                key={category.id}
                type="button"
                className={`${categoryToneClass(category.id)} ${activeCategory === category.id ? 'active' : ''}`}
                onClick={() => setActiveCategory(category.id)}
              >
                {category.label} <span>{category.count}</span>
              </button>
            ))}
          </div>
          <div className="wm-market-tv-summary">
            <span><strong>{summary.liveReady ?? 0}</strong> {shared('ready', 'READY')}</span>
            <span><strong>{summary.marketMatched ?? 0}</strong> {shared('matched', 'MATCHED')}</span>
            <span><strong>{summary.regions ?? 0}</strong> {shared('regions', 'REGIONS')}</span>
            <span><strong>{summary.staleCount ?? 0}</strong> {shared('stale', 'STALE')}</span>
          </div>
          {visibleItems.length ? (
            <div className="wm-market-tv-list">
              {visibleItems.map((item) => (
                <MarketTvRow
                  key={item.id}
                  item={item}
                  active={(activeId || previewItem?.id) === item.id}
                  onPreview={() => setActiveId(item.id)}
                />
              ))}
            </div>
          ) : null}
        </div>
        {previewItem ? <MarketTvPreview key={previewItem.id} item={previewItem} /> : (
          <div className="wm-empty-state">
            <strong>{categoryLoading ? copy('loading', 'Market TV Wire loading.') : copy('warming', 'Market TV Wire warming.')}</strong>
            <em>{categoryError || copy('notReady', 'The selected channel category is not ready yet.')}</em>
          </div>
        )}
      </div>
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'market-tv-wire': {
    render: (ctx) => {
      const payload = ctx.runtimeData['market-tv-wire'] as RuntimeMarketTvWirePayload | undefined;
      return <MarketTvWirePanel payload={payload} />;
    },
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  snapshot: mediaSnapshot('market-tv-wire', 60),
  id: 'market-tv-wire',
  title: 'Market TV Wire',
  eyebrow: 'content',
  description: 'Live video sources ranked for market context.',
  size: 'wide',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 900000,
  limit: 60,
  fetchData: (context, limit) => fetchRuntimeMarketTvWire(limit, undefined, context?.signal),
});
