import type { ComponentChildren } from 'preact';
import { MobileWorkspaceNav } from '@/components/MobileWorkspaceNav';
import { PwaControl } from '@/components/PwaControl';
import { useI18n, type MessageKey } from '@/services/i18n';

const APP_VERSION = 'v0.2.1';
const SITE_NAV_LINKS: Array<{ key: MessageKey; href: string; external?: boolean }> = [
  { key: 'nav.blog', href: '/blog/' },
  { key: 'nav.docs', href: '/docs/documentation/' },
  { key: 'nav.paper', href: 'https://arxiv.org/pdf/2604.20421', external: true },
  { key: 'nav.github', href: 'https://github.com/virusLuke3/polymonitor', external: true },
  { key: 'nav.quality', href: '/data-quality' },
  { key: 'nav.watchlist', href: '/watchlist' },
  { key: 'nav.briefings', href: '/briefings' },
  { key: 'nav.access', href: '/account' },
  { key: 'nav.developers', href: '/developers' },
  { key: 'nav.quant', href: '/quant' },
];

type AppShellProps = {
  children: ComponentChildren;
  regionLabel: string;
  orderFilledCount: number;
  onCycleRegion: () => void;
  onResetWorkspace: () => void;
  onOpenCommandPalette: () => void;
  onTogglePanelLibrary: () => void;
  onOpenSettings: () => void;
  onCopyLink: () => void;
};

export function AppShell({
  children,
  regionLabel,
  orderFilledCount,
  onCycleRegion,
  onResetWorkspace,
  onOpenCommandPalette,
  onTogglePanelLibrary,
  onOpenSettings,
  onCopyLink,
}: AppShellProps) {
  const { locale, setLocale, t } = useI18n();
  return (
    <div className="wm-shell">
      <div className="wm-promo">
        <span className="wm-pro-badge">{t('shell.proBadge')}</span>
        <span className="wm-promo-copy">{t('shell.promo')}</span>
        <button className="wm-promo-cta" type="button">{t('shell.reserve')}</button>
      </div>

      <header className="wm-toolbar">
        <div className="wm-toolbar-left">
          <div className="wm-nav-cluster">
            <button className="wm-workspace-option active" type="button" onClick={onResetWorkspace} title={t('shell.worldTitle')}>
              <span className="wm-workspace-icon">◎</span>
              <span className="wm-workspace-label">{t('shell.world')}</span>
            </button>
            <button className="wm-nav-icon" type="button" onClick={onOpenCommandPalette} title={t('shell.command')}>⌨</button>
            <button className="wm-nav-icon" type="button" onClick={onTogglePanelLibrary} title={t('shell.panelLibrary')}>◫</button>
            <button className="wm-nav-icon" type="button" onClick={onOpenSettings} title={t('shell.settings')}>⚒</button>
            <button className="wm-nav-icon" type="button" onClick={onCycleRegion} title={t('shell.region')}>◌</button>
          </div>
          <div className="wm-brand">POLYDATA MONITOR <span>{APP_VERSION}</span></div>
          <div className="wm-live-dot">{t('shell.live')}</div>
          <button className="wm-select-pill" type="button" onClick={onCycleRegion}>{regionLabel} ▾</button>
          <div className="wm-defcon-pill">POLYMARKET <span>LIVE</span></div>
        </div>
        <nav className="wm-site-nav" aria-label={t('shell.resources')}>
          {SITE_NAV_LINKS.map((link) => (
            <a
              key={link.key}
              className={link.key === 'nav.quant' ? 'wm-site-nav-quant' : undefined}
              href={link.href}
              target={link.external ? '_blank' : undefined}
              rel={link.external ? 'noopener noreferrer' : undefined}
            >
              {t(link.key)}
            </a>
          ))}
        </nav>
        <div className="wm-toolbar-right">
          <label className="wm-language-switch">
            <span className="sr-only">{t('settings.language')}</span>
            <select value={locale} onChange={(event) => setLocale(event.currentTarget.value === 'zh' ? 'zh' : 'en')}>
              <option value="en">EN</option>
              <option value="zh">中文</option>
            </select>
          </label>
          <PwaControl />
          <button className="wm-counter-pill" type="button">{orderFilledCount}</button>
          <button className="wm-tool-button" type="button" onClick={onOpenCommandPalette}>{t('shell.search')}</button>
          <button className="wm-tool-button" type="button" onClick={onCopyLink}>{t('shell.copyLink')}</button>
          <button className="wm-tool-icon" type="button" onClick={onResetWorkspace} title={t('shell.home')}>⌂</button>
          <button className="wm-tool-icon" type="button" onClick={onOpenSettings} title={t('shell.settings')}>⚙</button>
        </div>
      </header>
      {children}
      <MobileWorkspaceNav />
    </div>
  );
}
