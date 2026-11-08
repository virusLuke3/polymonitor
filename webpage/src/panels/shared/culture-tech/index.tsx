import type { ComponentChildren } from 'preact';
import { Panel } from '@/components/Panel';
import { DisclosureControls } from '../official-disclosures';
import { isBasePayload, record, type BasePayload } from '../external/resource';
import './styles.css';

export type Item = { id: string; title: string; [key: string]: unknown };
export type CulturePayload = BasePayload & { items: Item[]; publishedAt?: string; period?: string; show?: string; season?: number; documentUrl?: string };
export function valid(value: unknown): value is CulturePayload {
  const object = record(value) ? value : null;
  return isBasePayload(value) && object !== null && Array.isArray(object.items) && object.items.length <= 100
    && object.items.every(r => record(r) && typeof r.id === 'string' && typeof r.title === 'string'
      && Object.values(r).every(v => typeof v !== 'number' || Number.isFinite(v)));
}
export const s = (v: unknown) => typeof v === 'string' ? v : '';
export const n = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? v : null;
export const num = (v: unknown, digits = 0) => n(v) === null ? '—' : new Intl.NumberFormat('en', { maximumFractionDigits: digits }).format(n(v)!);
export const compact = (v: unknown) => n(v) === null ? '—' : new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 2 }).format(n(v)!);
export const date = (v: unknown) => s(v).slice(0, 10) || 'Date unavailable';
export function EvidenceLink({ row, children }: { row: Item; children?: ComponentChildren }) {
  const url = s(row.url);
  return /^https:\/\//.test(url) ? <a href={url} target="_blank" rel="noreferrer">{children || row.title} ↗</a> : <span>{children || row.title}</span>;
}
export function Tabs({ values, value, onChange }: { values: string[]; value: string; onChange: (value: string) => void }) {
  return <div className="wm-panel-tabs">{values.map(v => <button key={v} aria-pressed={v === value} onClick={() => onChange(v)}>{v}</button>)}</div>;
}
export function Frame({ id, title, data, children, tone = 'cyan' }: { id: string; title: string; data?: CulturePayload; children: ComponentChildren; tone?: string }) {
  return <Panel title={title} dataPanelId={id} className={`wm-ct-panel wm-ct-${tone}`} controls={<DisclosureControls><p>{data?.coverage}</p>{data?.sources.map(source => <p key={source.id}>{source.label} · acquired {source.lastSuccessAt || 'not yet'}</p>)}</DisclosureControls>}>
    <div className="wm-ct-body">
      {!data ? <p className="wm-ct-note">Loading the published source snapshot…</p> : <>
        {data.sources.some(source => source.error || source.stale || !source.usable) && <p className="wm-ct-warning">{data.sources.filter(source => source.error || source.stale || !source.usable).map(source => `${source.label || source.id}: ${source.error === 'not-configured' ? 'source not configured' : source.error || (source.usable ? 'retained older observation' : 'no usable observation')}`).join(' · ')}</p>}
        {data.items.length ? children : <p className="wm-ct-note">{data.status === 'unavailable' ? 'The source has not supplied a usable snapshot.' : 'No records in the acquired source scope.'}</p>}
      </>}
    </div>
  </Panel>;
}
