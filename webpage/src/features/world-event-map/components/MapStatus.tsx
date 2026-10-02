import type { WorldEventSourceStatus } from '../data/sourceStatus';
import { useI18n } from '@/services/i18n';

export function MapStatus({ sources }: { sources: WorldEventSourceStatus[] }) {
  const { locale } = useI18n();
  const issues = sources.filter(source => ['error', 'unavailable', 'degraded', 'stale', 'partial', 'renderer-limited'].includes(source.phase || source.status));
  return <details className="wm-map-source-details">
    <summary>{locale === 'zh' ? '来源' : 'Sources'} · {sources.length}{issues.length ? ` · ${issues.length} ${locale === 'zh' ? '需关注' : 'need attention'}` : ''}</summary>
    <span className="wm-map-source-statuses" aria-label="Map source status">
      {sources.map(source => <span className={`wm-map-source-status is-${source.status}`} key={source.key} title={source.message || `${source.label}: ${source.status}`}>
        <b>{source.label}</b><em>{(source.phase || source.status).toUpperCase()}</em>{source.status !== 'loading' ? <small>{source.eventCount}</small> : null}
      </span>)}
    </span>
    <ul className="wm-map-source-notes">{sources.filter(s => s.message).map(source => <li key={source.key}><b>{source.label}</b> · {source.message}
      {source.key === 'gpsjam' ? <> · <a href="https://gpsjam.org/data/manifest.csv" target="_blank" rel="noreferrer">GPSJAM source catalog</a></> : null}
    </li>)}</ul>
  </details>;
}
