import { Panel } from '@/components/Panel';
import type { ContentItem } from '@/types';
import { useMemo, useState } from 'preact/hooks';
import type { PanelRenderMap, PanelRuntimeContext } from './types';
import { contentList } from './shared/renderers';
import { contentByType, focusedContent } from './shared/selectors';

type IntelTab = {
  id: 'news' | 'video' | 'report' | 'research';
  label: string;
};

const INTEL_TABS: IntelTab[] = [
  { id: 'news', label: 'News' },
  { id: 'video', label: 'Video' },
  { id: 'report', label: 'Reports' },
  { id: 'research', label: 'Research' },
];

function explicitContentType(item: ContentItem) {
  return String(item.contentType || '').trim().toLowerCase();
}

function smartContentByType(items: ContentItem[], tab: IntelTab['id']) {
  if (tab === 'news') return items;
  return items.filter((item) => {
    const explicit = explicitContentType(item);
    if (explicit === tab) return true;
    const source = String(item.source || '').toLowerCase();
    const url = String(item.url || '').toLowerCase();
    if (tab === 'video') {
      return /youtube|youtu\.be|vimeo|twitch\.tv/.test(`${source} ${url}`);
    }
    if (tab === 'report') {
      return /\.pdf($|[?#])|annual-report|whitepaper|research-report/.test(url);
    }
    return /arxiv\.org|ssrn\.com|nber\.org|papers\.ssrn/.test(`${source} ${url}`);
  });
}

function topSources(items: ContentItem[]) {
  const counts = new Map<string, number>();
  items.forEach((item) => {
    const source = String(item.source || item.contentType || 'intel').trim();
    if (!source) return;
    counts.set(source, (counts.get(source) || 0) + 1);
  });
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 5);
}

function providerMix(items: ContentItem[]) {
  const counts = new Map<string, number>();
  items.forEach((item) => {
    const provider = String(item.provider || 'rss').trim().toUpperCase();
    counts.set(provider, (counts.get(provider) || 0) + 1);
  });
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function topicMix(items: ContentItem[]) {
  const counts = new Map<string, number>();
  items.forEach((item) => {
    const topic = String(item.topicId || '').trim().toUpperCase();
    if (!topic) return;
    counts.set(topic, (counts.get(topic) || 0) + 1);
  });
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 4);
}

function sourceCoverage(items: ContentItem[]) {
  return new Set(items.map((item) => String(item.source || '').trim()).filter(Boolean)).size;
}

function RelatedIntelPanel({ ctx }: { ctx: PanelRuntimeContext }) {
  const [activeTab, setActiveTab] = useState<IntelTab['id']>('news');
  const items = focusedContent(ctx);
  const tabItems = useMemo(() => Object.fromEntries(
    INTEL_TABS.map((tab) => [tab.id, smartContentByType(items, tab.id)]),
  ) as Record<IntelTab['id'], ReturnType<typeof contentByType>>, [items]);
  const visibleItems = tabItems[activeTab] || [];
  const activeLabel = INTEL_TABS.find((tab) => tab.id === activeTab)?.label || 'Intel';
  const emptyMessage = activeTab === 'news'
    ? 'No news intel for this market yet.'
    : `No explicit ${activeLabel.toLowerCase()} intel for this market yet. Runtime RSS news stays under News.`;
  const sources = useMemo(() => topSources(visibleItems), [visibleItems]);
  const providers = useMemo(() => providerMix(items), [items]);
  const topics = useMemo(() => topicMix(items), [items]);
  const uniqueSources = useMemo(() => sourceCoverage(items), [items]);
  const sourceMode = ctx.bundle?.content?.sourceMode || 'runtime-intel';

  return (
    <Panel
      title="RELATED INTEL"
      badge={sourceMode}
      status="live"
      count={items.length}
      className="wm-market-panel wm-content-feed-panel wm-related-news-panel wm-related-intel-panel"
    >
      <div className="wm-intel-coverage-row" aria-label="Related intel source coverage">
        <span>
          <b>{uniqueSources}</b>
          sources
        </span>
        {providers.map(([provider, count]) => (
          <span key={provider}>
            <b>{count}</b>
            {provider}
          </span>
        ))}
        {topics.map(([topic, count]) => (
          <span key={topic}>
            <b>{count}</b>
            {topic}
          </span>
        ))}
      </div>
      <div className="wm-intel-filter-tabs" role="tablist" aria-label="Related intel content types">
        {INTEL_TABS.map((tab) => (
          <button
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? 'active' : ''}
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            role="tab"
            type="button"
          >
            <span>{tab.label}</span>
            <b>{tabItems[tab.id]?.length || 0}</b>
          </button>
        ))}
      </div>
      {sources.length ? (
        <div className="wm-intel-source-strip" aria-label="Related intel source mix">
          {sources.map(([source, count]) => (
            <span key={source}>
              <b>{source}</b>
              <em>{count}</em>
            </span>
          ))}
        </div>
      ) : null}
      {contentList(visibleItems, emptyMessage, 20)}
    </Panel>
  );
}

export const contentPanelRenderers: PanelRenderMap = {
  'related-news': {
    render: (ctx) => <RelatedIntelPanel ctx={ctx} />,
  },
  'related-video': {
    render: (ctx) => (
      <Panel title="VIDEO FEED" badge="VIDEO" status="muted" count={contentByType(focusedContent(ctx), 'video').length} className="wm-market-panel wm-content-feed-panel wm-related-video-panel">
        {contentList(contentByType(focusedContent(ctx), 'video'), 'No linked videos yet.')}
      </Panel>
    ),
  },
  'report-feed': {
    render: (ctx) => (
      <Panel title="REPORT FEED" badge="REPORT" status="muted" count={contentByType(ctx.latestContent, 'report').length} className="wm-market-panel wm-content-feed-panel wm-report-feed-panel">
        {contentList(contentByType(ctx.latestContent, 'report'), 'No linked reports yet.')}
      </Panel>
    ),
  },
  'research-feed': {
    render: (ctx) => (
      <Panel title="RESEARCH FEED" badge="RESEARCH" status="muted" count={contentByType(ctx.latestContent, 'research').length} className="wm-market-panel wm-content-feed-panel wm-research-feed-panel">
        {contentList(contentByType(ctx.latestContent, 'research'), 'No linked research yet.')}
      </Panel>
    ),
  },
};
