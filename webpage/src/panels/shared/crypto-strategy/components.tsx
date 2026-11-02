import type { ComponentChildren } from 'preact';
import { Panel, PanelLoading } from '@/components/Panel';
import { useI18n } from '@/services/i18n';
import { PanelDataControls } from '@/panels/shared/PanelDataControls';
import { ASSETS, marketUrl, validPoints, type Point, type Reference } from './model';
import { useCryptoAsset, useCryptoInputs } from './resource';
import './styles.css';

export const fmt = (value: number | null | undefined, digits = 2) => value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits });
export const compact = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? '—' : new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 }).format(value);
export const time = (value: string | number | undefined | null) => value == null || !Number.isFinite(new Date(value).getTime()) ? '—' : new Date(value).toLocaleTimeString([], { hour:'2-digit', minute:'2-digit', second:'2-digit' });
export function useCopy() { const { locale } = useI18n(); return (zh: string, en: string) => locale.startsWith('zh') ? zh : en; }

export function Frame({ id, title, badge, children, assets = true, filters }: {id: string; title: string; badge: string; children: ComponentChildren; assets?: boolean; filters?: ComponentChildren}) {
  const feed = useCryptoInputs(), [asset, select] = useCryptoAsset(), t = useCopy();
  return <Panel title={title} badge={badge} status="muted" dataPanelId={id} className="wm-market-panel wm-cstrategy-panel"
    controls={<PanelDataControls fetching={feed.status.fetching} onRefresh={() => void feed.refresh()}>
      <p>{t('快照','Snapshot')} {feed.data?.generatedAt ? new Date(feed.data.generatedAt).toLocaleString() : '—'}</p>
      <p>{t('检查','Checked')} {time(feed.status.checkedAt)}</p>
    </PanelDataControls>}>
    {(assets || filters) && <div className="wm-cstrategy-filter-bar">
      {assets && <div className="wm-panel-tabs" aria-label={t('共享币种选择','Shared asset selection')}>{ASSETS.map(a => <button key={a} aria-pressed={asset===a} onClick={() => select(a)}>{a}</button>)}</div>}
      {filters}
    </div>}
    {feed.loading && <PanelLoading/>}
    {(feed.error || feed.status.phase === 'stale') && <p className="wm-cstrategy-notice">{t('数据延迟或读取失败，保留原始时间。','Delayed or unavailable data; original timestamps retained.')}</p>}
    {children}
  </Panel>;
}

export function Stats({items}: {items: {label: string; value: string}[]}) {
  return <div className="wm-cstrategy-stats">{items.map(({label,value}) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>;
}
export function Notice({children}: {children: ComponentChildren}) { return <p className="wm-cstrategy-notice">{children}</p>; }

export function Series({points = [], label, color = 'var(--ds-color-info)', domain, maxGapMs = 120000}: {points?: Point[]; label: string; color?: string; domain?: [number,number]; maxGapMs?: number}) {
  const rows = validPoints(points), t = useCopy();
  if (rows.length < 2) return <div className="wm-cstrategy-chart-empty">{label} · {t('历史样本不足','Insufficient history')}</div>;
  const left = domain?.[0] ?? rows[0]!.t, right = domain?.[1] ?? rows[rows.length-1]!.t;
  const min = Math.min(...rows.map(p=>p.v)), max = Math.max(...rows.map(p=>p.v));
  const y = (v:number) => 72 - (v-min)/(max-min || 1)*60;
  const segments: string[][] = [[]];
  rows.forEach((p,i) => {
    if (i && p.t - rows[i-1]!.t > maxGapMs) segments.push([]);
    segments[segments.length-1]!.push(`${8+(p.t-left)/(right-left || 1)*284},${y(p.v)}`);
  });
  const axis = (stamp: number) => right-left > 86400000 ? new Date(stamp).toLocaleDateString([], {month:'short',day:'numeric'}) : time(stamp);
  return <figure className="wm-cstrategy-chart"><figcaption><span>{label}</span><strong>{fmt(rows[rows.length-1]?.v, 4)}</strong></figcaption>
    <svg viewBox="0 0 300 84" role="img" aria-label={label}><path d="M8 12H292M8 42H292M8 72H292" className="wm-cstrategy-grid"/>{segments.map((p,i)=><polyline key={i} points={p.join(' ')} fill="none" stroke={color} strokeWidth="1.6"/>)}</svg>
    <div className="wm-cstrategy-meta"><span>{axis(left)}</span><span>{axis(right)}</span></div>
  </figure>;
}

export function MarketLink({reference}: {reference?: Reference}) {
  const url = marketUrl(reference), t = useCopy(), market=reference?.market;
  if (!url || !market || market.ends_at_ms <= Date.now()) return <p className="wm-cstrategy-meta">{t('当前没有核验通过的合约关联','No verified current contract binding')}</p>;
  return <div className="wm-cstrategy-market"><a href={url} target="_blank" rel="noopener noreferrer">{market.asset} · {t('本轮涨跌合约','Current UP/DOWN market')} ↗</a>
    <span>{t('截止','Ends')} {time(market.ends_at_ms)}</span>
    {Object.entries(reference?.quotes || {}).map(([side,q]) => <span key={side}>{side} {fmt(q.bid*100,1)} / {fmt(q.ask*100,1)}¢ · {time(q.observedAt)}</span>)}
    {!Object.keys(reference?.quotes || {}).length && <span>{t('PM 盘口暂缺','PM book unavailable')}</span>}
  </div>;
}
