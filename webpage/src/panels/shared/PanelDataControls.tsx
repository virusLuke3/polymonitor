import type { ComponentChildren } from 'preact';
import { useI18n } from '@/services/i18n';

/** Header actions share the panel shell; diagnostics never consume a body row. */
export function PanelDataControls({ fetching, onRefresh, children }: {
  fetching?: boolean; onRefresh: () => void; children?: ComponentChildren;
}) {
  const { locale } = useI18n();
  const cn = locale.startsWith('zh');
  const details = cn ? '数据详情' : 'Data details';
  const refresh = cn ? '刷新' : 'Refresh';
  return <>
    {children && <details className="wm-panel-data-details" onKeyDown={event => {
      if (event.key === 'Escape') {
        event.currentTarget.open = false;
        event.currentTarget.querySelector('summary')?.focus();
        event.stopPropagation();
      }
    }}>
      <summary className="wm-panel-action" aria-label={details} title={details}>ⓘ</summary>
      <div className="wm-panel-data-popover">{children}</div>
    </details>}
    <button className="wm-panel-action" type="button" aria-label={refresh} title={refresh}
      disabled={fetching} aria-busy={fetching} onClick={onRefresh}>↻</button>
  </>;
}
