import type { ComponentChildren } from 'preact';
import { Panel } from '@/components/Panel';
import { useI18n } from '@/services/i18n';
import type { MarketWideAiInsightLens, MarketWideTheme, MarketWideWatchItem } from '@/types';
import type { InsightView } from './model';
import '@/styles/ai-market-panels.css';

export function InsightFrame({ view, lens, title, count, children }: {
  view: InsightView; lens: MarketWideAiInsightLens; title: string; count: number; children: ComponentChildren;
}) {
  const { t, formatDateTime } = useI18n();
  const { insight } = view;
  return <Panel title={title} badge={t(`marketInsights.${view.badge}`)} status={view.healthy ? 'live' : 'muted'}
    count={insight ? count : undefined} className={`wm-market-panel wm-ai-market-panel wm-ai-market-wide-panel wm-ai-${lens}`}>
    <div className="wm-ai-insights" data-generation-mode={view.mode} data-stale={view.stale}>
      <section className="wm-ai-insight-hero">
        <div className="wm-ai-insight-source"><span>{t('marketInsights.scope')}</span><b>{insight ? t(`marketInsights.${view.mode}`) : t('marketInsights.unavailable')}</b></div>
        <p>{insight?.brief || t('marketInsights.noSnapshot')}</p>
        <small className="wm-ai-insight-timestamp">{t('marketInsights.updated')}: {view.generatedAt ? <time dateTime={view.generatedAt}>{formatDateTime(view.generatedAt)}</time> : t('marketInsights.unknownTime')}</small>
      </section>
      {insight && view.mode === 'rules' ? <p className="wm-ai-insight-notice" role="status">{t('marketInsights.rulesNotice')}</p> : null}
      {view.stale ? <p className="wm-ai-insight-notice" role="status">{t('marketInsights.staleNotice')}</p> : null}
      {insight ? children : null}
      {insight?.evidence?.length ? <section className="wm-ai-insight-evidence" aria-label={t('marketInsights.evidence')}>
        {insight.evidence.map((item, index) => <span key={index}>{item}</span>)}
      </section> : null}
      {insight?.limitations?.length ? <details className="wm-ai-insight-limitations"><summary>{t('marketInsights.limitations')}</summary>
        <ul>{insight.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>
      </details> : null}
    </div>
  </Panel>;
}

export function InsightCards({ title, items, empty }: { title: string; items: MarketWideTheme[]; empty: string }) {
  return <section className="wm-ai-insight-list" aria-label={title}>
    <div className="wm-ai-insight-section-head"><span>{title}</span><em>{items.length}</em></div>
    {items.length ? items.map((item, index) => <article className="wm-ai-insight-card" key={index}>
      <div className="wm-ai-insight-card-head"><span>{item.label}</span><b>{item.evidence}</b></div>
      <strong>{item.title}</strong><p>{item.summary}</p>
    </article>) : <p className="wm-ai-insight-notice">{empty}</p>}
  </section>;
}

export function InsightWatchlist({ items }: { items: MarketWideWatchItem[] }) {
  const { t } = useI18n();
  return items.length ? <section className="wm-ai-insight-list wm-ai-watchlist" aria-label={t('marketInsights.watch')}>
    <div className="wm-ai-insight-section-head"><span>{t('marketInsights.watch')}</span></div>
    {items.map((item, index) => <article className="wm-ai-insight-watch" key={index}>
      <span>{item.horizon}</span><strong>{item.title}</strong><p>{item.reason}</p>
    </article>)}
  </section> : null;
}
