import { useMemo } from 'preact/hooks';
import { useI18n } from '@/services/i18n';
import type { CountryGeometryIndex } from '../domain/countryGeometry';
import type { GeoEvent } from '../domain/types';
import type { MapCountryTarget } from '../renderer/MapRenderer';
import { InspectorFrame } from './InspectorFrame';
import { eventMatchesCountry } from '../state/selectors';

export function CountryBrief({ country, index, events, onClose, onEvent, onFit, onFilter, returnFocusTarget }: {
  country: MapCountryTarget; index?: CountryGeometryIndex | null; events: GeoEvent[]; onClose: () => void;
  onEvent: (id: string) => void; onFit: () => void; onFilter: () => void; returnFocusTarget?: HTMLElement | null;
}) {
  const { locale } = useI18n(); const zh = locale === 'zh';
  const records = useMemo(() => [...new Map(events.filter(e => eventMatchesCountry(e, country.iso2, index ?? null))
    .map(e => [e.id, e])).values()]
    .sort((a, b) => (b.updatedAt || b.occurredAt || '').localeCompare(a.updatedAt || a.occurredAt || '')), [events, country.iso2, index]);
  const categories = [...new Set(records.map(e => e.category))];
  const sources = [...new Set(records.flatMap(e => e.sources.map(s => s.provider)))];
  return <InspectorFrame identity={`country:${country.iso2}`} onClose={onClose} returnFocusTarget={returnFocusTarget}>
    <header className="wm-event-inspector-header"><h2 id="wm-event-inspector-title" tabIndex={-1}>{country.name} · {zh ? '国家简报' : 'Country brief'}</h2>
      <p>{zh ? '当前筛选下已加载的事件与新闻；不是全国完整统计。' : 'Loaded events and news under current filters; not complete national coverage.'}</p>
      <button type="button" onClick={onFit}>{zh ? '定位国家' : 'Fit country'}</button> <button type="button" onClick={onFilter}>{zh ? '筛选此国家' : 'Filter country'}</button>
    </header>
    <section className="wm-event-inspector-section"><h3>{zh ? '汇总' : 'Summary'}</h3>
      <p>{records.length} {zh ? '条唯一记录' : 'unique records'} · {sources.length} {zh ? '个来源' : 'sources'}</p>
      <dl className="wm-event-inspector-fields">{categories.map(category => <div key={category}><dt>{category}</dt><dd>{records.filter(e => e.category === category).length}</dd></div>)}</dl>
      <p>{sources.join(' · ') || (zh ? '当前无匹配来源' : 'No matching sources loaded')}</p>
    </section>
    <section className="wm-event-inspector-section"><h3>{zh ? '事件与新闻时间线' : 'Events & news timeline'}</h3>
      {!records.length ? <p>{zh ? '当前筛选下无记录，不代表没有事件。' : 'No records under current filters; this does not imply no events.'}</p> : null}
      <ol className="wm-country-timeline">{records.map(e => <li key={e.id}>
        <time>{(e.updatedAt || e.occurredAt || '').replace('T', ' ').slice(0, 19) || (zh ? '时间未知' : 'Time unknown')}</time>
        <button type="button" onClick={() => onEvent(e.id)}>{e.title}</button>
        <small>{e.sources.map(s => `${s.provider} · ${s.freshness || 'unknown'}`).join(' / ')}</small>
      </li>)}</ol>
    </section>
  </InspectorFrame>;
}
