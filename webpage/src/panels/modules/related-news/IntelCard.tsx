import { Component, type ComponentChildren } from 'preact';
import { useState } from 'preact/hooks';
import { useI18n } from '@/services/i18n';
import type { IntelPayload } from './model';

export function IntelCard({ item, scope }: { item: IntelPayload['items'][number]; scope: 'global' | 'market' }) {
  const i18n = useI18n();
  const copy = (en: string, cn: string) => i18n.locale.startsWith('zh') ? cn : en;
  const [expanded, setExpanded] = useState(false);
  const kind = item.sourceKind === 'alert' ? copy('Weather alert', '天气警报')
    : item.sourceKind === 'observation' ? copy('Observation', '观测更新')
    : item.sourceKind === 'official_release' ? copy('Official', '公告') : copy('Reports', '报道');
  return <article className="wm-free-intel-card" data-intel-item-id={item.id} data-intel-item-version={item.content_version}>
    <div className="wm-free-intel-meta"><strong>{item.source}</strong><span>{kind}</span></div>
    {item.author && <p>{copy('By', '作者')} {item.author}</p>}
    <a className={`wm-news-title ${expanded ? '' : 'wm-intel-clamped'}`} href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a>
    {item.summary && <p className={`wm-intel-summary ${expanded ? '' : 'wm-intel-clamped'}`}>{expanded ? item.excerptFull || item.summary : item.summary} <small>{item.excerptOrigin === 'structured' ? copy('Data summary', '数据整理') : copy('Excerpt', '节选')}</small></p>}
    <button type="button" className="wm-intel-expand" aria-expanded={expanded} onClick={() => setExpanded(old => !old)}>{expanded ? copy('Collapse', '收起') : copy('Show full card text', '展开卡片文字')}</button>
    <div className="wm-news-meta"><time dateTime={item.publishedAt || undefined}>{item.publishedAt ? i18n.formatDateTime(item.publishedAt) : copy('Publication time unknown', '发布时间未知')}</time><a href={item.url} target="_blank" rel="noopener noreferrer">{copy('Read source', '阅读原文')}</a></div>
    {scope === 'market' && <p className="wm-intel-relation"><b>{item.relation === 'direct' ? copy('Direct relation', '直接关联') : copy('Background only', '仅背景关联')}</b> · {item.relationReason}</p>}
    {item.sourceStatus && !['ok', 'unchanged', 'healthy_empty'].includes(item.sourceStatus) && <p>{copy('Source temporarily unavailable or stale', '来源暂不可用或已过期')}</p>}
    {(item.licenseUrl || item.policyUrl) && <a className="wm-intel-license" href={item.licenseUrl || item.policyUrl} target="_blank" rel="noopener noreferrer">{item.licenseUrl === 'https://creativecommons.org/licenses/by/3.0/' ? 'CC BY 3.0' : copy('Source use policy', '来源使用政策')}</a>}
  </article>;
}

/** A rendering fault is local to this card; identity/version resets its recovery. */
export class IntelCardBoundary extends Component<{ children: ComponentChildren }, { failed: boolean }> {
  state = { failed: false };
  componentDidCatch() { this.setState({ failed: true }); }
  render() { return this.state.failed ? <article className="wm-free-intel-card" role="status">Unable to display this item / 此条内容显示失败</article> : this.props.children; }
}
