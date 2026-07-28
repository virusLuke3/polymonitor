import type { ComponentChildren } from 'preact';

const APP_VERSION = 'v0.2.1';
const SITE_NAV_LINKS = [
  { label: 'Blog', href: '/blog/' },
  { label: 'Docs', href: '/docs/documentation/' },
  { label: 'Paper', href: 'https://arxiv.org/pdf/2604.20421', external: true },
  { label: 'GitHub', href: 'https://github.com/virusLuke3/polymonitor', external: true },
  { label: 'Quant', href: '/quant' },
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
  return (
    <div className="wm-shell">
      <div className="wm-promo">
        <span className="wm-pro-badge">PRO</span>
        <span className="wm-promo-copy">PolyMonitor Pro is coming - sharper Polymarket signal, less noise, AI briefs for flow, oracle risk, and macro context.</span>
        <button className="wm-promo-cta" type="button">Reserve your spot</button>
      </div>

      <header className="wm-toolbar">
        <div className="wm-toolbar-left">
          <div className="wm-nav-cluster">
            <button
              className="wm-workspace-option active"
              type="button"
              onClick={onResetWorkspace}
              title="World workspace"
            >
              <span className="wm-workspace-icon">◎</span>
              <span className="wm-workspace-label">World</span>
            </button>
            <button className="wm-nav-icon" type="button" onClick={onOpenCommandPalette} title="Command palette">⌨</button>
            <button className="wm-nav-icon" type="button" onClick={onTogglePanelLibrary} title="Toggle panel library">◫</button>
            <button className="wm-nav-icon" type="button" onClick={onOpenSettings} title="Open settings">⚒</button>
            <button className="wm-nav-icon" type="button" onClick={onCycleRegion} title="Cycle region">◌</button>
          </div>
          <div className="wm-brand">POLYDATA MONITOR <span>{APP_VERSION}</span></div>
          <div className="wm-live-dot">Live</div>
          <button className="wm-select-pill" type="button" onClick={onCycleRegion}>
            {regionLabel} ▾
          </button>
          <div className="wm-defcon-pill">POLYMARKET <span>LIVE</span></div>
        </div>
        <nav className="wm-site-nav" aria-label="polyData resources">
          {SITE_NAV_LINKS.map((link) => (
            <a
              key={link.label}
              className={
                link.label === 'Quant' ? 'wm-site-nav-quant' : undefined
              }
              href={link.href}
              target={link.external ? '_blank' : undefined}
              rel={link.external ? 'noopener noreferrer' : undefined}
            >
              {link.label}
            </a>
          ))}
        </nav>
        <div className="wm-toolbar-right">
          <button className="wm-counter-pill" type="button">{orderFilledCount}</button>
          <button className="wm-tool-button" type="button" onClick={onOpenCommandPalette}>⌘K Search</button>
          <button className="wm-tool-button" type="button" onClick={onCopyLink}>Copy Link</button>
          <button className="wm-tool-icon" type="button" onClick={onResetWorkspace}>⌂</button>
          <button className="wm-tool-icon" type="button" onClick={onOpenSettings}>⚙</button>
        </div>
      </header>

      {children}
    </div>
  );
}
