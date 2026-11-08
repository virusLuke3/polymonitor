import type { ComponentChildren } from 'preact';
import type { SportsPayload } from './model';
import './style.css';

export function Frame({ data, children, className = '' }: { data: SportsPayload | undefined; children: ComponentChildren; className?: string }) {
  if (!data) return <p className="sportsx-note">Loading sports evidence…</p>;
  if (data.status === 'unavailable') return <p className="sportsx-note sportsx-warning">The source has not published a usable snapshot yet.</p>;
  return <div className={`sportsx-root ${className}`}>{data.sources.some(s => s.stale || s.error) && <p className="sportsx-warning">Source update delayed; retained observations are shown.</p>}{children}<details className="sportsx-evidence"><summary>Sources and coverage</summary><p>{data.coverage}</p>{data.sources.map(s => <p key={s.id}>{s.label} · {s.lastSuccessAt ? new Date(s.lastSuccessAt).toLocaleString() : 'No successful observation'}{s.error ? ` · ${s.error}` : ''}</p>)}</details></div>;
}
export function Tabs({ values, selected, onChange }: { values: string[]; selected: string; onChange: (s: string) => void }) {
  return <div className="sportsx-tabs" role="tablist">{values.map(v => <button key={v} type="button" role="tab" aria-selected={v === selected} onClick={() => onChange(v)}>{v}</button>)}</div>;
}
export function Spark({ values, label }: { values: (number | null)[]; label: string }) {
  const good = values.filter((v): v is number => v !== null);
  if (!good.length) return <p className="sportsx-note">This replay has no {label.toLowerCase()} series.</p>;
  const low = Math.min(0, ...good), high = Math.max(1, ...good), y = (v: number) => 82 - (v - low) / (high - low) * 72;
  // Null observations break the path instead of drawing invented segments.
  let open = false;
  const path = values.map((v, i) => { if (v === null) { open = false; return ''; } const cmd = open ? 'L' : 'M'; open = true; return `${cmd}${8 + i / Math.max(1, values.length - 1) * 284},${y(v)}`; }).join(' ');
  return <svg className="sportsx-spark" viewBox="0 0 300 96" role="img" aria-label={label}><line x1="8" x2="292" y1={y(0)} y2={y(0)} className="sportsx-axis"/><path d={path} fill="none" stroke="currentColor" strokeWidth="2"/><text x="8" y="94">0 min</text><text x="292" y="94" textAnchor="end">{values.length - 1} min</text></svg>;
}
