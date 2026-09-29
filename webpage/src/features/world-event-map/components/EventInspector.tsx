import { useI18n } from '@/services/i18n';
import { mapText } from '@/locales/map';
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import type { GeoEvent, GeoEventSource } from '../domain/types';
import { isHazardGeoEvent } from '../config/layerRegistry';
import {
  eventTimeFields,
  eventContextFields,
  formatTimestamp,
  geometryLabel,
  hazardLabel,
  hazardMetricFields,
  type InspectorField,
} from './eventInspectorModel';
import { useRelatedWeatherMarkets } from '../data/useRelatedWeatherMarkets';
import { mapSymbolForEvent } from '../config/mapSymbols';
import { MapSymbolIcon } from './MapSymbolIcon';
import { useNaturalHazardDetail } from '../data/useNaturalHazardDetail';

export type EventInspectorProps = {
  event: GeoEvent;
  onClose: () => void;
  onOpenMarket?: (marketId: number) => void;
  returnFocusTarget?: HTMLElement | null;
};

function FieldList({ fields }: { fields: InspectorField[] }) {
  const { locale } = useI18n();
  const mt = (text: string) => mapText(locale, text);
  if (!fields.length) return null;
  return (
    <dl className="wm-event-inspector-fields">
      {fields.map((item) => (
        <div key={mt(item.label)}>
          <dt>{mt(item.label)}</dt>
          <dd>{mt(item.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function SourceCard({ source }: { source: GeoEventSource }) {
  const { locale } = useI18n();
  const mt = (text: string) => mapText(locale, text);
  return (
    <article className="wm-event-inspector-source">
      <div>
        <strong>{source.provider}</strong>
        <span className={`tone-${source.status || 'unknown'}`}>
          {mt(source.status || 'unknown')} · {mt(source.freshness || 'unknown')}
        </span>
      </div>
      {source.nativeId ? <code>{source.nativeId}</code> : null}
      {source.observedAt ? <span>{mt("Observed")} {formatTimestamp(source.observedAt)}</span> : null}
      {source.ingestedAt ? <span>{mt("Ingested")} {formatTimestamp(source.ingestedAt)}</span> : null}
      {source.url && /^https?:\/\//i.test(source.url) ? (
        <a href={source.url} target="_blank" rel="noreferrer">
          {mt("OPEN NATIVE SOURCE ↗")}
        </a>
      ) : null}
    </article>
  );
}

export function EventInspector({
  event: mapEvent,
  onClose,
  onOpenMarket,
  returnFocusTarget,
}: EventInspectorProps) {
  const { locale } = useI18n();
  const mt = (text: string) => mapText(locale, text);
  const titleRef = useRef<HTMLHeadingElement | null>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const mapHazard = isHazardGeoEvent(mapEvent) ? mapEvent : null;
  const detail = useNaturalHazardDetail(mapHazard);
  const event = detail.event || mapEvent;
  const hazard = isHazardGeoEvent(event) ? event : null;
  const relatedMarkets = useRelatedWeatherMarkets(hazard?.id || null);

  useLayoutEffect(() => {
    const active = document.activeElement;
    restoreFocusRef.current = active instanceof HTMLElement && active !== document.body
      ? active
      : returnFocusTarget || null;
    // Keep a useful map strip above the fixed mobile report. Do this before
    // the renderer measures its safe area; focusing the title must not undo it.
    if (window.matchMedia('(max-width: 720px)').matches) {
      titleRef.current?.closest('.wm-weather-deck-map')?.scrollIntoView({ block: 'start', behavior: 'instant' });
    }
    titleRef.current?.focus({ preventScroll: true });
    return () => {
      const target = restoreFocusRef.current;
      if (target?.isConnected) target.focus({ preventScroll: true });
    };
  }, [event.id, returnFocusTarget]);

  useEffect(() => {
    const handleKeyDown = (keyboardEvent: KeyboardEvent) => {
      if (keyboardEvent.key !== 'Escape') return;
      keyboardEvent.preventDefault();
      onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const commonFields: InspectorField[] = [
    { label: 'Report ID', value: event.id },
    { label: 'Severity', value: event.severity.toUpperCase() },
    ...(hazard ? [{ label: 'Lifecycle', value: hazard.lifecycle.toUpperCase() }] : []),
    { label: 'Location', value: event.locationLabel || 'Location label unavailable' },
    { label: 'Precision', value: event.locationPrecision.toUpperCase() },
    { label: 'Geometry', value: geometryLabel(event) },
    ...(event.confidence == null
      ? []
      : [{ label: 'Confidence', value: `${Math.round(event.confidence * 100)}%` }]),
  ];

  return (
    <aside
      className={`wm-event-inspector level-${event.severity}`}
      aria-labelledby="wm-event-inspector-title"
      data-event-id={event.id}
    >
      <button
        type="button"
        className="wm-event-inspector-close"
        aria-label={mt("Close event details")}
        onClick={onClose}
      >
        ×
      </button>
      <header className="wm-event-inspector-header">
        <div className="wm-event-inspector-kickers">
          <span>{mt(hazard ? hazardLabel(hazard) : event.category)}</span>
          <span>{mt(event.severity)}</span>
          {hazard ? <span>{mt(hazard.lifecycle)}</span> : null}
        </div>
        <div className="wm-event-inspector-titleline">
          <MapSymbolIcon
            symbol={mapSymbolForEvent(event)}
            severity={event.severity}
            hazard={event.category === "natural-hazard"}
            size={36}
            label={`${mt(event.severity)} ${mt(hazard ? hazardLabel(hazard) : event.category)}`}
          />
          <h2 id="wm-event-inspector-title" ref={titleRef} tabIndex={-1}>{event.title}</h2>
        </div>
        <p>{event.locationLabel} · {mt(event.severity)}</p>
        <p>{event.sources.map(source => `${source.provider} · ${mt(source.freshness || 'unknown')}`).join(' / ')}</p>
        {hazard && !hazard.coverage.isComplete ? <p className="wm-event-inspector-coverage">{mt('Coverage gap')} · {hazard.coverage.label}</p> : null}
      </header>

      {hazard ? (
        <section className="wm-event-inspector-section" aria-labelledby="wm-hazard-metrics-heading">
          <h3 id="wm-hazard-metrics-heading">{mt('Key metrics')}</h3>
          <FieldList fields={hazardMetricFields(hazard).slice(0, 4)} />
          {hazardMetricFields(hazard).length > 4 ? <details><summary>{mt('More metrics')}</summary><FieldList fields={hazardMetricFields(hazard).slice(4)} /></details> : null}
          {hazard.metrics.kind === 'weather-alert' && hazard.metrics.instruction ? (
            <div className="wm-event-inspector-callout">
              <strong>{mt("Official instruction")}</strong>
              <p>{hazard.metrics.instruction}</p>
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="wm-event-inspector-section" aria-labelledby="wm-event-evidence-heading">
        <h3 id="wm-event-evidence-heading">{mt(hazard ? 'Disaster report' : 'Event evidence')}</h3>
        {event.summary ? <p>{event.summary}</p> : null}
        {detail.loading ? <p role="status">{mt("Loading the complete source report\u2026")}</p> : null}
        {detail.error ? (
          <p className="wm-event-inspector-market-error" role="status">
            Full report refresh failed; showing the compact map record: {detail.error}
          </p>
        ) : null}
        <FieldList fields={eventTimeFields(event)} />
        <FieldList fields={eventContextFields(event)} />
      </section>

      {event.category === 'infrastructure' && event.properties.riskReason ? (
        <section className="wm-event-inspector-section" aria-labelledby="wm-aviation-evidence-heading">
          <h3 id="wm-aviation-evidence-heading">{mt("Aviation exposure note")}</h3>
          <div className="wm-event-inspector-callout">
            <strong>{mt("Why this corridor is highlighted")}</strong>
            <p>{String(event.properties.riskReason)}</p>
          </div>
        </section>
      ) : null}

      <section className="wm-event-inspector-section" aria-labelledby="wm-event-sources-heading">
        <h3 id="wm-event-sources-heading">{mt("Sources & freshness")}</h3>
        <div className="wm-event-inspector-sources">
          {event.sources.map((source, index) => (
            <SourceCard key={`${source.provider}:${source.nativeId || index}`} source={source} />
          ))}
        </div>
      </section>

      {hazard ? (
        <section className="wm-event-inspector-section" aria-labelledby="wm-event-coverage-heading">
          <h3 id="wm-event-coverage-heading">{mt("Coverage")}</h3>
          <p className="wm-event-inspector-coverage">
            <strong>{mt(hazard.coverage.isComplete ? 'complete' : 'partial')} · {mt(hazard.coverage.scope)}</strong>
            <span>{hazard.coverage.label}</span>
          </p>
          {hazard.coverage.gaps.length ? (
            <ul>
              {hazard.coverage.gaps.map((gap) => <li key={gap}>{gap}</li>)}
            </ul>
          ) : null}
        </section>
      ) : null}

      {event.limitations.length ? (
        <section className="wm-event-inspector-section" aria-labelledby="wm-event-limitations-heading">
          <h3 id="wm-event-limitations-heading">{mt("Limitations")}</h3>
          <ul>
            {event.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
          </ul>
        </section>
      ) : null}

      {hazard ? (
        <section className="wm-event-inspector-section wm-event-inspector-markets" aria-labelledby="wm-related-markets-heading">
          <h3 id="wm-related-markets-heading">{mt("Related Weather Markets")}</h3>
          {relatedMarkets.loading ? <p role="status">{mt("Evaluating type, space, time and settlement metric\u2026")}</p> : null}
          {relatedMarkets.error ? (
            <div className="wm-event-inspector-market-error" role="alert">
              <p>Related markets unavailable: {relatedMarkets.error}</p>
              <button type="button" onClick={relatedMarkets.retry}>{mt("RETRY MARKET LINK")}</button>
            </div>
          ) : null}
          {!relatedMarkets.loading && !relatedMarkets.error && relatedMarkets.response?.markets.length === 0 ? (
            <p>
              No evidence-qualified related weather markets were found. Markets appear here only after
              type, location, time window and settlement metric all pass the linker threshold.
            </p>
          ) : null}
          <div className="wm-event-inspector-market-list">
            {relatedMarkets.response?.markets.map((market) => (
              <article key={market.eventSlug || market.marketId || market.title}>
                <div className="wm-event-inspector-market-head">
                  <span className={`relationship-${market.relationship}`}>{market.relationship}</span>
                  <span>{Math.round(market.matchScore * 100)}% evidence</span>
                </div>
                <strong>{market.title}</strong>
                <p>
                  {[market.target.city, market.target.country, market.target.date].filter(Boolean).join(' · ')}
                </p>
                {market.quote.leadingOutcome ? (
                  <div className="wm-event-inspector-market-quote">
                    <span>{market.quote.leadingOutcome}</span>
                    <strong>
                      {market.quote.probability == null
                        ? '--'
                        : `${(market.quote.probability * 100).toFixed(1)}%`}
                    </strong>
                    <em>
                      {market.quote.spread == null ? 'NO LIVE SPREAD' : `SPREAD ${(market.quote.spread * 100).toFixed(1)}¢`}
                    </em>
                  </div>
                ) : null}
                <details>
                  <summary>{mt("Why this is linked")}</summary>
                  <ul>
                    {Object.entries(market.matchReasons).map(([dimension, evidence]) => (
                      <li key={dimension}>
                        <strong>{dimension}</strong> — {evidence.reason}
                      </li>
                    ))}
                  </ul>
                </details>
                <div className="wm-event-inspector-market-actions">
                  {market.marketId != null && onOpenMarket ? (
                    <button type="button" onClick={() => onOpenMarket(market.marketId as number)}>
                      OPEN MARKET WORKSPACE
                    </button>
                  ) : null}
                  {market.url && /^https?:\/\//i.test(market.url) ? (
                    <a href={market.url} target="_blank" rel="noreferrer">POLYMARKET ↗</a>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
          {relatedMarkets.response ? (
            <p className="wm-event-inspector-market-audit">
              LINKER {relatedMarkets.response.linkerVersion} · {relatedMarkets.response.counts.matched}/
              {relatedMarkets.response.counts.candidates} CANDIDATES PASSED
            </p>
          ) : null}
        </section>
      ) : null}
      <details className="wm-event-inspector-section"><summary>{mt("Technical details")}</summary>
      <FieldList fields={commonFields} />
      {hazard ? (
        <section aria-labelledby="wm-severity-evidence-heading">
          <h3 id="wm-severity-evidence-heading">{mt("Severity normalization")}</h3>
          <FieldList fields={[
            { label: 'Provider', value: hazard.severityEvidence.provider },
            {
              label: 'Raw level',
              value: hazard.severityEvidence.rawLevel || 'Provider did not publish a level',
            },
            { label: 'Mapping version', value: hazard.severityEvidence.mappingVersion },
          ]} />
          <div className="wm-event-inspector-callout">
            <strong>{mt("Why this level")}</strong>
            <p>{hazard.severityEvidence.reason}</p>
          </div>
        </section>
      ) : null}

      </details>
    </aside>
  );
}
