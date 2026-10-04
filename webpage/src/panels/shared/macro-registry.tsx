import { MacroRefresh } from './macro-runtime';
import {
  displayValue,
  numberLabel as compactNumber,
  RowGlyph,
  StatusBadge,
  type PanelGlyphName,
} from '@/panels/shared/macro-intel';
import { panelStatus } from '@/panels/shared/formatters';
import { useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import type { RuntimeMacroRegistryItem, RuntimeMacroRegistryPayload } from '@/types';
import { useSpecialistCopy } from '@/services/specialist-i18n';

export type MacroRegistryConfig = {
  panelId: string;
  title: string;
  badge: string;
  glyph: PanelGlyphName;
  helpTitle: string;
  helpText: string;
  emptyTitle: string;
  implicationItems: string[];
};

function rowGlyph(item: RuntimeMacroRegistryItem): PanelGlyphName {
  const text = `${item.group || ''} ${item.type || ''} ${item.label || ''}`.toLowerCase();
  if (/(oil|wti|energy)/.test(text)) return 'oil';
  if (/(gasoline|gas)/.test(text)) return 'gas';
  if (/(food|egg|meat)/.test(text)) return 'food';
  if (/(shelter|rent|oer|housing)/.test(text)) return 'home';
  if (/(job|labor|wage|claim|unemployment|nfp)/.test(text)) return 'labor';
  if (/(fed|sofr|funds|fomc)/.test(text)) return 'fed';
  if (/(2y|10y|rate|curve|treasury)/.test(text)) return 'rates';
  if (/(gdp|growth|retail|demand|recession)/.test(text)) return 'growth';
  if (/(tariff|policy|federal register|ustr)/.test(text)) return 'policy';
  if (/(cpi|pce|nowcast|inflation)/.test(text)) return 'cpi';
  return 'source';
}

function rowTone(item: RuntimeMacroRegistryItem) {
  const tone = String(item.tone || '').toLowerCase();
  if (tone === 'hot' || tone === 'cool' || tone === 'watch') return tone;
  return 'neutral';
}

function DataMetric({ label, value, tone }: { label: string; value?: number | string | null; tone?: string }) {
  return (
    <span className={tone ? `wm-macro-data-metric ${tone}` : 'wm-macro-data-metric'}>
      <i>{label}</i>
      <strong>{displayValue(value)}</strong>
    </span>
  );
}

function RegistryRow({ item, panelId }: { item: RuntimeMacroRegistryItem; panelId: string }) {
  const { shared } = useSpecialistCopy(panelId);
  const tone = rowTone(item);
  const meta = String(item.group || item.domainTag || item.type || 'macro').toUpperCase();
  const source = String(item.sourceLabel || item.source || 'SOURCE').toUpperCase();
  const domain = String(item.domainTag || item.type || 'MACRO').toUpperCase();
  const rank = item.rank ? String(item.rank).padStart(2, '0') : null;
  return (
    <div className={`wm-macro-registry-row ${tone}`}>
      <RowGlyph icon={rowGlyph(item)} tone={tone} label={item.label || item.group || shared('macroRow', 'Macro row')} />
      <div className="wm-macro-registry-main">
        <div className="wm-macro-registry-meta">
          {rank ? <span className="wm-macro-registry-rank">{rank}</span> : null}
          <span>{meta}</span>
          <span className="wm-macro-registry-source">{source}</span>
          <span className={`wm-macro-registry-tag ${tone}`}>{domain}</span>
          {item.ageLabel ? <span className="wm-macro-registry-age">{item.ageLabel}</span> : null}
        </div>
        <strong>{item.label || shared('macroRegistryRow', 'Macro registry row')}</strong>
        <span className="wm-macro-observation">Period {item.periodLabel || item.date || '--'} · {String(item.metadata?.adjustment || 'Source basis')}</span>
        {item.metadata?.levelLabel && String(item.label).includes('payrolls') ? <small className="wm-macro-observation">Total {String(item.metadata.levelLabel)}</small> : null}
        {item.metadata?.contextOnly ? <small className="wm-macro-observation">Context indicator; not a direct CPI component</small> : null}
        {item.metadata?.retained ? <small className="wm-macro-observation">Saved observation · source refresh failed</small> : null}
        <small className="wm-macro-observation">Collected {item.metadata?.fetchedAt ? new Date(String(item.metadata.fetchedAt)).toLocaleString() : 'See snapshot'} · Publication {String(item.metadata?.publishedAt || 'not supplied')}</small>
        {item.sourceUrl ? <a className="wm-macro-source-link" href={item.sourceUrl} target="_blank" rel="noopener noreferrer">Source</a> : null}
      </div>
      <div className="wm-macro-registry-right">
        <strong className="wm-macro-registry-value">{displayValue(item.valueLabel || item.value)}</strong>
        <StatusBadge tone={tone}>{item.changeLabel || item.severityLabel || '--'}</StatusBadge>
      </div>
    </div>
  );
}

export function MacroRegistryPanel({ config, payload }: { config: MacroRegistryConfig; payload?: RuntimeMacroRegistryPayload | null }) {
  const { copy, shared } = useSpecialistCopy(config.panelId);
  const [showHelp, setShowHelp] = useState(false);
  const [group, setGroup] = useState('All');
  const summary = payload?.summary;
  const items = payload?.items || [];
  const status = String(payload?.status || '').toLowerCase();
  const badge = status && status !== 'ok' ? String(payload?.status || 'WARMING').toUpperCase() : undefined;
  const groups = ['All', ...new Set(items.map(item => item.group || 'Macro'))];
  const visible = group === 'All' ? items : items.filter(item => item.group === group);
  const title = copy('title', config.title);
  return (
    <Panel
      title={title}
      titleControls={(
        <button
          type="button"
          className="wm-panel-help-button"
          aria-label={shared('explainPanel', 'Explain {title}', { title })}
          aria-expanded={showHelp}
          onClick={() => setShowHelp((current) => !current)}
        >
          ?
        </button>
      )}
      badge={badge}
      status={panelStatus(payload?.status)}
      count={items.length}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>{copy('helpTitle', config.helpTitle)}</strong>
          <p>{copy('helpText', config.helpText)}</p>
        </div>
      ) : null}
      className="wm-market-panel wm-macro-registry-panel"
      dataPanelId={config.panelId}
    >
      <MacroRefresh payload={payload} />
      <div className="wm-macro-registry-data-strip">
        <DataMetric label="Series checks" value={`${compactNumber(summary?.coverage)}/${compactNumber(summary?.sourceCount)}`} />
        <DataMetric label="Source services" value={summary?.providerCount ?? '--'} />
        <DataMetric label="Rows" value={items.length} />
      </div>
      <small className="wm-macro-observation">Observed moves use each row's unit and period. These are not weighted CPI contributions or a forecast.</small>
      <div className="wm-macro-filters" aria-label="Macro group filter">
        {groups.map(value => <button key={value} type="button" aria-pressed={group === value} onClick={() => setGroup(value)}>{value}</button>)}
      </div>
      <div className="wm-macro-registry-list">
        {visible.length ? visible.map((item) => <RegistryRow key={item.key || `${item.group}-${item.label}`} item={item} panelId={config.panelId} />) : (
          <div className="wm-empty-state">
            <strong>{copy('emptyTitle', config.emptyTitle)}</strong>
            <em>{shared('registryWarming', 'Seed cache has not composed this registry yet.')}</em>
          </div>
        )}
      </div>
    </Panel>
  );
}
