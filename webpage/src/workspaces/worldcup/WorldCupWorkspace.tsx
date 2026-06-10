import { type ComponentChildren } from 'preact';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { PanelLoading } from '@/components/Panel';
import type { ContentItem } from '@/types';
import {
  filterWorldCupNews,
  getNextWorldCupMatch,
  applyWorldCupMarketLinks,
  loadWorldCupDashboard,
  matchCity,
  matchPolymarketMarkets,
  refreshWorldCupDashboard,
  WORLD_CUP_HOST_MATCH_COUNTS,
} from './data';
import { WorldCupMap } from './WorldCupMap';
import { SourceRequired, type SourceRequiredRow } from './components/SourceRequired';
import { CalendarPanel } from './panels/CalendarPanel';
import { WinProbabilityPanel } from './panels/WinProbabilityPanel';
import type {
  WorldCupDashboardPayload,
  WorldCupMatch,
  WorldCupNewsItem,
  WorldCupOddsSnapshot,
  WorldCupPolymarketMarket,
  WorldCupWorkspaceProps,
} from './types';
import { WorldCupPanel as Panel } from './components/WorldCupPanel';
import {
  WORLD_CUP_PANEL_DRAG_THRESHOLD,
  WORLD_CUP_PANEL_ORDER,
  WORLD_CUP_PANEL_ORDER_STORAGE_KEY,
  readWorldCupPanelOrder,
  reorderWorldCupPanels,
  type MatchFilter,
  type WorldCupPanelId,
} from './panels/registry';
import { kickoffDay, kickoffTime, scoreText, stageLabel } from './panels/formatters';
import './styles/worldcup-reference-ui.css';

type WorldCupSignalTone = 'red' | 'gold' | 'blue' | 'purple' | 'gray' | 'green';
type WorldCupSignalItem = {
  id: string;
  source: string;
  title: string;
  summary: string;
  age: string;
  tags: Array<{ label: string; tone: WorldCupSignalTone }>;
  accent?: WorldCupSignalTone;
};

const WORLD_CUP_DASHBOARD_CLASS = 'wm-dashboard wm-worldcup-dashboard wm-worldcup-v5';

function formatCountdown(match: WorldCupMatch | null, now: Date) {
  if (!match) return '--';
  const diffSeconds = Math.max(0, Math.floor((new Date(match.kickoffUtc).getTime() - now.getTime()) / 1000));
  const days = Math.floor(diffSeconds / 86400);
  const hours = Math.floor((diffSeconds % 86400) / 3600);
  const minutes = Math.floor((diffSeconds % 3600) / 60);
  const seconds = diffSeconds % 60;
  const pad = (value: number) => String(value).padStart(2, '0');
  if (days > 0) return `${days}D ${pad(hours)}H ${pad(minutes)}M ${pad(seconds)}S`;
  return `${pad(hours)}H ${pad(minutes)}M ${pad(seconds)}S`;
}

function formatNumber(value?: number | null, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  return Number(value).toFixed(digits);
}

function formatCompact(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  const number = Number(value);
  if (number >= 1_000_000) return `$${(number / 1_000_000).toFixed(1)}M`;
  if (number >= 1_000) return `$${(number / 1_000).toFixed(1)}K`;
  return `$${number.toFixed(0)}`;
}

function formatUpdatedAgo(iso: string, now: Date) {
  const diffSeconds = Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 1000));
  if (diffSeconds < 60) return `${diffSeconds}s ago`;
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffHours / 24)}d ago`;
}

function formatWeatherDay(date: string) {
  const normalized = /^\d{2}-\d{2}$/.test(date) ? `2026-${date}` : date;
  const parsed = new Date(`${normalized}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime())) return date;
  const weekday = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', weekday: 'short' }).format(parsed);
  const monthDay = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: '2-digit' }).format(parsed);
  return `${weekday} ${monthDay}`;
}

function weatherIcon(condition = '') {
  if (/storm|thunder/i.test(condition)) return '⚡';
  if (/rain|mist|shower/i.test(condition)) return '☔';
  if (/humid|warm|heat/i.test(condition)) return '◐';
  if (/cloud/i.test(condition)) return '☁';
  return '☀';
}

function weatherTone(condition = '', tempC = 0) {
  if (/storm|thunder|rain|mist|shower/i.test(condition)) return 'weather-rain';
  if (/humid/i.test(condition)) return 'weather-humid';
  if (tempC >= 27 || /warm|heat/i.test(condition)) return 'weather-warm';
  if (/cloud/i.test(condition)) return 'weather-cloud';
  return 'weather-clear';
}

function formatBjtClock(now: Date) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(now);
}

function probabilityWidth(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '2%';
  return `${Math.max(2, Math.min(100, Number(value) * 100))}%`;
}

function percentLabel(value?: number | null, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  return `${Number(value).toFixed(digits)}%`;
}

function probabilityLabel(value?: number | null, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '--';
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function clampNumber(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function newsTags(item: WorldCupNewsItem) {
  const text = `${item.title} ${item.summary || ''}`.toLowerCase();
  const tags: Array<{ label: string; tone: string }> = [];
  tags.push({ label: 'ONGOING', tone: 'gray' });
  if (/(alert|risk|delay|storm|injur|security|crisis)/.test(text)) tags.push({ label: 'ALERT', tone: 'red' });
  if (/(strike|attack|war|quake|killed|evacuat|ceasefire|conflict|disaster)/.test(text)) tags.push({ label: 'ALERT', tone: 'red' });
  if (/(market|odds|price|trading|polymarket)/.test(text)) tags.push({ label: 'MARKET', tone: 'purple' });
  if (/(weather|storm|heat|rain|travel)/.test(text)) tags.push({ label: 'WEATHER', tone: 'blue' });
  if (/(squad|team|player|coach|roster)/.test(text)) tags.push({ label: 'TEAM', tone: 'gold' });
  return tags.slice(0, 2);
}

function latestContentNewsFallback(content: ContentItem[]): WorldCupNewsItem[] {
  return content.slice(0, 24).map((item, index) => ({
    id: String(item.id || item.url || `latest-${index}`),
    title: item.title || 'Global monitor item',
    source: item.source || 'GLOBAL WIRE',
    url: item.url || '#',
    publishedAt: item.publishedAt || new Date().toISOString(),
    summary: item.summary || '',
  }));
}

const HIDDEN_SIGNAL_LABELS = new Set(['SEED', 'RSS', 'PRIMARY', 'LIVE', 'LOCAL DB', 'REMOTE', 'WATCH']);

function cleanPanelBadge(label: string) {
  if (!label) return '';
  if (/(seed|rss|primary|local db|remote|watch|pending|scheduled|live|实时)/i.test(label)) return '';
  return label;
}

function cleanSignalAge(age?: string | null) {
  const value = (age || '').trim();
  if (!value) return '';
  if (/(seed|rss|primary|policy|pool|reserve|pending|pre-match|scheduled|local|model|watch|live)$/i.test(value)) return '';
  const hourMatch = value.match(/^(\d+)h(?:\s+ago)?$/i);
  if (hourMatch) return `${hourMatch[1]}小时前`;
  const minuteMatch = value.match(/^(\d+)m(?:\s+ago)?$/i);
  if (minuteMatch) return `${minuteMatch[1]}分钟前`;
  const dayMatch = value.match(/^(\d+)d(?:\s+ago)?$/i);
  if (dayMatch) return `${dayMatch[1]}天前`;
  if (/^(now|live)$/i.test(value)) return '';
  return value;
}

function cleanSignalSource(source?: string | null) {
  const value = (source || '').trim();
  if (!value) return 'WORLD CUP DESK';
  if (/^(seed|rss|primary|inferred|manual|fallback)$/i.test(value)) return 'WORLD CUP DESK';
  if (/local\s*db/i.test(value)) return 'MARKET DESK';
  if (/remote/i.test(value)) return 'DATA DESK';
  return String(value || 'source').replace(/[-_]/g, ' ').toUpperCase();
}

function cleanSignalTags(tags: WorldCupSignalItem['tags']) {
  return tags.filter((tag) => {
    const label = String(tag.label || '').trim().toUpperCase();
    return label && !HIDDEN_SIGNAL_LABELS.has(label) && !/(^|\s)(SEED|RSS|PRIMARY|LIVE|WATCH)(\s|$)/i.test(label);
  });
}

function mergeSignalRows(...groups: WorldCupSignalItem[][]) {
  const seen = new Set<string>();
  return groups.flat().filter((item) => {
    const key = `${item.source}:${item.title}`.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function WorldCupPanelSlot({
  panelId,
  draggingId,
  children,
  onMovePanel,
  onDragStateChange,
}: {
  panelId: WorldCupPanelId;
  draggingId: WorldCupPanelId | null;
  children: ComponentChildren;
  onMovePanel: (draggedId: WorldCupPanelId, targetId: WorldCupPanelId, insertAfter: boolean) => void;
  onDragStateChange: (panelId: WorldCupPanelId | null) => void;
}) {
  const slotRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef({
    active: false,
    started: false,
    startX: 0,
    startY: 0,
    lastX: 0,
    lastY: 0,
    offsetX: 0,
    offsetY: 0,
    rafId: 0,
    ghost: null as HTMLElement | null,
    indicator: null as HTMLElement | null,
    lastTarget: null as HTMLElement | null,
  });

  const clearDragVisuals = () => {
    const state = dragRef.current;
    if (state.rafId) {
      window.cancelAnimationFrame(state.rafId);
      state.rafId = 0;
    }
    slotRef.current?.classList.remove('dragging-source');
    state.lastTarget?.classList.remove('panel-drop-target');
    state.lastTarget = null;
    if (state.ghost) {
      const ghost = state.ghost;
      ghost.style.opacity = '0';
      window.setTimeout(() => ghost.remove(), 140);
      state.ghost = null;
    }
    if (state.indicator) {
      const indicator = state.indicator;
      indicator.style.opacity = '0';
      window.setTimeout(() => indicator.remove(), 140);
      state.indicator = null;
    }
    onDragStateChange(null);
  };

  const findDropTarget = (clientX: number, clientY: number) => {
    const hit = document.elementFromPoint(clientX, clientY) as HTMLElement | null;
    const targetSlot = hit?.closest<HTMLElement>('.wm-worldcup-matrix-cell[data-worldcup-panel-id]') || null;
    if (!targetSlot) return null;
    const targetPanelId = targetSlot.dataset.worldcupPanelId as WorldCupPanelId | undefined;
    if (!targetPanelId || targetPanelId === panelId) return null;
    const rect = targetSlot.getBoundingClientRect();
    return {
      targetSlot,
      targetPanelId,
      insertAfter: clientY > rect.top + rect.height / 2 || (
        Math.abs(clientY - (rect.top + rect.height / 2)) < Math.min(44, rect.height / 4)
        && clientX > rect.left + rect.width / 2
      ),
      rect,
    };
  };

  const updateDropIndicator = (clientX: number, clientY: number) => {
    const state = dragRef.current;
    if (!state.indicator) return;
    const target = findDropTarget(clientX, clientY);
    if (!target) {
      state.indicator.style.opacity = '0';
      state.lastTarget?.classList.remove('panel-drop-target');
      state.lastTarget = null;
      return;
    }
    if (target.targetSlot !== state.lastTarget) {
      state.lastTarget?.classList.remove('panel-drop-target');
      target.targetSlot.classList.add('panel-drop-target');
      state.lastTarget = target.targetSlot;
    }
    state.indicator.style.left = `${target.rect.left}px`;
    state.indicator.style.top = `${target.insertAfter ? target.rect.bottom : target.rect.top - 3}px`;
    state.indicator.style.width = `${target.rect.width}px`;
    state.indicator.style.opacity = '0.92';
  };

  const startDrag = (event: MouseEvent) => {
    if (event.button !== 0 || !slotRef.current) return;
    const target = event.target as HTMLElement;
    if (target.closest('button, a, input, select, textarea, [role="button"]')) return;
    if (!target.closest('.wm-panel-header')) return;
    const rect = slotRef.current.getBoundingClientRect();
    dragRef.current = {
      active: true,
      started: false,
      startX: event.clientX,
      startY: event.clientY,
      lastX: event.clientX,
      lastY: event.clientY,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      rafId: 0,
      ghost: null,
      indicator: null,
      lastTarget: null,
    };
    event.preventDefault();

    const onMouseMove = (moveEvent: MouseEvent) => {
      const state = dragRef.current;
      if (!state.active || !slotRef.current) return;
      state.lastX = moveEvent.clientX;
      state.lastY = moveEvent.clientY;
      if (!state.started) {
        const dx = Math.abs(moveEvent.clientX - state.startX);
        const dy = Math.abs(moveEvent.clientY - state.startY);
        if (dx < WORLD_CUP_PANEL_DRAG_THRESHOLD && dy < WORLD_CUP_PANEL_DRAG_THRESHOLD) return;
        const sourceRect = slotRef.current.getBoundingClientRect();
        const sourcePanel = slotRef.current.querySelector<HTMLElement>(':scope > .wm-worldcup-panel') || slotRef.current;
        state.started = true;
        onDragStateChange(panelId);
        const ghost = sourcePanel.cloneNode(true) as HTMLElement;
        ghost.querySelectorAll('iframe').forEach((frame) => frame.remove());
        ghost.classList.add('wm-panel-drag-ghost', 'wm-worldcup-drag-ghost');
        ghost.setAttribute('aria-hidden', 'true');
        ghost.style.position = 'fixed';
        ghost.style.pointerEvents = 'none';
        ghost.style.zIndex = '10000';
        ghost.style.width = `${sourceRect.width}px`;
        ghost.style.height = `${sourceRect.height}px`;
        ghost.style.left = `${moveEvent.clientX - state.offsetX}px`;
        ghost.style.top = `${moveEvent.clientY - state.offsetY}px`;
        document.body.appendChild(ghost);
        state.ghost = ghost;
        slotRef.current.classList.add('dragging-source');
        const indicator = document.createElement('div');
        indicator.className = 'wm-panel-drop-indicator wm-worldcup-drop-indicator';
        document.body.appendChild(indicator);
        state.indicator = indicator;
      }
      if (state.rafId) window.cancelAnimationFrame(state.rafId);
      state.rafId = window.requestAnimationFrame(() => {
        const latest = dragRef.current;
        if (latest.ghost) {
          latest.ghost.style.left = `${latest.lastX - latest.offsetX}px`;
          latest.ghost.style.top = `${latest.lastY - latest.offsetY}px`;
        }
        updateDropIndicator(latest.lastX, latest.lastY);
        latest.rafId = 0;
      });
    };

    const finishDrag = () => {
      const state = dragRef.current;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', finishDrag);
      document.removeEventListener('keydown', onKeyDown);
      if (state.active && state.started) {
        const targetDrop = findDropTarget(state.lastX, state.lastY);
        if (targetDrop) onMovePanel(panelId, targetDrop.targetPanelId, targetDrop.insertAfter);
      }
      state.active = false;
      state.started = false;
      clearDragVisuals();
    };

    const onKeyDown = (keyEvent: KeyboardEvent) => {
      if (keyEvent.key !== 'Escape') return;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', finishDrag);
      document.removeEventListener('keydown', onKeyDown);
      dragRef.current.active = false;
      dragRef.current.started = false;
      clearDragVisuals();
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', finishDrag);
    document.addEventListener('keydown', onKeyDown);
  };

  useEffect(() => clearDragVisuals, []);

  return (
    <div
      ref={slotRef}
      className={`wm-worldcup-matrix-cell wm-worldcup-draggable-cell ${draggingId === panelId ? 'dragging-source' : ''}`}
      data-worldcup-panel-id={panelId}
      onMouseDown={(event) => startDrag(event as MouseEvent)}
    >
      {children}
    </div>
  );
}

function InfoDot({ label }: { label: string }) {
  return <span className="wm-worldcup-info-dot" aria-label={label} title={label}>?</span>;
}

function SignalTags({ tags }: { tags: WorldCupSignalItem['tags'] }) {
  return (
    <>
      {cleanSignalTags(tags).slice(0, 3).map((tag) => (
        <b className={`wm-worldcup-feed-tag ${tag.tone}`} key={`${tag.label}-${tag.tone}`}>{tag.label}</b>
      ))}
    </>
  );
}

function SignalRow({ item }: { item: WorldCupSignalItem }) {
  const displayAge = cleanSignalAge(item.age);
  return (
    <article className={`wm-worldcup-signal-row ${item.accent || item.tags[0]?.tone || 'gray'}`}>
      <div className="wm-worldcup-feed-meta">
        <span>{cleanSignalSource(item.source)}</span>
        <SignalTags tags={item.tags} />
      </div>
      <strong>{item.title}</strong>
      <em>{item.summary}</em>
      <div className="wm-worldcup-signal-foot">
        {displayAge ? <span>{displayAge}</span> : <span aria-hidden="true" />}
        <button type="button" tabIndex={-1}>文</button>
      </div>
    </article>
  );
}

function SignalFeedPanel({
  title,
  badge,
  count,
  items,
  className,
}: {
  title: string;
  badge: string;
  count?: number;
  items: WorldCupSignalItem[];
  className: string;
}) {
  return (
    <Panel title={title} badge={cleanPanelBadge(badge) || undefined} count={count ?? items.length} className={`wm-worldcup-panel ${className}`}>
      <div className="wm-worldcup-signal-list">
        {items.map((item) => <SignalRow item={item} key={item.id} />)}
      </div>
    </Panel>
  );
}

function coerceSignalTone(tone?: string | null): WorldCupSignalTone {
  if (tone === 'red' || tone === 'gold' || tone === 'blue' || tone === 'purple' || tone === 'gray' || tone === 'green') return tone;
  return 'blue';
}

function runtimeSignalItems(payload: WorldCupDashboardPayload, category: string, match: WorldCupMatch | null): WorldCupSignalItem[] {
  const signals = payload.intelligence?.signals || [];
  return signals
    .filter((item) => item.category === category && (!item.matchId || item.matchId === match?.id))
    .slice(0, 16)
    .map((item, index) => ({
      id: item.id || `${category}-${index}`,
      source: item.source || item.provider || 'WORLD CUP DESK',
      title: item.title || 'World Cup live signal',
      summary: item.summary || 'Runtime feed item from World Cup intelligence provider.',
      age: item.age || payload.intelligence?.generatedAt || '',
      tags: cleanSignalTags((item.tags?.length ? item.tags : [{ label: 'INFO', tone: 'blue' }]).slice(0, 3).map((tag) => ({
        label: tag.label,
        tone: coerceSignalTone(tag.tone),
      }))),
      accent: coerceSignalTone(item.accent),
    }));
}

function useWorldCupDashboard(marketGroups: WorldCupWorkspaceProps['marketGroups']) {
  const [basePayload, setBasePayload] = useState<WorldCupDashboardPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loadWorldCupDashboard()
      .then((nextPayload) => {
        if (cancelled) return;
        setBasePayload(nextPayload);
        setError(null);
        void refreshWorldCupDashboard(nextPayload)
          .then((refreshedPayload) => {
            if (!cancelled) setBasePayload(refreshedPayload);
          })
          .catch(() => {
            // Keep the first-paint schedule visible when runtime enrichment is slow.
          });
      })
      .catch((loadError) => {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : 'World Cup payload unavailable.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const payload = useMemo(
    () => (basePayload ? applyWorldCupMarketLinks(basePayload, marketGroups) : null),
    [basePayload, marketGroups],
  );
  return { payload, loading, error };
}

function MatchPanel({
  match,
  markets,
  odds,
  weather,
  city,
}: {
  match: WorldCupMatch | null;
  markets: WorldCupPolymarketMarket[];
  odds: WorldCupOddsSnapshot[];
  weather?: WorldCupDashboardPayload['weather'][number] | null;
  city?: WorldCupDashboardPayload['cities'][number] | null;
}) {
  if (!match) {
    return (
      <Panel title="MATCH DETAIL" count={0} className="wm-worldcup-panel">
        <div className="wm-worldcup-empty">No match selected.</div>
      </Panel>
    );
  }
  return (
    <Panel title="MATCH DETAIL" count={markets.length + odds.length} className="wm-worldcup-panel wm-worldcup-match-panel">
      <div className="wm-worldcup-scoreboard">
        <div>
          <span>HOME</span>
          <strong>{match.homeTeam}</strong>
        </div>
        <b>{scoreText(match)}</b>
        <div>
          <span>AWAY</span>
          <strong>{match.awayTeam}</strong>
        </div>
      </div>
      <div className="wm-worldcup-match-detail-strip">
        <span><b>#{match.fifaMatchNumber || '--'}</b> MATCH</span>
        <span><b>{match.group || stageLabel(match.stage)}</b> GROUP</span>
        <span><b>{markets.length}</b> MKTS</span>
        <span><b>{odds.length}</b> ODDS</span>
      </div>
      <div className="wm-worldcup-match-facts">
        <div><span>MATCH</span><strong>#{match.fifaMatchNumber || '--'} · {match.round}</strong></div>
        <div><span>GROUP</span><strong>{match.group || stageLabel(match.stage)}</strong></div>
        <div><span>BEIJING</span><strong>{match.kickoffBeijing}</strong></div>
        <div><span>LOCAL</span><strong>{match.kickoffLocal}</strong></div>
        <div><span>CITY</span><strong>{match.city}</strong></div>
        <div><span>VENUE</span><strong>{match.venue}</strong></div>
        <div><span>WEATHER</span><strong>{weather ? `${weather.current.tempC}C · ${weather.current.condition}` : 'Host weather watch'}</strong></div>
        <div><span>CAPACITY</span><strong>{city?.capacity ? `${city.capacity.toLocaleString()} seats` : 'Host venue'}</strong></div>
        <div><span>STATE</span><strong>{String(match.status || 'scheduled').toUpperCase()}{match.minute ? ` · ${match.minute}` : ''}</strong></div>
      </div>
    </Panel>
  );
}

function NewsPanel({ items }: { items: ReturnType<typeof filterWorldCupNews> }) {
  return (
    <Panel title="NEWS" count={items.length} className="wm-worldcup-panel wm-worldcup-news-panel">
      <div className="wm-worldcup-feed">
        {items.map((item) => (
          <a className="wm-worldcup-feed-row" href={item.url || '#'} key={item.id} target={item.url === '#' ? undefined : '_blank'} rel="noreferrer">
            <div className="wm-worldcup-feed-meta">
              <span>{item.source}</span>
              {newsTags(item).map((tag) => (
                <b className={`wm-worldcup-feed-tag ${tag.tone}`} key={`${item.id}-${tag.label}`}>{tag.label}</b>
              ))}
            </div>
            <strong>{item.title}</strong>
            <em>{item.summary || 'Monitoring World Cup-linked market context.'}</em>
          </a>
        ))}
      </div>
    </Panel>
  );
}

function WeatherPanel({
  payload,
  selectedCityId,
  onSelectCity,
}: {
  payload: WorldCupDashboardPayload;
  selectedCityId: string | null;
  onSelectCity: (cityId: string) => void;
}) {
  const cityWeather = payload.weather.map((weather) => ({
    weather,
    city: matchCity(payload.cities, weather.cityId),
    matchCount: payload.matches.filter((match) => match.cityId === weather.cityId).length,
  }));
  return (
    <Panel title="WEATHER" count={cityWeather.length} className="wm-worldcup-panel wm-worldcup-weather-panel">
      <div className="wm-worldcup-weather-list">
        {cityWeather.map(({ city, weather, matchCount }) => (
          <button className={`wm-worldcup-weather-row ${city.id === selectedCityId ? 'active' : ''} ${weatherTone(weather.current.condition, weather.current.tempC)}`} key={city.id} type="button" onClick={() => onSelectCity(city.id)}>
            <span className="wm-worldcup-weather-main">
              <strong><i aria-hidden="true">{weatherIcon(weather.current.condition)}</i>{city.city}</strong>
              <em>{city.country} · {matchCount} matches · wind {weather.current.windKph ?? '--'} kph · rain {weather.current.precipitationProbability ?? 0}%</em>
            </span>
            <b>{weather.current.tempC}°C</b>
            <span className="wm-worldcup-weather-condition">{weather.current.condition}</span>
            <span className="wm-worldcup-weather-forecast">
              {weather.forecast.slice(0, 5).map((day) => (
                <i key={`${city.id}-${day.date}`}>
                  <small>{formatWeatherDay(day.date)}</small>
                  <strong>{day.lowC}°/{day.highC}°</strong>
                  <em>{day.precipitationProbability ?? 0}%</em>
                </i>
              ))}
            </span>
          </button>
        ))}
        {!cityWeather.length ? (
          <SourceRequired
            detail="Weather panel requires runtime Open-Meteo/wttr host-city forecasts. No browser-generated temperatures are displayed."
            rows={[
              { source: 'Open-Meteo', status: payload.intelligence?.providerStates?.openMeteo || 'required', detail: 'current and 5-day forecast by host city' },
              { source: 'wttr.in secondary', status: payload.intelligence?.providerStates?.wttr || 'optional', detail: 'used only when Open-Meteo does not return a city' },
            ]}
          />
        ) : null}
      </div>
    </Panel>
  );
}

function PolymarketPanel({ markets }: { markets: WorldCupPolymarketMarket[] }) {
  return (
    <Panel
      title="MARKETS"
      count={markets.length}
      titleControls={<InfoDot label="Local Polymarket market matches are ranked by team, venue and kickoff context confidence." />}
      className="wm-worldcup-panel wm-worldcup-polymarket-panel"
    >
      {markets.length ? (
        <div className="wm-worldcup-market-list">
          {markets.map((market) => (
            <article className="wm-worldcup-market-row" key={`${market.eventId || market.title}`}>
              <div>
                <span>{formatCompact(market.volume24h)} 24H · {Math.round(market.confidence * 100)}% match</span>
                <strong>{market.title}</strong>
                <em>Polymarket-style probability board</em>
              </div>
              <div className="wm-worldcup-outcomes">
                {market.outcomes.slice(0, 3).map((outcome) => (
                  <span key={outcome.name}>
                    <b>{outcome.name}</b>
                    <strong>{outcome.yesPrice == null ? '--' : `${(outcome.yesPrice * 100).toFixed(1)}%`}</strong>
                    <i style={{ width: probabilityWidth(outcome.yesPrice) }} />
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <SourceRequired
          detail="No verified Polymarket/local-db market is linked to this fixture. The panel will stay empty instead of creating inferred prices."
          rows={[{ source: 'Polymarket local DB / Gamma', status: 'not matched', detail: 'requires event/market title match and real outcome prices' }]}
        />
      )}
    </Panel>
  );
}

function RostersPanel({ payload, match }: { payload: WorldCupDashboardPayload; match: WorldCupMatch | null }) {
  const teams = match ? [match.homeTeam, match.awayTeam] : [];
  const rosters = payload.rosters.filter((roster) => teams.includes(roster.team));
  return (
    <Panel title="SQUADS" count={rosters.length} className="wm-worldcup-panel wm-worldcup-rosters-panel">
      {rosters.length ? rosters.map((roster) => (
        <section className="wm-worldcup-roster-block" key={roster.team}>
          <div className="wm-worldcup-roster-head">
            <strong>{roster.team}</strong>
            <span>FED</span>
          </div>
          {roster.players.map((player) => (
            <div className="wm-worldcup-player-row" key={`${roster.team}-${player.name}`}>
              <span>{player.name}</span>
              <em>{player.position || '--'} · {player.club || player.status || 'pending'}</em>
            </div>
          ))}
        </section>
      )) : (
        <SourceRequired
          detail="Official federation squad feeds are not connected. No placeholder player rows are rendered."
          rows={[
            { source: 'FIFA / federation squad pages', status: 'required', detail: 'confirmed roster and shirt-number data' },
            { source: 'ESPN injury tracker / club notes', status: 'required', detail: 'availability and injury status' },
          ]}
        />
      )}
    </Panel>
  );
}

function OddsPanel({ odds, polymarket }: { odds: WorldCupOddsSnapshot[]; polymarket: WorldCupPolymarketMarket[] }) {
  return (
    <Panel
      title="ODDS"
      count={odds.length}
      titleControls={<InfoDot label="Bookmaker snapshots show decimal odds and implied probability for the selected match." />}
      className="wm-worldcup-panel wm-worldcup-odds-panel"
    >
      <div className="wm-worldcup-odds-list">
        {odds.slice(0, 8).map((snapshot) => (
          <article className="wm-worldcup-odds-row" key={`${snapshot.matchId}-${snapshot.provider}`}>
            <div>
              <span>{String(snapshot.providerType || 'provider').replace('_', ' ')}</span>
              <strong>{snapshot.provider}</strong>
            </div>
            <div className="wm-worldcup-odds-cells">
              {snapshot.outcomes.map((outcome) => (
                <span key={outcome.name}>
                  <b>{outcome.name}</b>
                  <strong>{formatNumber(outcome.decimalOdds, 2)}</strong>
                  <em>{formatNumber(outcome.impliedProbability, 1)}%</em>
                  <i style={{ width: outcome.impliedProbability == null ? '2%' : `${Math.max(2, Math.min(100, outcome.impliedProbability))}%` }} />
                </span>
              ))}
            </div>
          </article>
        ))}
        {!odds.length ? (
          <SourceRequired
            detail="No sportsbook feed is connected for this fixture. Odds rows are hidden until a licensed odds API supplies bookmaker snapshots."
            rows={[
              { source: 'The Odds API / Sportradar odds / bookmaker feed', status: 'required', detail: 'moneyline, totals and timestamped implied probabilities' },
              { source: 'Polymarket local DB', status: polymarket.length ? 'available' : 'not matched', detail: `${polymarket.length} linked prediction markets` },
            ]}
          />
        ) : null}
      </div>
    </Panel>
  );
}

void [SignalFeedPanel, MatchPanel, WeatherPanel, PolymarketPanel, RostersPanel, OddsPanel];

function MatchControlPanel({
  match,
  markets,
  odds,
  weather,
  city,
  facts,
  broadcast,
}: {
  match: WorldCupMatch | null;
  markets: WorldCupPolymarketMarket[];
  odds: WorldCupOddsSnapshot[];
  weather?: WorldCupDashboardPayload['weather'][number] | null;
  city?: WorldCupDashboardPayload['cities'][number] | null;
  facts: WorldCupSignalItem[];
  broadcast: WorldCupSignalItem[];
}) {
  if (!match) {
    return (
      <Panel title="MATCH CONTROL" count={0} className="wm-worldcup-panel wm-worldcup-match-control-panel">
        <div className="wm-worldcup-empty">No match selected.</div>
      </Panel>
    );
  }
  const factCards = [
    ['MATCH', `#${match.fifaMatchNumber || '--'}`, match.round],
    ['GROUP', match.group || stageLabel(match.stage), 'table / fixtures'],
    ['BJT', match.kickoffBeijing, 'desk clock'],
    ['LOCAL', match.kickoffLocal, city?.timezone || 'venue time'],
    ['VENUE', match.venue, `${match.city} · ${city?.capacity ? city.capacity.toLocaleString() : '--'} seats`],
    ['WEATHER', weather ? `${weather.current.tempC}C · ${weather.current.condition}` : 'pending', `wind ${weather?.current.windKph ?? '--'} kph · rain ${weather?.current.precipitationProbability ?? 0}%`],
  ];
  return (
    <Panel title="MATCH CONTROL" count={facts.length + broadcast.length} className="wm-worldcup-panel wm-worldcup-match-control-panel">
      <div className="wm-worldcup-control-score">
        <span><em>HOME</em><strong>{match.homeTeam}</strong></span>
        <b>{scoreText(match)}</b>
        <span><em>AWAY</em><strong>{match.awayTeam}</strong></span>
      </div>
      <div className="wm-worldcup-control-ticker">
        <i>{String(match.status || 'scheduled').toUpperCase()}</i>
        <i>{markets.length} markets</i>
        <i>{odds.length} odds feeds</i>
        <i>{match.city}</i>
      </div>
      <div className="wm-worldcup-control-grid">
        {factCards.map(([label, value, meta]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
            <em>{meta}</em>
          </div>
        ))}
      </div>
      <div className="wm-worldcup-mini-feed">
        {[...facts.slice(0, 3), ...broadcast.slice(0, 2)].map((item) => <SignalRow item={item} key={item.id} />)}
      </div>
    </Panel>
  );
}

function HostVenuePanel({
  payload,
  selectedCityId,
  onSelectCity,
  hostOps,
  risk,
  refVenue,
}: {
  payload: WorldCupDashboardPayload;
  selectedCityId: string | null;
  onSelectCity: (cityId: string) => void;
  hostOps: WorldCupSignalItem[];
  risk: WorldCupSignalItem[];
  refVenue: WorldCupSignalItem[];
}) {
  const cityWeather = payload.weather.map((weather) => ({
    weather,
    city: matchCity(payload.cities, weather.cityId),
    matchCount: payload.matches.filter((match) => match.cityId === weather.cityId).length,
  }));
  const selectedWeather = payload.weather.find((item) => item.cityId === selectedCityId) || payload.weather[0] || null;
  const opsMetrics = [
    ['WIND', selectedWeather?.current.windKph ?? 0, 'kph', 36],
    ['RAIN', selectedWeather?.current.precipitationProbability ?? 0, '%', 100],
    ['TRAVEL LOAD', Math.min(100, (payload.matches.filter((match) => match.cityId === selectedCityId).length || 1) * 9), '%', 100],
    ['DELAY RISK', /storm|rain/i.test(selectedWeather?.current.condition || '') ? 42 : 12, '%', 100],
  ] as const;
  return (
    <Panel title="HOST / VENUE OPS" count={cityWeather.length} className="wm-worldcup-panel wm-worldcup-host-venue-panel">
      {cityWeather.length ? (
        <>
          <div className="wm-worldcup-ops-metrics">
            {opsMetrics.map(([label, value, unit, max]) => (
              <span key={label}>
                <em>{label}</em>
                <strong>{value}{unit}</strong>
                <i style={{ width: `${Math.max(4, Math.min(100, (Number(value) / Number(max)) * 100))}%` }} />
              </span>
            ))}
          </div>
          <div className="wm-worldcup-city-strip">
            {cityWeather.slice(0, 16).map(({ city, weather, matchCount }) => (
              <button className={city.id === selectedCityId ? 'active' : ''} key={city.id} type="button" onClick={() => onSelectCity(city.id)}>
                <span>
                  <strong>{city.city}</strong>
                  <em>{city.country} · {matchCount} matches · {weather.current.condition}</em>
                </span>
                <b>{weather.current.tempC}C</b>
                <i>{weather.forecast.slice(0, 4).map((day) => `${formatWeatherDay(day.date)} ${day.lowC}/${day.highC}`).join(' · ')}</i>
              </button>
            ))}
          </div>
          <div className="wm-worldcup-mini-feed wm-worldcup-mini-feed-compact">
            {[...hostOps.slice(0, 2), ...risk.slice(0, 2), ...refVenue.slice(0, 2)].map((item) => <SignalRow item={item} key={item.id} />)}
          </div>
        </>
      ) : (
        <SourceRequired
          detail="Host ops uses real weather and venue metadata only. It is waiting for runtime weather before showing wind/rain/load rows."
          rows={[{ source: 'Open-Meteo runtime weather', status: 'required', detail: 'host-city current and forecast payload' }]}
        />
      )}
    </Panel>
  );
}

function MarketBoardPanel({
  markets,
  odds,
}: {
  markets: WorldCupPolymarketMarket[];
  odds: WorldCupOddsSnapshot[];
}) {
  const firstMarket = markets[0] || null;
  const totalVolume = markets.reduce((sum, market) => sum + (market.volume24h || 0), 0);
  return (
    <Panel
      title="MARKET BOARD"
      count={markets.length}
      titleControls={<InfoDot label="Only verified local DB / Polymarket market links are shown. No inferred market rows are generated." />}
      className="wm-worldcup-panel wm-worldcup-market-board-panel"
    >
      <div className="wm-worldcup-board-stats">
        <span><em>24H VOL</em><strong>{formatCompact(totalVolume)}</strong></span>
        <span><em>LINKS</em><strong>{markets.length}</strong></span>
        <span><em>BOOKS</em><strong>{odds.length}</strong></span>
        <span><em>CONF</em><strong>{firstMarket ? percentLabel(firstMarket.confidence * 100, 0) : '--'}</strong></span>
      </div>
      {markets.slice(0, 4).map((market, index) => (
        <article className="wm-worldcup-market-card" key={`${market.eventId || market.title}`}>
          <div className="wm-worldcup-card-head">
            <span>{formatCompact(market.volume24h)} · {Math.round(market.confidence * 100)} conf</span>
            <b>{index === 0 ? 'VERIFIED' : String(market.source || 'market').toUpperCase()}</b>
          </div>
          <strong>{market.title}</strong>
          <div className="wm-worldcup-prob-grid">
            {market.outcomes.slice(0, 3).map((outcome) => (
              <span key={outcome.name}>
                <em>{outcome.name}</em>
                <strong>{probabilityLabel(outcome.yesPrice)}</strong>
                <i style={{ width: probabilityWidth(outcome.yesPrice) }} />
              </span>
            ))}
          </div>
        </article>
      ))}
      {!markets.length ? (
        <SourceRequired
          detail="No trusted market row is available for this fixture. The board is intentionally empty until local DB/Gamma returns a matched event."
          rows={[{ source: 'Polymarket local DB / Gamma', status: 'not matched', detail: 'real outcomes and volume required' }]}
        />
      ) : null}
    </Panel>
  );
}

function TeamStatusPanel({
  payload,
  match,
  injuries,
  players,
}: {
  payload: WorldCupDashboardPayload;
  match: WorldCupMatch | null;
  injuries: WorldCupSignalItem[];
  players: WorldCupSignalItem[];
}) {
  const teams = match ? [match.homeTeam, match.awayTeam] : payload.rosters.slice(0, 2).map((roster) => roster.team);
  const rosters = payload.rosters.filter((roster) => teams.includes(roster.team));
  const rosterRows = rosters.slice(0, 2);
  return (
    <Panel title="TEAM STATUS" count={injuries.length + players.length} className="wm-worldcup-panel wm-worldcup-team-status-panel">
      {rosterRows.length ? (
        <div className="wm-worldcup-team-grid">
          {rosterRows.map((roster) => {
            const confirmed = roster.players.filter((player) => player.status === 'confirmed').length;
            const injured = roster.players.filter((player) => player.status === 'injured').length;
            const ready = roster.players.length ? Math.round((confirmed / roster.players.length) * 100) : 0;
            return (
              <section key={roster.team}>
                <header><strong>{roster.team}</strong><span>{roster.players.length} players</span></header>
                <div className="wm-worldcup-team-meter"><i style={{ width: `${Math.max(2, ready)}%` }} /><b>{ready}% ready</b></div>
                <p>{injured ? `${injured} injury flags` : 'No injury flag in connected roster feed'}</p>
                {roster.players.slice(0, 4).map((player) => (
                  <div className="wm-worldcup-team-row" key={`${roster.team}-${player.name}`}>
                    <span>{player.position || 'ALL'}</span>
                    <strong>{player.name}</strong>
                    <em>{player.status || 'watch'}</em>
                  </div>
                ))}
              </section>
            );
          })}
        </div>
      ) : (
        <SourceRequired
          detail="Team status is hidden until official roster and injury status feeds are connected."
          rows={[{ source: 'Federation squads / ESPN injury tracker', status: 'required', detail: 'player-level availability' }]}
        />
      )}
      <div className="wm-worldcup-status-table">
        {[...injuries.slice(0, 3), ...players.slice(0, 3)].map((item) => (
          <div key={item.id}>
            <span>{cleanSignalSource(item.source)}</span>
            <strong>{item.title}</strong>
            <SignalTags tags={item.tags} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

function LineupBoardPanel({
  lineups,
  squadSignals,
}: {
  lineups: WorldCupSignalItem[];
  squadSignals: WorldCupSignalItem[];
}) {
  return (
    <Panel title="LINEUP BOARD" count={lineups.length} className="wm-worldcup-panel wm-worldcup-lineup-board-panel">
      {lineups.length || squadSignals.length ? (
        <div className="wm-worldcup-mini-feed wm-worldcup-mini-feed-compact">
          {[...lineups.slice(0, 4), ...squadSignals.slice(0, 2)].map((item) => <SignalRow item={item} key={item.id} />)}
        </div>
      ) : (
        <SourceRequired
          detail="Predicted XI and confirmed lineup cards require Flashscore/SofaScore/FotMob or official team feeds. Formation boards are not fabricated."
          rows={[
            { source: 'Official team sheets', status: 'required', detail: 'T-60 confirmed XI' },
            { source: 'Flashscore / SofaScore / FotMob', status: 'required', detail: 'predicted XI and formation feed' },
          ]}
        />
      )}
    </Panel>
  );
}

function MatchModelPanel({
  xgSignals,
  tacticalSignals,
}: {
  xgSignals: WorldCupSignalItem[];
  tacticalSignals: WorldCupSignalItem[];
}) {
  const rows = [...xgSignals, ...tacticalSignals].slice(0, 6);
  return (
    <Panel title="MATCH MODEL" count={rows.length} className="wm-worldcup-panel wm-worldcup-model-panel">
      {rows.length ? (
        <div className="wm-worldcup-model-table">
          {rows.map((item) => (
            <div key={item.id}>
              <span>{cleanSignalSource(item.source)}</span>
              <strong>{item.title}</strong>
              <em>{item.summary}</em>
            </div>
          ))}
        </div>
      ) : (
        <SourceRequired
          detail="xG, set-piece and transition metrics are disabled until a licensed statistical feed or model service supplies values."
          rows={[
            { source: 'Opta / StatsBomb / FBref / SofaScore', status: 'required', detail: 'xG, xGA, shots, pressure and player events' },
          ]}
        />
      )}
    </Panel>
  );
}

function MediaWirePanel({
  news,
  matchSignals,
  localMedia,
}: {
  news: ReturnType<typeof filterWorldCupNews>;
  matchSignals: WorldCupSignalItem[];
  localMedia: WorldCupSignalItem[];
}) {
  const newsSignals: WorldCupSignalItem[] = news.slice(0, 8).map((item) => {
    const tags = newsTags(item);
    const firstTone = tags[0]?.tone;
    return {
      id: `news-wire-${item.id}`,
      source: item.source,
      title: item.title,
      summary: item.summary || 'World Cup desk monitors source, tag, match and market context.',
      age: item.publishedAt,
      tags: tags.map((tag) => ({ label: tag.label, tone: coerceSignalTone(tag.tone) })),
      accent: firstTone ? coerceSignalTone(firstTone) : 'blue',
    };
  });
  return (
    <Panel title="MEDIA / INTEL WIRE" count={news.length + localMedia.length} className="wm-worldcup-panel wm-worldcup-media-wire-panel">
      <div className="wm-worldcup-wire-columns">
        <section>
          <header><strong>GLOBAL</strong><span>{newsSignals.length}</span></header>
          {newsSignals.slice(0, 4).map((item) => <SignalRow item={item} key={item.id} />)}
        </section>
        <section>
          <header><strong>LOCAL / MATCH</strong><span>{localMedia.length + matchSignals.length}</span></header>
          {[...localMedia.slice(0, 3), ...matchSignals.slice(0, 2)].map((item) => <SignalRow item={item} key={item.id} />)}
        </section>
      </div>
    </Panel>
  );
}

function OddsLiquidityPanel({
  odds,
  markets,
  oddsSignals,
  marketSignals,
}: {
  odds: WorldCupOddsSnapshot[];
  markets: WorldCupPolymarketMarket[];
  oddsSignals: WorldCupSignalItem[];
  marketSignals: WorldCupSignalItem[];
}) {
  const liquidity = markets.reduce((sum, market) => sum + (market.liquidity || market.volume24h || 0), 0);
  return (
    <Panel title="ODDS / LIQUIDITY" count={odds.length + markets.length} className="wm-worldcup-panel wm-worldcup-odds-liquidity-panel">
      <div className="wm-worldcup-liquidity-strip">
        <span><em>LIQUIDITY</em><strong>{formatCompact(liquidity)}</strong></span>
        <span><em>ODDS FEEDS</em><strong>{odds.length}</strong></span>
        <span><em>MARKETS</em><strong>{markets.length}</strong></span>
      </div>
      <div className="wm-worldcup-odds-table">
        {odds.slice(0, 5).map((snapshot) => (
          <article key={`${snapshot.matchId}-${snapshot.provider}`}>
            <header><strong>{snapshot.provider}</strong><span>{String(snapshot.providerType || 'provider').replace('_', ' ')}</span></header>
            <div>
              {snapshot.outcomes.slice(0, 3).map((outcome) => (
                <span key={outcome.name}>
                  <em>{outcome.name}</em>
                  <b>{formatNumber(outcome.decimalOdds, 2)}</b>
                  <i style={{ width: `${Math.max(3, Math.min(100, outcome.impliedProbability || 0))}%` }} />
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>
      <div className="wm-worldcup-mini-feed wm-worldcup-mini-feed-tight">
        {[...oddsSignals.slice(0, 2), ...marketSignals.slice(0, 2)].map((item) => <SignalRow item={item} key={item.id} />)}
      </div>
      {!odds.length && !markets.length ? (
        <SourceRequired
          detail="No odds or liquidity feed is connected for the selected match. The panel is waiting for real bookmaker or market data."
          rows={[
            { source: 'Bookmaker odds API', status: 'required', detail: 'moneyline/totals snapshots' },
            { source: 'Polymarket local DB / Gamma', status: 'not matched', detail: 'liquidity and outcome prices' },
          ]}
        />
      ) : null}
    </Panel>
  );
}

function VenueRefPanel({
  refVenue,
  risk,
  payload,
  match,
}: {
  refVenue: WorldCupSignalItem[];
  risk: WorldCupSignalItem[];
  payload: WorldCupDashboardPayload;
  match: WorldCupMatch | null;
}) {
  const city = match ? matchCity(payload.cities, match.cityId) : payload.cities[0];
  if (!city) {
    return (
      <Panel title="REF / VENUE BOARD" count={0} className="wm-worldcup-panel wm-worldcup-venue-ref-panel">
        <div className="wm-worldcup-empty">No venue selected.</div>
      </Panel>
    );
  }
  const venueCity = city;
  const nearbyMatches = payload.matches.filter((item) => item.cityId === venueCity.id).slice(0, 5);
  return (
    <Panel title="REF / VENUE BOARD" count={refVenue.length + nearbyMatches.length} className="wm-worldcup-panel wm-worldcup-venue-ref-panel">
      <div className="wm-worldcup-venue-card">
        <span>{venueCity.countryName}</span>
        <strong>{venueCity.venue}</strong>
        <em>{venueCity.city} · {venueCity.capacity ? venueCity.capacity.toLocaleString() : '--'} seats · {venueCity.timezone}</em>
      </div>
      <div className="wm-worldcup-venue-fixtures">
        {nearbyMatches.map((item) => (
          <span key={item.id}>
            <em>#{item.fifaMatchNumber || '--'} {item.group || stageLabel(item.stage)}</em>
            <strong>{item.homeTeam} vs {item.awayTeam}</strong>
            <b>{item.kickoffBeijing}</b>
          </span>
        ))}
      </div>
      <div className="wm-worldcup-mini-feed wm-worldcup-mini-feed-compact">
        {[...refVenue.slice(0, 3), ...risk.slice(0, 2)].map((item) => <SignalRow item={item} key={item.id} />)}
      </div>
    </Panel>
  );
}

function GroupAdvancePanel({
  matches,
  group,
  onGroupChange,
}: {
  matches: WorldCupMatch[];
  group: string;
  onGroupChange: (group: string) => void;
}) {
  const groups = buildGroupNames(matches);
  const standings = buildGroupStandings(matches, group);
  const rows = standings;
  const groupFixtures = matches.filter((match) => match.group === group);
  return (
    <Panel title="GROUP ADVANCE" count={rows.length} className="wm-worldcup-panel wm-worldcup-group-advance-panel">
      <div className="wm-worldcup-mini-tabs">
        {groups.slice(0, 8).map((item) => (
          <button className={item === group ? 'active' : ''} key={item} type="button" onClick={() => onGroupChange(item)}>
            {String(item || 'Group').replace('Group ', '')}
          </button>
        ))}
      </div>
      <div className="wm-worldcup-advance-table">
        <header><span>TEAM</span><span>P</span><span>PTS</span><span>GD</span><span>FIX</span></header>
        {rows.map((row, index) => (
          <div key={row.team}>
            <strong>{index + 1}. {row.team}</strong>
            <b>{row.played}</b>
            <b>{row.pts}</b>
            <b>{row.gf - row.ga}</b>
            <span><em>{groupFixtures.filter((match) => match.homeTeam === row.team || match.awayTeam === row.team).length}</em><i style={{ width: `${Math.max(4, row.played * 33)}%` }} /></span>
          </div>
        ))}
      </div>
      {!rows.length ? (
        <SourceRequired
          detail="No verified group rows are available. Advance and win-group probabilities are not generated without a real standings/probability source."
          rows={[{ source: 'FIFA Match Centre / official standings', status: 'required', detail: 'played, points, goals and qualification state' }]}
        />
      ) : null}
    </Panel>
  );
}

function TeamPowerPanel({ payload, match }: { payload: WorldCupDashboardPayload; match: WorldCupMatch | null }) {
  const teams = match ? [match.homeTeam, match.awayTeam] : payload.rosters.slice(0, 2).map((roster) => roster.team);
  const rows = teams.map((team) => {
    const roster = payload.rosters.find((item) => item.team === team);
    const confirmed = roster?.players.filter((player) => player.status === 'confirmed').length ?? 0;
    const injured = roster?.players.filter((player) => player.status === 'injured').length ?? 0;
    return { team, rosterCount: roster?.players.length ?? 0, confirmed, injured };
  });
  return (
    <Panel title="TEAM POWER" count={rows.length} className="wm-worldcup-panel wm-worldcup-team-power-panel">
      {payload.rosters.length ? (
        <div className="wm-worldcup-power-grid">
          {rows.map((row) => (
            <section key={row.team}>
              <header><strong>{row.team}</strong><span>{row.rosterCount} players</span></header>
              {[
                ['CONFIRMED', row.confirmed, Math.max(1, row.rosterCount)],
                ['INJURY FLAGS', row.injured, Math.max(1, row.rosterCount)],
                ['ROSTER ROWS', row.rosterCount, 26],
              ].map(([label, value, max]) => (
                <div key={label}>
                  <span>{label}</span>
                  <b>{value}</b>
                  <i style={{ width: `${clampNumber((Number(value) / Number(max)) * 100, 4, 100)}%` }} />
                </div>
              ))}
            </section>
          ))}
        </div>
      ) : (
        <SourceRequired
          detail="Team power cannot be computed without a real squad/rating provider. Elo, form and market value are not estimated in the browser."
          rows={[
            { source: 'FIFA ranking / Elo provider', status: 'required', detail: 'team rating and form inputs' },
            { source: 'Official squads', status: 'required', detail: 'confirmed player pool and availability' },
          ]}
        />
      )}
    </Panel>
  );
}

function InjuryLoadPanel({ payload, match, injuries }: { payload: WorldCupDashboardPayload; match: WorldCupMatch | null; injuries: WorldCupSignalItem[] }) {
  const teams = match ? [match.homeTeam, match.awayTeam] : payload.rosters.slice(0, 2).map((roster) => roster.team);
  const rows = teams.map((team) => {
    const roster = payload.rosters.find((item) => item.team === team);
    const injured = roster?.players.filter((player) => player.status === 'injured').length ?? 0;
    const load = roster?.players.length ? clampNumber(injured * 26, 0, 96) : 0;
    return { team, injured, load, hasRoster: Boolean(roster?.players.length) };
  });
  return (
    <Panel title="INJURY LOAD" count={injuries.length} className="wm-worldcup-panel wm-worldcup-injury-load-panel">
      {rows.some((row) => row.hasRoster) ? (
        <div className="wm-worldcup-load-grid">
          {rows.map((row) => (
            <section key={row.team}>
              <header><strong>{row.team}</strong><span className={row.load > 55 ? 'red' : 'green'}>{row.load}/100</span></header>
              <div><span>INJURED</span><b>{row.injured}</b></div>
              <i style={{ width: `${row.load}%` }} />
            </section>
          ))}
        </div>
      ) : null}
      {injuries.length ? (
        <div className="wm-worldcup-load-list">
          {injuries.slice(0, 5).map((item) => (
            <span key={item.id}><b>{cleanSignalSource(item.source)}</b><strong>{item.title}</strong></span>
          ))}
        </div>
      ) : (
        <SourceRequired
          detail="No verified injury feed is available for this match. Doubtful/suspended counts are not guessed."
          rows={[{ source: 'ESPN injury tracker / official team medical notes', status: 'required', detail: 'player-level status with timestamp' }]}
        />
      )}
    </Panel>
  );
}

function MatchTempoPanel({ xgSignals, tacticalSignals }: { xgSignals: WorldCupSignalItem[]; tacticalSignals: WorldCupSignalItem[] }) {
  const rows = [...xgSignals, ...tacticalSignals].slice(0, 6);
  return (
    <Panel title="MATCH TEMPO" count={rows.length} className="wm-worldcup-panel wm-worldcup-tempo-panel">
      {rows.length ? (
        <div className="wm-worldcup-model-table">
          {rows.map((item) => (
            <div key={item.id}>
              <span>{cleanSignalSource(item.source)}</span>
              <strong>{item.title}</strong>
              <em>{item.summary}</em>
            </div>
          ))}
        </div>
      ) : (
        <SourceRequired
          detail="Tempo metrics need real event/team data. xG, shots, corners, cards, pace and press are not estimated from fixture names."
          rows={[
            { source: 'Opta / StatsBomb / FBref / SofaScore', status: 'required', detail: 'xG, shots, corners, cards and pressure metrics' },
          ]}
        />
      )}
    </Panel>
  );
}

function RefCardsPanel({ refVenue }: { refVenue: WorldCupSignalItem[] }) {
  return (
    <Panel title="REF / CARDS" count={refVenue.length} className="wm-worldcup-panel wm-worldcup-ref-cards-panel">
      {refVenue.length ? (
        <div className="wm-worldcup-ref-list">
          {refVenue.slice(0, 5).map((item) => <SignalRow item={item} key={item.id} />)}
        </div>
      ) : (
        <SourceRequired
          detail="Card profile requires assigned referee history and match-official data. No yellow/red/foul values are generated."
          rows={[{ source: 'FIFA referee appointments / historical referee stats', status: 'required', detail: 'cards, fouls, penalties and VAR tendency' }]}
        />
      )}
    </Panel>
  );
}

function TravelLoadPanel({ payload, match }: { payload: WorldCupDashboardPayload; match: WorldCupMatch | null }) {
  const teams = match ? [match.homeTeam, match.awayTeam] : payload.rosters.slice(0, 2).map((roster) => roster.team);
  return (
    <Panel title="TRAVEL LOAD" count={0} className="wm-worldcup-panel wm-worldcup-travel-load-panel">
      <SourceRequired
        detail={`Travel load for ${teams.join(' / ') || 'selected teams'} requires actual team-base, previous-match and travel itinerary data. Distances and rest windows are not synthesized.`}
        rows={[
          { source: 'Official team base / federation logistics', status: 'required', detail: 'team camp location and travel dates' },
          { source: 'FIFA fixture history', status: payload.matches.length ? 'partial schedule only' : 'required', detail: 'previous fixture and recovery window' },
        ]}
      />
    </Panel>
  );
}

function VenueRiskPanel({ payload, match, weather }: { payload: WorldCupDashboardPayload; match: WorldCupMatch | null; weather?: WorldCupDashboardPayload['weather'][number] | null }) {
  const city = match ? matchCity(payload.cities, match.cityId) : payload.cities[0];
  const matchCount = city ? Math.max(WORLD_CUP_HOST_MATCH_COUNTS[city.id] || 0, payload.matches.filter((item) => item.cityId === city.id).length) : 0;
  if (!weather) {
    return (
      <Panel title="VENUE RISK" count={0} className="wm-worldcup-panel wm-worldcup-venue-risk-panel">
        <SourceRequired
          detail="Venue risk is calculated only from live weather plus real host-city match count. No default temperature or rain values are used."
          rows={[{ source: 'Open-Meteo runtime weather', status: 'required', detail: 'temperature, wind and precipitation probability by host city' }]}
        />
      </Panel>
    );
  }
  const temp = weather.current.tempC;
  const rain = weather.current.precipitationProbability || 0;
  const wind = weather.current.windKph || 0;
  const risk = clampNumber(Math.round((temp > 27 ? 18 : 6) + rain * 0.35 + wind * 0.7 + matchCount * 1.4), 5, 96);
  const metrics = [
    ['TEMP', temp, 36, 'gold'],
    ['RAIN', rain, 100, 'blue'],
    ['WIND', wind, 40, 'purple'],
    ['LOAD', matchCount * 6, 100, 'green'],
  ] as const;
  return (
    <Panel title="VENUE RISK" count={risk} className="wm-worldcup-panel wm-worldcup-venue-risk-panel">
      <div className="wm-worldcup-risk-score">
        <span><em>{city?.city || 'Host city'}</em><strong>{risk}/100</strong><b>{weather?.current.condition || 'venue watch'}</b></span>
      </div>
      <div className="wm-worldcup-risk-grid">
        {metrics.map(([label, value, max, tone]) => (
          <span className={tone} key={label}>
            <em>{label}</em>
            <strong>{value}{label === 'TEMP' ? 'C' : label === 'WIND' ? 'kph' : '%'}</strong>
            <i style={{ width: `${clampNumber((Number(value) / Number(max)) * 100, 4, 100)}%` }} />
          </span>
        ))}
      </div>
    </Panel>
  );
}

function NewsImpactPanel({ news }: { news: ReturnType<typeof filterWorldCupNews> }) {
  const rows = news.slice(0, 10).map((item) => {
    const tags = newsTags(item);
    const market = tags.find((tag) => tag.label === 'MARKET') ? 'market' : tags.find((tag) => tag.label === 'TEAM') ? 'lineup' : tags.find((tag) => tag.label === 'WEATHER') ? 'venue' : 'match';
    return { item, tags, market };
  });
  return (
    <Panel title="NEWS IMPACT" count={rows.length} className="wm-worldcup-panel wm-worldcup-news-impact-panel">
      {rows.length ? (
        <div className="wm-worldcup-impact-list">
          {rows.map(({ item, tags, market }) => (
            <article key={item.id}>
              <div><span>{item.source}</span>{tags.map((tag) => <b className={`wm-worldcup-feed-tag ${tag.tone}`} key={`${item.id}-${tag.label}`}>{tag.label}</b>)}</div>
              <strong>{item.title}</strong>
              <footer><em>{market}</em><span><b>{new Date(item.publishedAt).toLocaleString('en-US', { hour12: false })}</b></span></footer>
            </article>
          ))}
        </div>
      ) : (
        <SourceRequired
          detail="News impact scoring is disabled until a real classifier/model service is connected. The panel will not hash titles into fake scores."
          rows={[{ source: 'News classifier / market reaction model', status: 'required', detail: 'impact score must be computed server-side with provenance' }]}
        />
      )}
    </Panel>
  );
}

function groupName(match: WorldCupMatch | null) {
  return match?.group || 'Group A';
}

function buildGroupNames(matches: WorldCupMatch[]) {
  const groups = Array.from(new Set(matches.map((match) => match.group).filter(Boolean))) as string[];
  return groups.length ? groups.sort((a, b) => a.localeCompare(b)) : ['Group A'];
}

function buildGroupStandings(matches: WorldCupMatch[], group: string) {
  const table = new Map<string, { team: string; played: number; gf: number; ga: number; pts: number }>();
  const ensure = (team: string) => {
    if (!table.has(team)) table.set(team, { team, played: 0, gf: 0, ga: 0, pts: 0 });
    return table.get(team)!;
  };
  matches.filter((match) => (match.group || '') === group).forEach((match) => {
    const home = ensure(match.homeTeam);
    const away = ensure(match.awayTeam);
    if (match.homeScore === undefined || match.awayScore === undefined) return;
    home.played += 1;
    away.played += 1;
    home.gf += match.homeScore;
    home.ga += match.awayScore;
    away.gf += match.awayScore;
    away.ga += match.homeScore;
    if (match.homeScore > match.awayScore) home.pts += 3;
    else if (match.homeScore < match.awayScore) away.pts += 3;
    else {
      home.pts += 1;
      away.pts += 1;
    }
  });
  return Array.from(table.values()).sort((a, b) => b.pts - a.pts || (b.gf - b.ga) - (a.gf - a.ga) || a.team.localeCompare(b.team));
}

function GroupTablePanel({
  matches,
  group,
  onGroupChange,
}: {
  matches: WorldCupMatch[];
  group: string;
  onGroupChange: (group: string) => void;
}) {
  const groups = buildGroupNames(matches);
  const groupMatches = matches.filter((match) => (match.group || '') === group);
  const standings = buildGroupStandings(matches, group);
  return (
    <Panel title="GROUP TABLE" count={groupMatches.length} className="wm-worldcup-panel wm-worldcup-group-table-panel">
      <div className="wm-worldcup-group-tabs">
        {groups.slice(0, 12).map((item) => (
          <button className={item === group ? 'active' : ''} key={item} type="button" onClick={() => onGroupChange(item)}>
            {String(item || 'Group').replace('Group ', '')}
          </button>
        ))}
      </div>
      <div className="wm-worldcup-standings">
        <div className="wm-worldcup-standings-head">
          <span>TEAM</span><span>P</span><span>GD</span><span>PTS</span>
        </div>
        {standings.map((row, index) => (
          <div className="wm-worldcup-standings-row" key={row.team}>
            <strong>{index + 1}. {row.team}</strong>
            <span>{row.played}</span>
            <span>{row.gf - row.ga}</span>
            <b>{row.pts}</b>
          </div>
        ))}
      </div>
      <div className="wm-worldcup-group-match-feed">
        {groupMatches.slice(0, 8).map((match) => (
          <button key={match.id} type="button" className="wm-worldcup-group-match-row">
            <span>#{match.fifaMatchNumber || '--'} · {match.round}</span>
            <strong>{match.homeTeam} <i>{scoreText(match)}</i> {match.awayTeam}</strong>
            <em>{match.kickoffBeijing} · {match.city}</em>
          </button>
        ))}
      </div>
    </Panel>
  );
}

function buildMatchSignals(match: WorldCupMatch | null, markets: WorldCupPolymarketMarket[]): WorldCupSignalItem[] {
  if (!match) return [];
  const group = match.group || stageLabel(match.stage);
  return [
    {
      id: 'match-clock',
      source: 'MATCH DESK',
      title: `${match.homeTeam} vs ${match.awayTeam}: kickoff control and match state`,
      summary: `${match.kickoffBeijing || match.kickoffUtc || 'Kickoff pending'} Beijing · ${match.kickoffLocal || 'local pending'} local · ${String(match.status || 'scheduled').toUpperCase()}`,
      age: '',
      tags: [{ label: 'SCHEDULE', tone: 'green' }, { label: group, tone: 'gold' }],
      accent: 'green',
    },
    {
      id: 'match-venue',
      source: 'VENUE OPS',
      title: `${match.venue}: host venue readiness and pitch watch`,
      summary: `${match.city}. Venue and city metadata come from the dashboard host-city registry.`,
      age: '',
      tags: [{ label: 'VENUE', tone: 'blue' }],
      accent: 'blue',
    },
    {
      id: 'match-market',
      source: 'POLYDATA',
      title: `${markets.length} linked market candidates for selected fixture`,
      summary: 'Only local DB / Polymarket matched markets are counted.',
      age: '',
      tags: [{ label: 'MARKET', tone: 'purple' }],
      accent: 'purple',
    },
  ];
}

function buildHostOpsSignals(payload: WorldCupDashboardPayload, selectedCityId: string | null): WorldCupSignalItem[] {
  return payload.weather.slice(0, 12).map((weather, index) => {
    const city = matchCity(payload.cities, weather.cityId);
    const matchCount = Math.max(
      WORLD_CUP_HOST_MATCH_COUNTS[weather.cityId] || 0,
      payload.matches.filter((match) => match.cityId === weather.cityId).length,
    );
    const active = city.id === selectedCityId;
    return {
      id: `host-${city.id}`,
      source: active ? 'SELECTED HOST' : 'HOST OPS',
      title: `${city.city}: ${matchCount} matches, ${city.venue}`,
      summary: `${weather.current.tempC}C · ${weather.current.condition} · wind ${weather.current.windKph || '--'} kph · rain ${weather.current.precipitationProbability || 0}%`,
      age: weather.generatedAt,
      tags: [
        { label: active ? 'ACTIVE' : 'WEATHER', tone: active ? 'green' : 'blue' },
        { label: String(weather.current.condition || 'WEATHER').toUpperCase(), tone: /storm|rain/i.test(weather.current.condition || '') ? 'red' : 'gold' },
      ],
      accent: active ? 'green' : index % 3 === 0 ? 'blue' : 'gold',
    } satisfies WorldCupSignalItem;
  });
}

function buildMarketSignals(markets: WorldCupPolymarketMarket[], match: WorldCupMatch | null): WorldCupSignalItem[] {
  if (!match) return [];
  return markets.flatMap<WorldCupSignalItem>((market, marketIndex) => [
    {
      id: `market-${marketIndex}-headline`,
      source: String(market.source || 'market').toUpperCase(),
      title: market.title,
      summary: `${Math.round(market.confidence * 100)} confidence · 24h volume ${formatCompact(market.volume24h)} · ${market.outcomes.length} outcomes`,
      age: '',
      tags: [{ label: 'MARKET', tone: 'purple' }],
      accent: marketIndex % 2 ? 'blue' : 'purple',
    },
    {
      id: `market-${marketIndex}-price`,
      source: 'PRICE WATCH',
      title: market.outcomes.slice(0, 3).map((outcome) => `${outcome.name} ${outcome.yesPrice == null ? '--' : `${(outcome.yesPrice * 100).toFixed(1)}%`}`).join(' · '),
      summary: 'Outcome spread is displayed only from real market outcome prices.',
      age: '',
      tags: [{ label: 'ODDS', tone: 'gold' }, { label: 'SPREAD', tone: 'blue' }],
      accent: 'gold',
    },
  ]).slice(0, 10);
}

function buildSquadSignals(payload: WorldCupDashboardPayload, match: WorldCupMatch | null): WorldCupSignalItem[] {
  const teams = match ? [match.homeTeam, match.awayTeam] : payload.rosters.slice(0, 2).map((roster) => roster.team);
  const rosters = payload.rosters.filter((roster) => teams.includes(roster.team));
  return rosters.flatMap((roster) => roster.players.map((player) => ({
    id: `squad-${roster.team}-${player.name}`,
      source: roster.team,
      title: player.name,
    summary: `${player.position || 'ALL'} · ${player.club || player.status || 'official roster row'}`,
    age: roster.updatedAt,
    tags: [
      { label: player.status?.toUpperCase() || 'PLAYER', tone: player.status === 'injured' ? 'red' : 'gold' },
      { label: 'TEAM', tone: 'green' },
    ],
    accent: player.status === 'injured' ? 'red' : 'blue',
  } satisfies WorldCupSignalItem))).slice(0, 8);
}

function buildOddsSignals(odds: WorldCupOddsSnapshot[], match: WorldCupMatch | null): WorldCupSignalItem[] {
  const snapshots = odds.length ? odds : [];
  return snapshots.slice(0, 8).map((snapshot, index) => ({
    id: `odds-${snapshot.matchId}-${snapshot.provider}-${index}`,
    source: String(snapshot.providerType || 'provider').replace('_', ' ').toUpperCase(),
    title: snapshot.provider,
    summary: snapshot.outcomes.map((outcome) => `${outcome.name} ${formatNumber(outcome.decimalOdds, 2)} / ${formatNumber(outcome.impliedProbability, 1)}%`).join(' · '),
    age: snapshot.generatedAt || (match ? match.kickoffBeijing : ''),
    tags: [{ label: String(snapshot.marketType || 'odds').toUpperCase(), tone: 'purple' }],
    accent: index % 2 ? 'purple' : 'blue',
  }));
}

function buildRiskSignals(payload: WorldCupDashboardPayload, match: WorldCupMatch | null): WorldCupSignalItem[] {
  const selected = match || payload.matches[0] || null;
  const weather = selected ? payload.weather.find((item) => item.cityId === selected.cityId) : null;
  if (!weather) return [];
  return [
    {
      id: 'risk-weather',
      source: 'WEATHER RISK',
      title: selected ? `${selected.city}: ${weather?.current.condition || 'host conditions'} before kickoff` : 'Host weather monitor',
      summary: `Temperature ${weather?.current.tempC ?? '--'}C · precipitation ${weather?.current.precipitationProbability ?? 0}% · wind ${weather?.current.windKph ?? '--'} kph.`,
      age: weather.generatedAt,
      tags: [{ label: 'ALERT', tone: /storm|rain/i.test(weather?.current.condition || '') ? 'red' : 'gold' }, { label: 'WEATHER', tone: 'blue' }],
      accent: /storm|rain/i.test(weather?.current.condition || '') ? 'red' : 'gold',
    },
  ];
}

function buildBroadcastSignals(match: WorldCupMatch | null): WorldCupSignalItem[] {
  if (!match) return [];
  return [
    {
      id: 'broadcast-bjt',
      source: 'BROADCAST',
      title: `${match.homeTeam} vs ${match.awayTeam}: Beijing time window`,
      summary: `${match.kickoffBeijing}. Desk view keeps BJT, local kickoff and venue status together.`,
      age: '',
      tags: [{ label: 'BJT', tone: 'green' }, { label: 'LIVE OPS', tone: 'blue' }],
      accent: 'green',
    },
    {
      id: 'broadcast-local',
      source: 'LOCAL FEED',
      title: `${match.city}: local matchday handoff`,
      summary: `${match.kickoffLocal}. Host city context is paired with weather and venue ops.`,
      age: '',
      tags: [{ label: 'LOCAL', tone: 'blue' }, { label: 'VENUE', tone: 'gold' }],
      accent: 'blue',
    },
    {
      id: 'broadcast-market',
      source: 'MARKET FEED',
      title: 'Market desk watches news latency and odds spread',
      summary: 'News tags, source age and market confidence are normalized into the same row grammar.',
      age: '',
      tags: [{ label: 'MARKET', tone: 'purple' }, { label: 'WATCH', tone: 'gray' }],
      accent: 'purple',
    },
  ];
}

function buildOfficialFactSignals(payload: WorldCupDashboardPayload, match: WorldCupMatch | null, city: WorldCupDashboardPayload['cities'][number] | null): WorldCupSignalItem[] {
  const liveSignals = runtimeSignalItems(payload, 'officialFacts', match);
  if (!match) return liveSignals;
  const cityMatches = payload.matches.filter((item) => item.cityId === match.cityId).slice(0, 3);
  const factRows: WorldCupSignalItem[] = [
    {
      id: 'facts-match-centre',
      source: payload.cacheMode === 'remote' ? 'SCHEDULE SOURCE' : 'SCHEDULE SOURCE REQUIRED',
      title: `${match.homeTeam} vs ${match.awayTeam}: fixture identity verified`,
      summary: `Match #${match.fifaMatchNumber || '--'} · ${match.group || stageLabel(match.stage)} · ${match.round}. Official FIFA API connector is still required for final verification.`,
      age: '',
      tags: [{ label: 'FACT', tone: 'green' }, { label: payload.cacheMode === 'remote' ? 'REMOTE' : 'REQUIRED', tone: payload.cacheMode === 'remote' ? 'blue' : 'red' }],
      accent: 'green',
    },
    {
      id: 'facts-kickoff',
      source: 'WORLD CUP DESK',
      title: `Kickoff lock: ${match.kickoffBeijing} BJT / ${match.kickoffLocal} local`,
      summary: 'Beijing desk, local desk and venue desk should all reference this same match card.',
      age: '',
      tags: [{ label: 'TIME', tone: 'blue' }, { label: 'VERIFY', tone: 'gray' }],
      accent: 'blue',
    },
    {
      id: 'facts-venue',
      source: 'HOST CITY',
      title: `${match.venue}, ${match.city}`,
      summary: `${city?.countryName || 'Host country'} · capacity ${city?.capacity ? city.capacity.toLocaleString() : 'pending'} · timezone ${city?.timezone || 'local'}.`,
      age: '',
      tags: [{ label: 'VENUE', tone: 'gold' }, { label: 'OPS', tone: 'green' }],
      accent: 'gold',
    },
    {
      id: 'facts-team-source',
      source: 'TEAM CHANNELS',
      title: 'National team official channels are not connected yet',
      summary: 'Roster and injury panels remain empty unless federation/team data is ingested.',
      age: '',
      tags: [{ label: 'ROSTER', tone: 'purple' }, { label: 'REQUIRED', tone: 'red' }],
      accent: 'purple',
    },
    {
      id: 'facts-city-window',
      source: 'HOST SCHEDULE',
      title: `${match.city}: host-city match window and operational load`,
      summary: `${cityMatches.length || 1} visible fixture rows in this city panel · venue, weather and travel context share the same city key.`,
      age: '',
      tags: [{ label: 'CITY', tone: 'blue' }, { label: 'OPS', tone: 'gold' }],
      accent: 'blue',
    },
    {
      id: 'facts-market-link',
      source: 'POLYDATA',
      title: 'Market identity requires a real local DB / Gamma hit',
      summary: 'No inferred market rows are generated when a matching market is absent.',
      age: '',
      tags: [{ label: 'MARKET', tone: 'purple' }, { label: 'VERIFY', tone: 'green' }],
      accent: 'purple',
    },
    {
      id: 'facts-status-rules',
      source: 'MATCH STATE',
      title: `Current state: ${String(match.status || 'scheduled').toUpperCase()}${match.minute ? ` · ${match.minute}` : ''}`,
      summary: 'Scheduled, live, finished and postponed states drive calendar filters, match detail and group table updates.',
      age: '',
      tags: [{ label: 'STATE', tone: 'green' }, { label: String(match.status || 'scheduled').toUpperCase(), tone: match.status === 'postponed' ? 'red' : 'gold' }],
      accent: match.status === 'postponed' ? 'red' : 'green',
    },
    ...cityMatches.map((cityMatch) => ({
      id: `facts-city-match-${cityMatch.id}`,
      source: 'CITY FIXTURE',
      title: `#${cityMatch.fifaMatchNumber || '--'} ${cityMatch.homeTeam} vs ${cityMatch.awayTeam}`,
      summary: `${cityMatch.kickoffBeijing} BJT · ${cityMatch.group || stageLabel(cityMatch.stage)} · ${cityMatch.venue}.`,
      age: '',
      tags: [{ label: 'FIXTURE', tone: 'blue' }, { label: cityMatch.group || stageLabel(cityMatch.stage), tone: 'gold' }],
      accent: 'blue',
    } satisfies WorldCupSignalItem)),
  ];
  return mergeSignalRows(liveSignals, factRows).slice(0, 12);
}

function buildInjurySignals(payload: WorldCupDashboardPayload, match: WorldCupMatch | null): WorldCupSignalItem[] {
  return runtimeSignalItems(payload, 'injuryTracker', match).slice(0, 12);
}

function buildLineupSignals(payload: WorldCupDashboardPayload, match: WorldCupMatch | null): WorldCupSignalItem[] {
  return runtimeSignalItems(payload, 'lineupWatch', match).slice(0, 10);
}

function buildPlayerPoolSignals(payload: WorldCupDashboardPayload, match: WorldCupMatch | null): WorldCupSignalItem[] {
  const focusTeams = match ? [match.homeTeam, match.awayTeam] : payload.rosters.slice(0, 4).map((roster) => roster.team);
  return payload.rosters
    .filter((roster) => focusTeams.includes(roster.team))
    .flatMap<WorldCupSignalItem>((roster) => [
      {
        id: `pool-${roster.team}-status`,
        source: roster.team,
        title: `${roster.team}: final roster window`,
        summary: `${roster.players.length || 0} roster candidates · official federation squad page remains authority.`,
        age: '',
        tags: [{ label: 'SQUAD', tone: 'green' }, { label: 'OFFICIAL', tone: 'blue' }],
        accent: 'green',
      } satisfies WorldCupSignalItem,
      ...roster.players.map((player) => ({
        id: `pool-${roster.team}-${player.name}`,
        source: player.position || 'PLAYER',
        title: player.name,
        summary: `${player.club || 'federation source'} · ${player.status || 'probable'} · number ${player.number || '--'}.`,
        age: player.status || 'pool',
        tags: [{ label: player.status?.toUpperCase() || 'WATCH', tone: player.status === 'injured' ? 'red' : 'gold' }, { label: 'TEAM', tone: 'gray' }],
        accent: player.status === 'injured' ? 'red' : 'blue',
      } satisfies WorldCupSignalItem)),
    ])
    .slice(0, 12);
}

function buildXgSignals(payload: WorldCupDashboardPayload, match: WorldCupMatch | null): WorldCupSignalItem[] {
  return runtimeSignalItems(payload, 'xgModel', match).slice(0, 10);
}

function buildTacticalSignals(payload: WorldCupDashboardPayload, match: WorldCupMatch | null): WorldCupSignalItem[] {
  return runtimeSignalItems(payload, 'tacticalMatchup', match).slice(0, 10);
}

function buildLocalMediaSignals(payload: WorldCupDashboardPayload, match: WorldCupMatch | null): WorldCupSignalItem[] {
  return runtimeSignalItems(payload, 'localMedia', match).slice(0, 14);
}

function buildRefVenueSignals(payload: WorldCupDashboardPayload, match: WorldCupMatch | null): WorldCupSignalItem[] {
  return runtimeSignalItems(payload, 'refVenue', match).slice(0, 10);
}

function SourceAuditPanel({
  payload,
  markets,
  odds,
  news,
}: {
  payload: WorldCupDashboardPayload;
  markets: WorldCupPolymarketMarket[];
  odds: WorldCupOddsSnapshot[];
  news: WorldCupNewsItem[];
}) {
  const states = payload.intelligence?.providerStates || {};
  const rows: SourceRequiredRow[] = [
    { source: 'Calendar / match control', status: payload.matches.length ? payload.cacheMode : 'missing', detail: `${payload.matches.length} schedule rows; no hardcoded fixtures` },
    { source: 'News', status: news.length ? 'ok' : 'empty', detail: `${news.length} ESPN/latest-content rows; no generated news` },
    { source: 'Weather / venue risk', status: payload.weather.length ? (states.openMeteo || states.wttr || 'ok') : 'missing', detail: `${payload.weather.length} host-city weather rows` },
    { source: 'Polymarket markets', status: markets.length ? 'local-db' : 'not matched', detail: `${markets.length} linked local DB / Gamma market rows` },
    { source: 'Bookmaker odds', status: odds.length ? 'ok' : 'source required', detail: `${odds.length} licensed odds snapshots` },
    { source: 'Official facts', status: states.espnScoreboard || 'source required', detail: 'ESPN scoreboard if available; FIFA Match Centre connector still required' },
    { source: 'Injury / lineup / xG / referee', status: 'source required', detail: 'Panels show empty-state until trusted provider rows arrive' },
  ];
  return (
    <Panel title="SOURCE AUDIT" count={rows.length} className="wm-worldcup-panel wm-worldcup-source-audit-panel">
      <SourceRequired
        title="VERIFIED DATA MODE"
        detail="This workspace only renders rows backed by an upstream provider, cached snapshot, or local Polymarket DB link; generated odds, squads, news and market rows are blocked."
        rows={rows}
      />
    </Panel>
  );
}

export function WorldCupWorkspace({ now, marketGroups, latestContent, geoShockPayload }: WorldCupWorkspaceProps) {
  const { payload, loading, error } = useWorldCupDashboard(marketGroups);
  const [selectedMatchId, setSelectedMatchId] = useState<string | null>(null);
  const [selectedCityId, setSelectedCityId] = useState<string | null>(null);
  const [filter, setFilter] = useState<MatchFilter>('future');
  const [selectedGroup, setSelectedGroup] = useState('Group A');
  const [panelOrder, setPanelOrder] = useState<WorldCupPanelId[]>(readWorldCupPanelOrder);
  const [draggingPanelId, setDraggingPanelId] = useState<WorldCupPanelId | null>(null);

  const nextMatch = useMemo(() => payload ? getNextWorldCupMatch(payload.matches, now) : null, [now, payload]);

  useEffect(() => {
    if (!payload || selectedMatchId) return;
    const next = getNextWorldCupMatch(payload.matches, now) || payload.matches[0] || null;
    setSelectedMatchId(next?.id || null);
    setSelectedCityId(next?.cityId || payload.cities[0]?.id || null);
  }, [now, payload, selectedMatchId]);

  const selectedMatch = payload?.matches.find((match) => match.id === selectedMatchId) || nextMatch || payload?.matches[0] || null;
  const selectedOdds = payload?.odds.filter((item) => item.matchId === selectedMatch?.id) || [];
  const selectedMarkets = useMemo(() => matchPolymarketMarkets(selectedMatch, marketGroups), [marketGroups, selectedMatch]);
  const news = useMemo(() => {
    const runtimeNews = payload?.news || [];
    const contentNews = filterWorldCupNews(latestContent, selectedMatch);
    const seen = new Set<string>();
    const filteredNews = [...runtimeNews, ...contentNews].filter((item) => {
      const key = `${item.source}:${item.title}`.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, 24);
    return filteredNews.length ? filteredNews : latestContentNewsFallback(latestContent);
  }, [latestContent, payload?.news, selectedMatch]);

  useEffect(() => {
    if (selectedMatch?.group) setSelectedGroup(selectedMatch.group);
  }, [selectedMatch?.group]);

  useEffect(() => {
    window.localStorage.setItem(WORLD_CUP_PANEL_ORDER_STORAGE_KEY, JSON.stringify(panelOrder));
  }, [panelOrder]);

  if (loading && !payload) {
    return (
      <main className={WORLD_CUP_DASHBOARD_CLASS}>
        <PanelLoading label="Loading World Cup workspace" detail="Syncing schedule, host cities and market links" />
      </main>
    );
  }

  if (!payload) {
    return (
      <main className={WORLD_CUP_DASHBOARD_CLASS}>
        <div className="wm-banner error">{error || 'World Cup workspace unavailable.'}</div>
      </main>
    );
  }

  const selectedCity = matchCity(payload.cities, selectedCityId || selectedMatch?.cityId || nextMatch?.cityId || payload.cities[0]?.id || '');
  const selectedWeather = payload.weather.find((item) => item.cityId === selectedCity.id) || null;
  const nextCity = nextMatch ? matchCity(payload.cities, nextMatch.cityId) : null;
  const geoConflictEvents = useMemo(
    () => (geoShockPayload?.items || []).filter((item) => {
      const lat = Number(item.latitude);
      const lon = Number(item.longitude);
      return Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
    }),
    [geoShockPayload],
  );
  const linkedMarketCount = payload.matches.filter((match) => match.marketLinked).length + selectedMarkets.length;
  const weatherWatchCount = payload.weather.filter((item) => {
    const rain = item.current.precipitationProbability ?? 0;
    const wind = item.current.windKph ?? 0;
    return rain >= 35 || wind >= 22 || /storm|thunder|rain|humid|watch/i.test(item.current.condition);
  }).length;
  const selectedCityMatchCount = Math.max(
    WORLD_CUP_HOST_MATCH_COUNTS[selectedCity.id] || 0,
    payload.matches.filter((match) => match.cityId === selectedCity.id).length,
  );
  const plannedMatchTotal = payload.cities.reduce((sum, city) => sum + (WORLD_CUP_HOST_MATCH_COUNTS[city.id] || 0), 0);
  const displayOdds = selectedOdds;
  const matchSignals = buildMatchSignals(selectedMatch, selectedMarkets);
  const hostOpsSignals = buildHostOpsSignals(payload, selectedCity.id);
  const marketSignals = buildMarketSignals(selectedMarkets, selectedMatch);
  const squadSignals = buildSquadSignals(payload, selectedMatch);
  const oddsSignals = buildOddsSignals(displayOdds, selectedMatch);
  const riskSignals = buildRiskSignals(payload, selectedMatch);
  const broadcastSignals = buildBroadcastSignals(selectedMatch);
  const officialFactSignals = buildOfficialFactSignals(payload, selectedMatch, selectedCity);
  const injurySignals = buildInjurySignals(payload, selectedMatch);
  const lineupSignals = buildLineupSignals(payload, selectedMatch);
  const playerPoolSignals = buildPlayerPoolSignals(payload, selectedMatch);
  const xgSignals = buildXgSignals(payload, selectedMatch);
  const tacticalSignals = buildTacticalSignals(payload, selectedMatch);
  const localMediaSignals = buildLocalMediaSignals(payload, selectedMatch);
  const refVenueSignals = buildRefVenueSignals(payload, selectedMatch);
  const terminalMetrics = [
    { label: 'next_kickoff', value: formatCountdown(nextMatch, now), meta: nextMatch ? `${nextMatch.homeTeam} vs ${nextMatch.awayTeam}` : 'schedule complete' },
    { label: 'selected_city', value: selectedCity.city, meta: `${selectedCity.country} · ${selectedCityMatchCount} matches` },
    { label: 'match_count', value: String(Math.max(payload.matches.length, plannedMatchTotal)), meta: `${payload.cities.length} host cities` },
    { label: 'market_links', value: String(linkedMarketCount), meta: 'Dashboard feed' },
  ];
  const worldCupPanels: Record<WorldCupPanelId, ComponentChildren> = {
    calendar: (
      <CalendarPanel
        matches={payload.matches}
        selectedMatchId={selectedMatch?.id || null}
        filter={filter}
        now={now}
        onFilter={setFilter}
        onSelectMatch={(match) => {
          setSelectedMatchId(match.id);
          setSelectedCityId(match.cityId);
        }}
      />
    ),
    'match-control': (
      <MatchControlPanel
        match={selectedMatch}
        markets={selectedMarkets}
        odds={displayOdds}
        weather={selectedWeather}
        city={selectedCity}
        facts={officialFactSignals}
        broadcast={broadcastSignals}
      />
    ),
    news: <NewsPanel items={news} />,
    'win-probability': <WinProbabilityPanel markets={selectedMarkets} odds={displayOdds} match={selectedMatch} />,
    'venue-risk': <VenueRiskPanel payload={payload} match={selectedMatch} weather={selectedWeather} />,
    'host-venue': (
      <HostVenuePanel
        payload={payload}
        selectedCityId={selectedCity.id}
        onSelectCity={setSelectedCityId}
        hostOps={hostOpsSignals}
        risk={riskSignals}
        refVenue={refVenueSignals}
      />
    ),
    'market-board': <MarketBoardPanel markets={selectedMarkets} odds={displayOdds} />,
    'group-advance': <GroupAdvancePanel matches={payload.matches} group={selectedGroup || groupName(selectedMatch)} onGroupChange={setSelectedGroup} />,
    'team-power': <TeamPowerPanel payload={payload} match={selectedMatch} />,
    'injury-load': <InjuryLoadPanel payload={payload} match={selectedMatch} injuries={injurySignals} />,
    'match-tempo': <MatchTempoPanel xgSignals={xgSignals} tacticalSignals={tacticalSignals} />,
    'ref-cards': <RefCardsPanel refVenue={refVenueSignals} />,
    'travel-load': <TravelLoadPanel payload={payload} match={selectedMatch} />,
    'news-impact': <NewsImpactPanel news={news} />,
    'team-status': <TeamStatusPanel payload={payload} match={selectedMatch} injuries={injurySignals} players={playerPoolSignals} />,
    'lineup-board': <LineupBoardPanel lineups={lineupSignals} squadSignals={squadSignals} />,
    'match-model': <MatchModelPanel xgSignals={xgSignals} tacticalSignals={tacticalSignals} />,
    'group-table': <GroupTablePanel matches={payload.matches} group={selectedGroup || groupName(selectedMatch)} onGroupChange={setSelectedGroup} />,
    'media-wire': <MediaWirePanel news={news} matchSignals={matchSignals} localMedia={localMediaSignals} />,
    'odds-liquidity': <OddsLiquidityPanel odds={displayOdds} markets={selectedMarkets} oddsSignals={oddsSignals} marketSignals={marketSignals} />,
    'venue-ref': <VenueRefPanel refVenue={refVenueSignals} risk={riskSignals} payload={payload} match={selectedMatch} />,
    'source-audit': <SourceAuditPanel payload={payload} markets={selectedMarkets} odds={displayOdds} news={news} />,
  };
  const orderedPanels = [...panelOrder, ...WORLD_CUP_PANEL_ORDER.filter((id) => !panelOrder.includes(id))]
    .filter((id, index, array) => array.indexOf(id) === index);
  const movePanel = (draggedId: WorldCupPanelId, targetId: WorldCupPanelId, insertAfter: boolean) => {
    setPanelOrder((current) => reorderWorldCupPanels(current, draggedId, targetId, insertAfter));
    setDraggingPanelId(null);
  };

  return (
    <main className={WORLD_CUP_DASHBOARD_CLASS}>
      <section className="wm-worldcup-hero">
        <div className="wm-worldcup-hero-copy">
          <div className="wm-worldcup-hero-topline">
            <span>FIFA WORLD CUP 2026</span>
            <span>UPDATED {formatUpdatedAgo(payload.generatedAt, now)}</span>
            <span>{formatBjtClock(now)} BJT</span>
          </div>
          <h1>World Cup Host Atlas</h1>
          <p>Venue schedule, match markets, weather watch and host-city intelligence in one premium World Cup workspace.</p>
          <div className="wm-worldcup-next-context">
            <span>NEXT MATCH CONTEXT</span>
            <strong>{nextMatch ? `${nextMatch.homeTeam} / ${nextMatch.awayTeam}` : 'Tournament window complete'}</strong>
            <em>{nextMatch ? `${kickoffDay(nextMatch)} · ${kickoffTime(nextMatch)} BJT · ${nextCity?.city || nextMatch.city}` : 'No upcoming kickoff in schedule'}</em>
          </div>
        </div>
        <div className="wm-worldcup-hero-metrics">
          {terminalMetrics.map((metric) => (
            <div className="wm-worldcup-terminal-card" key={metric.label}>
              <span><b>$</b> {metric.label}</span>
              <strong>{metric.value}</strong>
              <em>{metric.meta}</em>
            </div>
          ))}
        </div>
      </section>

      <section className="wm-worldcup-map-section">
        <div className="wm-map-header">
          <div className="wm-map-heading">
            <span className="wm-map-kicker">United States · Canada · Mexico</span>
            <div className="wm-map-title">World Cup Host Atlas</div>
          </div>
          <div className="wm-map-status-strip">
            <span className="wm-map-kpi-chip"><b>{payload.cities.length}</b> Host Cities</span>
            <span className="wm-map-kpi-chip"><b>{Math.max(payload.matches.length, plannedMatchTotal)}</b> Matches</span>
            <span className="wm-map-kpi-chip"><b>{linkedMarketCount}</b> Market-linked</span>
            <span className="wm-map-kpi-chip"><b>{weatherWatchCount}</b> Weather watch</span>
            <span className="wm-status-chip">WORLD CUP · PRE-TOURNAMENT</span>
            <div className="wm-map-clock">{formatBjtClock(now)} BJT</div>
            <span className="wm-map-next-chip">
              {nextCity && nextMatch
                ? `NEXT · ${nextCity.city} · M#${nextMatch.fifaMatchNumber || '--'} · ${formatCountdown(nextMatch, now)}`
                : 'NEXT · --'}
            </span>
          </div>
        </div>
        <WorldCupMap
          cities={payload.cities}
          matches={payload.matches}
          weather={payload.weather}
          marketGroups={marketGroups}
          odds={payload.odds}
          conflicts={geoConflictEvents}
          nextMatch={nextMatch}
          selectedCityId={selectedCityId}
          selectedMatchId={selectedMatch?.id || null}
          onSelectCity={setSelectedCityId}
          onSelectMatch={setSelectedMatchId}
        />
      </section>

      <section className="wm-worldcup-panel-matrix">
        {orderedPanels.map((panelId) => (
          <WorldCupPanelSlot
            draggingId={draggingPanelId}
            key={panelId}
            panelId={panelId}
            onDragStateChange={setDraggingPanelId}
            onMovePanel={movePanel}
          >
            {worldCupPanels[panelId]}
          </WorldCupPanelSlot>
        ))}
      </section>
    </main>
  );
}
