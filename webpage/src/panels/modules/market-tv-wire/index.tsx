import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeMarketTvWire } from '@/services/api';
import type { RuntimeMarketTvWireItem, RuntimeMarketTvWirePayload } from '@/types';
import { formatRelative } from '../../shared/formatters';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '../helpers';

type PlaybackState = 'connecting' | 'playing' | 'waiting' | 'blocked' | 'external';

function badgeLabel(payload?: RuntimeMarketTvWirePayload | null) {
  const status = String(payload?.status || '').toLowerCase();
  const cacheMode = String(payload?.cacheMode || '').toLowerCase();
  if (cacheMode.includes('stale')) return 'STALE';
  if (status === 'warming') return 'WARM';
  if (status === 'degraded') return 'DEGRADED';
  if (status === 'empty') return 'EMPTY';
  return 'LIVE';
}

function panelStatus(payload?: RuntimeMarketTvWirePayload | null): 'live' | 'muted' {
  const status = String(payload?.status || '').toLowerCase();
  return status === 'warming' || status === 'empty' ? 'muted' : 'live';
}

function scoreLabel(value?: string | number | null) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '--';
  return String(Math.round(numeric));
}

function itemTitle(item: RuntimeMarketTvWireItem) {
  return item.displayName || item.name || 'Live video source';
}

function categoryLabel(value?: string | null) {
  const category = String(value || 'other').toUpperCase();
  if (category === 'GEO') return 'GEO';
  return category;
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

function sourceLocation(item: RuntimeMarketTvWireItem) {
  return [item.region, item.country, item.language].filter(Boolean).join(' / ') || 'GLOBAL';
}

function openExternal(url?: string | null) {
  const target = String(url || '').trim();
  if (!target) return;
  window.open(target, '_blank', 'noopener,noreferrer');
}

function isHlsPreviewable(item?: RuntimeMarketTvWireItem | null) {
  return String(item?.sourceType || '').toLowerCase() === 'hls' && Boolean(String(item?.hlsUrl || '').trim());
}

function MarketTvPreview({ item }: { item: RuntimeMarketTvWireItem }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsUrl = String(item.hlsUrl || '').trim();
  const [playbackState, setPlaybackState] = useState<PlaybackState>(hlsUrl ? 'connecting' : 'external');

  useEffect(() => {
    const video = videoRef.current;
    let cancelled = false;
    let destroyHls: (() => void) | null = null;

    setPlaybackState(hlsUrl ? 'connecting' : 'external');
    if (!video || !hlsUrl) return undefined;

    const markPlaying = () => setPlaybackState('playing');
    const markWaiting = () => setPlaybackState('waiting');
    const markBlocked = () => setPlaybackState('blocked');
    video.addEventListener('playing', markPlaying);
    video.addEventListener('waiting', markWaiting);
    video.addEventListener('error', markBlocked);

    const startNative = () => {
      video.src = hlsUrl;
      video.load();
      video.play().catch(() => setPlaybackState('waiting'));
    };

    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      startNative();
    } else {
      import('hls.js')
        .then(({ default: Hls }) => {
          if (cancelled) return;
          if (!Hls.isSupported()) {
            setPlaybackState('blocked');
            return;
          }
          const hls = new Hls({
            enableWorker: true,
            lowLatencyMode: true,
            liveSyncDurationCount: 3,
          });
          destroyHls = () => hls.destroy();
          hls.loadSource(hlsUrl);
          hls.attachMedia(video);
          hls.on(Hls.Events.MANIFEST_PARSED, () => {
            video.play().catch(() => setPlaybackState('waiting'));
          });
          hls.on(Hls.Events.ERROR, (_event, data) => {
            if (data?.fatal) setPlaybackState('blocked');
          });
        })
        .catch(() => setPlaybackState('blocked'));
    }

    return () => {
      cancelled = true;
      video.removeEventListener('playing', markPlaying);
      video.removeEventListener('waiting', markWaiting);
      video.removeEventListener('error', markBlocked);
      destroyHls?.();
      video.pause();
      video.removeAttribute('src');
      video.load();
    };
  }, [hlsUrl]);

  if (!hlsUrl) {
    return (
      <div className="wm-market-tv-preview external">
        <div>
          <span>{sourceTypeLabel(item.sourceType)}</span>
          <strong>{itemTitle(item)}</strong>
          <em>{item.marketUseCase || item.sourceName || 'Open official live source.'}</em>
        </div>
        <button type="button" onClick={() => openExternal(item.externalUrl || item.sourceUrl)}>
          OPEN
        </button>
      </div>
    );
  }

  return (
    <div className="wm-market-tv-preview">
      <div className="wm-market-tv-preview-head">
        <div>
          <strong>{itemTitle(item)}</strong>
          <span>{categoryLabel(item.category)} / {sourceLocation(item)} / {sourceTypeLabel(item.sourceType)}</span>
        </div>
        <em className={`wm-market-tv-playback ${playbackState}`}>{playbackState.toUpperCase()}</em>
        <button type="button" onClick={() => openExternal(item.externalUrl || item.sourceUrl || item.hlsUrl)}>
          OPEN
        </button>
      </div>
      <div className="wm-market-tv-stage">
        <video ref={videoRef} className="wm-market-tv-video" controls muted playsInline />
        {playbackState === 'blocked' ? (
          <button
            type="button"
            className="wm-market-tv-fallback"
            onClick={() => openExternal(item.externalUrl || item.sourceUrl || item.hlsUrl)}
          >
            STREAM BLOCKED · OPEN SOURCE
          </button>
        ) : null}
      </div>
    </div>
  );
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
  const hlsReady = isHlsPreviewable(item);
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
          <p>{item.marketUseCase || item.sourceName || 'Live source for market context.'}</p>
          {tags.length ? (
            <div className="wm-market-tv-tags">
              {tags.map((tag) => <span key={`${item.id}-${tag}`}>{String(tag).toUpperCase()}</span>)}
            </div>
          ) : null}
        </div>
        <div className="wm-market-tv-score">
          <strong>{scoreLabel(item.relevanceScore)}</strong>
          <span>{hlsReady ? 'WATCH' : 'OPEN'}</span>
          <em>{formatRelative(item.lastCheckedAt)}</em>
        </div>
      </button>
    </article>
  );
}

function MarketTvWirePanel({ payload }: { payload?: RuntimeMarketTvWirePayload | null }) {
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
  const visibleItems = useMemo(() => items, [items]);
  const activeItem = visibleItems.find((item) => item.id === activeId) || null;
  const previewItem = activeItem || visibleItems.find(isHlsPreviewable) || visibleItems[0] || null;

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
        setCategoryError(error instanceof Error ? error.message : 'Failed to load category');
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
      setActiveId((visibleItems.find(isHlsPreviewable) || visibleItems[0])?.id || null);
    }
  }, [activeId, visibleItems]);

  return (
    <Panel
      title="MARKET TV WIRE"
      titleControls={(
        <button
          type="button"
          className="wm-panel-help-button"
          aria-label="Explain Market TV Wire panel"
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
          <strong>Market TV Wire</strong>
          <p>GCP-seeded live video sources ranked for Polymarket context. Stale snapshots stay visible when source refresh fails.</p>
        </div>
      ) : null}
      className="wm-market-panel wm-market-tv-panel"
      dataPanelId="market-tv-wire"
    >
      <div className="wm-market-tv-layout">
        <div className="wm-market-tv-control-rail">
          <div className="wm-market-tv-tabs">
            <button type="button" className={activeCategory === 'all' ? 'active' : ''} onClick={() => setActiveCategory('all')}>
              ALL <span>{items.length}</span>
            </button>
            {categories.map((category) => (
              <button
                key={category.id}
                type="button"
                className={activeCategory === category.id ? 'active' : ''}
                onClick={() => setActiveCategory(category.id)}
              >
                {category.label} <span>{category.count}</span>
              </button>
            ))}
          </div>
          <div className="wm-market-tv-summary">
            <span><strong>{summary.liveReady ?? 0}</strong> READY</span>
            <span><strong>{summary.marketMatched ?? 0}</strong> MATCHED</span>
            <span><strong>{summary.regions ?? 0}</strong> REGIONS</span>
            <span><strong>{summary.staleCount ?? 0}</strong> STALE</span>
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
        {previewItem ? <MarketTvPreview item={previewItem} /> : (
          <div className="wm-empty-state">
            <strong>{categoryLoading ? 'Market TV Wire loading.' : 'Market TV Wire warming.'}</strong>
            <em>{categoryError || 'GCP seed snapshot or selected channel category is not ready yet.'}</em>
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
  id: 'market-tv-wire',
  title: 'Market TV Wire',
  eyebrow: 'content',
  description: 'GCP-seeded live video sources ranked for market context.',
  size: 'wide',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 180000,
  fetchData: () => fetchRuntimeMarketTvWire(60),
});
