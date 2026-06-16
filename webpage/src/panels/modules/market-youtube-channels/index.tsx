import { useEffect, useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeMarketYoutubeChannels } from '@/services/api';
import type { RuntimeMarketTvWireItem, RuntimeMarketYoutubeChannelsPayload } from '@/types';
import { formatRelative } from '../../shared/formatters';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '../helpers';

const YOUTUBE_VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/;

function badgeLabel(payload?: RuntimeMarketYoutubeChannelsPayload | null) {
  const status = String(payload?.status || '').toLowerCase();
  const cacheMode = String(payload?.cacheMode || '').toLowerCase();
  if (cacheMode.includes('stale')) return 'STALE';
  if (status === 'warming') return 'WARM';
  if (status === 'empty') return 'EMPTY';
  if (status === 'degraded') return 'MIXED';
  return 'LIVE';
}

function panelStatus(payload?: RuntimeMarketYoutubeChannelsPayload | null): 'live' | 'muted' {
  const status = String(payload?.status || '').toLowerCase();
  return status === 'warming' || status === 'empty' ? 'muted' : 'live';
}

function itemTitle(item: RuntimeMarketTvWireItem) {
  return item.youtubeLiveTitle || item.displayName || item.name || 'YouTube source';
}

function channelName(item: RuntimeMarketTvWireItem) {
  return item.youtubeChannelName || item.displayName || item.sourceName || 'YouTube';
}

function categoryLabel(value?: string | null) {
  const category = String(value || 'other').toUpperCase();
  return category === 'GEO' ? 'GEO' : category;
}

function categoryToneClass(value?: string | null) {
  const category = String(value || 'all').toLowerCase().replace(/[^a-z0-9-]/g, '');
  return `tone-${category || 'all'}`;
}

function sourceLocation(item: RuntimeMarketTvWireItem) {
  return [item.region, item.country, item.language].filter(Boolean).join(' / ') || 'GLOBAL';
}

function youtubeVideoId(item?: RuntimeMarketTvWireItem | null) {
  const liveId = String(item?.youtubeLiveVideoId || '').trim();
  if (YOUTUBE_VIDEO_ID_RE.test(liveId)) return liveId;
  const fallbackId = String(item?.fallbackVideoId || '').trim();
  return YOUTUBE_VIDEO_ID_RE.test(fallbackId) ? fallbackId : '';
}

function hasPlayableYoutubeEmbed(item?: RuntimeMarketTvWireItem | null) {
  const mode = String(item?.youtubeEmbedMode || '').toLowerCase();
  return mode === 'live-video' || mode === 'video' || Boolean(youtubeVideoId(item));
}

function youtubeEmbedUrl(item?: RuntimeMarketTvWireItem | null) {
  if (!hasPlayableYoutubeEmbed(item)) return '';
  const embedded = String(item?.youtubeEmbedUrl || '').trim();
  if (embedded) return embedded;
  const videoId = youtubeVideoId(item);
  return videoId ? `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&mute=1&playsinline=1&rel=0&modestbranding=1` : '';
}

function probeLabel(item?: RuntimeMarketTvWireItem | null) {
  const status = String(item?.youtubeProbeStatus || '').toLowerCase();
  if (status === 'live') return 'LIVE';
  if (status === 'offline') return 'VIDEO';
  if (status === 'error') return 'FALLBACK';
  return 'OPEN';
}

function scoreLabel(value?: string | number | null) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? String(Math.round(numeric)) : '--';
}

function openExternal(url?: string | null) {
  const target = String(url || '').trim();
  if (!target) return;
  window.open(target, '_blank', 'noopener,noreferrer');
}

function MarketYoutubePlayer({ item }: { item: RuntimeMarketTvWireItem }) {
  const embedUrl = youtubeEmbedUrl(item);
  const videoId = youtubeVideoId(item);
  const externalUrl = item.externalUrl || item.sourceUrl || (videoId ? `https://www.youtube.com/watch?v=${videoId}` : null);
  return (
    <div className="wm-market-youtube-player">
      <header>
        <div>
          <span>{categoryLabel(item.category)} / {sourceLocation(item)} / {probeLabel(item)}</span>
          <strong>{itemTitle(item)}</strong>
        </div>
        <button type="button" onClick={() => openExternal(externalUrl)}>
          OPEN
        </button>
      </header>
      {embedUrl ? (
        <iframe
          className="wm-market-youtube-frame"
          src={embedUrl}
          title={itemTitle(item)}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          allowFullScreen
          referrerPolicy="strict-origin-when-cross-origin"
        />
      ) : (
        <div className="wm-market-youtube-fallback">
          <strong>{channelName(item)}</strong>
          <em>{item.marketUseCase || 'Open the YouTube channel externally. Current live embed is not verified.'}</em>
          <button type="button" onClick={() => openExternal(externalUrl)}>
            OPEN
          </button>
        </div>
      )}
    </div>
  );
}

function MarketYoutubeRow({
  item,
  active,
  onSelect,
}: {
  item: RuntimeMarketTvWireItem;
  active: boolean;
  onSelect: () => void;
}) {
  const tags = (item.matchedTerms?.length ? item.matchedTerms : item.marketTags || []).slice(0, 3);
  return (
    <button type="button" className={`wm-market-youtube-row ${active ? 'active' : ''}`} onClick={onSelect}>
      <span className={`wm-market-youtube-dot ${youtubeEmbedUrl(item) ? 'live' : 'ready'}`} />
      <div>
        <small>{categoryLabel(item.category)} / {probeLabel(item)}</small>
        <strong>{channelName(item)}</strong>
        <em>{item.marketUseCase || item.sourceName || 'Live video context.'}</em>
        {tags.length ? (
          <span className="wm-market-youtube-tags">
            {tags.map((tag) => <i key={`${item.id}-${tag}`}>{String(tag).toUpperCase()}</i>)}
          </span>
        ) : null}
      </div>
      <b>{scoreLabel(item.relevanceScore)}</b>
    </button>
  );
}

function MarketYoutubeChannelsPanel({ payload }: { payload?: RuntimeMarketYoutubeChannelsPayload | null }) {
  const [activeCategory, setActiveCategory] = useState('all');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [categoryPayload, setCategoryPayload] = useState<{ category: string; payload: RuntimeMarketYoutubeChannelsPayload } | null>(null);
  const [categoryLoading, setCategoryLoading] = useState(false);
  const [categoryError, setCategoryError] = useState<string | null>(null);
  const selectedPayload = activeCategory === 'all'
    ? payload
    : (categoryPayload?.category === activeCategory ? categoryPayload.payload : null);
  const items = selectedPayload?.items || [];
  const summary = payload?.summary || selectedPayload?.summary || {};
  const categories = payload?.categories || selectedPayload?.categories || [];
  const totalCount = Number(summary.total ?? payload?.selection?.total ?? items.length);
  const visibleItems = useMemo(() => items, [items]);
  const activeItem = visibleItems.find((item) => item.id === activeId) || null;
  const playerItem = activeItem || visibleItems.find((item) => youtubeEmbedUrl(item)) || visibleItems[0] || null;

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
    fetchRuntimeMarketYoutubeChannels(24, activeCategory)
      .then((nextPayload) => {
        if (cancelled) return;
        setCategoryPayload({ category: activeCategory, payload: nextPayload });
      })
      .catch((error) => {
        if (cancelled) return;
        setCategoryError(error instanceof Error ? error.message : 'Failed to load YouTube category');
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
      setActiveId((visibleItems.find((item) => youtubeEmbedUrl(item)) || visibleItems[0])?.id || null);
    }
  }, [activeId, visibleItems]);

  return (
    <Panel
      title="YOUTUBE MARKET TV"
      badge={badgeLabel(payload)}
      status={panelStatus(payload)}
      count={items.length || undefined}
      className="wm-market-panel wm-market-youtube-panel"
      dataPanelId="market-youtube-channels"
    >
      <div className="wm-market-youtube-layout">
        <aside className="wm-market-youtube-sidebar">
          <div className="wm-market-youtube-tabs">
            <button
              type="button"
              className={`${categoryToneClass('all')} ${activeCategory === 'all' ? 'active' : ''}`}
              onClick={() => setActiveCategory('all')}
            >
              ALL <span>{Number.isFinite(totalCount) ? totalCount : items.length}</span>
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
          <div className="wm-market-youtube-summary">
            <span><strong>{summary.liveReady ?? 0}</strong> LIVE</span>
            <span><strong>{summary.embedReady ?? 0}</strong> EMBED</span>
          </div>
          <div className="wm-market-youtube-list">
            {visibleItems.map((item) => (
              <MarketYoutubeRow
                key={item.id}
                item={item}
                active={(activeId || playerItem?.id) === item.id}
                onSelect={() => setActiveId(item.id)}
              />
            ))}
          </div>
        </aside>
        {playerItem ? <MarketYoutubePlayer item={playerItem} /> : (
          <div className="wm-empty-state">
            <strong>{categoryLoading ? 'YouTube TV loading.' : 'YouTube TV warming.'}</strong>
            <em>{categoryError || 'GCP seeded YouTube channel snapshot is not ready yet.'}</em>
          </div>
        )}
      </div>
      <footer className="wm-market-youtube-foot">
        <span>{formatRelative(selectedPayload?.generatedAt || payload?.generatedAt)}</span>
        <em>{selectedPayload?.cacheMode || payload?.cacheMode || 'seeded'}</em>
      </footer>
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'market-youtube-channels': {
    render: (ctx) => {
      const payload = ctx.runtimeData['market-youtube-channels'] as RuntimeMarketYoutubeChannelsPayload | undefined;
      return <MarketYoutubeChannelsPanel payload={payload} />;
    },
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'market-youtube-channels',
  title: 'YouTube Market TV',
  eyebrow: 'content',
  description: 'Curated YouTube live and video channels for market context.',
  size: 'wide',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 180000,
  fetchData: () => fetchRuntimeMarketYoutubeChannels(24),
});
