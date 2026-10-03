/** Private selector ownership, shared by the CSS boundary check. Generic panel
 * chrome stays in shell; a module's modifiers belong with that module's body. */
export function panelStyleOwner(selector) {
  const value = selector.replace(/:not\([^)]*\)/g, '');
  if (/\.wm-(world-event|weather-deck|inline-weather-map|event-inspector|country-context|map-(status|legend|hover)|aviation-(lens|risk-tabs))/.test(value)) return 'map';
  if (/\.wm-(globe-(runtime|shade|quality|perf|hover|html)|ucdp-marker)/.test(value)) return 'map';
  if (/\.wm-market-(tv|youtube)/.test(value) || /data-panel-id=['"]market-(tv|youtube)/.test(value)) return 'media';
  if (/\.wm-(global-transport|aviation-)/.test(value)) return 'transport';
  if (/\.wm-(weather-|temp-city|global-temperature|world-clock)/.test(value) || /data-panel-id=['"](?:weather-|global-temperature)/.test(value)) return 'weather';
  if (/\.wm-(finance-|funding-|defi-|crypto-|commodity-|commodities|transmission-)/.test(value)) return 'finance';
  if (/\.wm-(tech-|ai-market)/.test(value)) return 'tech';
  if (/\.wm-(macro-|cpi-|energy-|food-|nowcast-|intel-signal|linked-market|market-implication|registry-empty|row-marker|intel-mark|status-badge)/.test(value)) return 'macro';
  if (/\.wm-(f1-|score-|scoreboard|lineup-|matchup-|esports-|odds-|nba-)/.test(value) || /data-panel-id=['"](?:nba-|espn-)/.test(value)) return 'sports';
  if (/\.wm-(evidence-|breaking-)/.test(value)) return 'breaking';
  if (/\.wm-(jin10-|new-market|signal-|trade-|oracle-|orderfilled-|intel-|news-|content-feed|related-intel|alpha-|polybeats-|whale-|flow-|geo-)/.test(value)) return 'signals';
  if (/\.wm-(market-(summary|status-value|context|search|sort|radar|signal|catalog)|feature-|summary-row|poly-market)/.test(value) || /data-workspace-panel-id=['"]market-summary/.test(value)) return 'market';
  return 'shell';
}

export const panelStyleFiles = Object.fromEntries(['shell', 'finance', 'tech', 'market', 'signals', 'macro', 'weather', 'sports', 'media', 'breaking', 'transport', 'map'].map(owner => [owner,
  owner === 'map' ? 'features/world-event-map/styles.css' : `panels/styles/${owner}.css`,
]));
