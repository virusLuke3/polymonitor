import { usePanelRuntimeView } from '../PanelRuntimeView';
import { useI18n } from '@/services/i18n';
import './snapshot-controls.css';

export function SnapshotControls({ generatedAt }: { generatedAt?: string }) {
  const view = usePanelRuntimeView(), i18n = useI18n(), cn = i18n.locale.startsWith('zh');
  if (!view) return null;
  const checked = view.status?.checkedAt ? new Date(view.status.checkedAt).toISOString() : null;
  const clock = (value: string) => new Intl.DateTimeFormat(i18n.locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value));
  return <div className="wm-snapshot-controls">
    <span>{cn ? '自动检查5分钟' : 'Auto check 5m'}</span>
    {view.refresh && <button type="button" disabled={view.status?.fetching} onClick={view.refresh}>{view.status?.fetching ? cn ? '检查中…' : 'Checking…' : cn ? '刷新' : 'Refresh'}</button>}
    <div>{checked && <span>{cn ? '检查' : 'Checked'} <time data-runtime-checked-at dateTime={checked}>{clock(checked)}</time></span>}{generatedAt && <span>{cn ? '快照' : 'Snapshot'} <time data-runtime-snapshot-at dateTime={generatedAt} title={i18n.formatDateTime(generatedAt)}>{clock(generatedAt)}</time></span>}</div>
  </div>;
}
