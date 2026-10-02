import type { ComponentChildren } from 'preact';
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import { useI18n } from '@/services/i18n';

/** Shared report focus, escape and mobile placement for events and country briefs. */
export function InspectorFrame({ identity, level = 'info', onClose, returnFocusTarget, children }: {
  identity: string; level?: string; onClose: () => void; returnFocusTarget?: HTMLElement | null; children: ComponentChildren;
}) {
  const { locale } = useI18n(); const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const active = document.activeElement;
    const restore = active instanceof HTMLElement && active !== document.body ? active : returnFocusTarget;
    if (window.matchMedia('(max-width: 720px)').matches) ref.current?.closest('.wm-weather-deck-map')?.scrollIntoView({block: 'start', behavior: 'instant'});
    ref.current?.querySelector<HTMLElement>('h2')?.focus({preventScroll: true});
    return () => { if (restore?.isConnected) restore.focus({preventScroll: true}); };
  }, [identity, returnFocusTarget]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.defaultPrevented) {event.preventDefault(); onClose();} };
    document.addEventListener('keydown', escape); return () => document.removeEventListener('keydown', escape);
  }, [onClose]);
  return <aside ref={ref} className={`wm-event-inspector level-${level}`} aria-labelledby="wm-event-inspector-title" data-event-id={identity}>
    <button type="button" className="wm-event-inspector-close" aria-label={locale === 'zh' ? '关闭详情' : 'Close event details'} onClick={onClose}>×</button>
    {children}
  </aside>;
}
