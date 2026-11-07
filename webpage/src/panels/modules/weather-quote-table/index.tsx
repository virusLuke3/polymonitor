import { WeatherQuoteStatus } from '@/panels/shared/weather/WeatherDataStatus';
import { Panel } from '@/components/Panel';
import type { RuntimeGlobalWeatherMapPayload, RuntimeWeatherQuoteBin } from '@/types';
import type { PanelRenderMap } from '../../types';
import { panelFromRenderer } from '@/panels/definePanel';
import { bestBookQuoteBin, bookMidPrice, num, priceLabel, quoteBinLabel, selectedWeatherCity } from '@/panels/shared/weather/model';
import { useLiveWeatherQuoteBins } from '@/panels/shared/weather/useLiveWeatherQuoteBins';
import { useSpecialistCopy } from '@/services/specialist-i18n';

function sourceLabel(value?: string | null) {
  if (value === 'clob-book') return 'CLOB';
  if (value === 'clob-snapshot') return 'SNAPSHOT';
  if (value === 'previous-book') return 'PREVIOUS';
  if (value === 'db-latest') return 'LAST';
  if (value === 'gamma-outcome') return 'GAMMA';
  return '--';
}

function quoteState(bin: RuntimeWeatherQuoteBin) {
  if (bin.bookStatus === 'retained') return 'RETAINED';
  if (bin.bookStatus === 'snapshot') return 'SNAPSHOT';
  if (bookMidPrice(bin) !== null) return 'CLOB MID';
  if (num(bin.bestBidYes) !== null || num(bin.bestAskYes) !== null) return 'CLOB 1-SIDED';
  if (num(bin.midPriceYes) !== null) return sourceLabel(bin.priceSource) === '--' ? 'QUOTED' : sourceLabel(bin.priceSource);
  return bin.bookStatus && bin.bookStatus !== 'not-queried' ? bin.bookStatus.toUpperCase() : 'MISSING';
}

function QuoteRow({ bin, active }: { bin: RuntimeWeatherQuoteBin; active: boolean }) {
  const { shared, formatRelativeTime } = useSpecialistCopy('weather-quote-table');
  const state = quoteState(bin);
  const stateLabel = state === 'QUOTED' ? shared('quoted', 'QUOTED') : state === 'MISSING' ? shared('missing', 'MISSING') : state;
  return (
    <tr className={`${active ? 'active' : ''} ${bin.bookStatus === 'retained' ? 'is-retained' : ''}`}>
      <td title={bin.label || undefined}>{quoteBinLabel(bin)}{bin.quoteUpdatedAt ? <small className="wm-weather-quote-time" title={bin.quoteUpdatedAt}>{formatRelativeTime(bin.quoteUpdatedAt)}</small> : null}</td>
      <td>{priceLabel(bin.bestBidYes)}</td>
      <td>{priceLabel(bin.bestAskYes)}</td>
      <td>{priceLabel(bin.midPriceYes)}</td>
      <td><span className={`wm-weather-quote-state ${state.toLowerCase().replace(/\s+/g, '-')}`}>{stateLabel}</span></td>
    </tr>
  );
}

function WeatherQuoteTablePanel({
  payload,
  selectedCityId,
}: {
  payload?: RuntimeGlobalWeatherMapPayload | null;
  selectedCityId?: string | null;
}) {
  const { copy, shared } = useSpecialistCopy('weather-quote-table');
  const city = selectedWeatherCity(payload, selectedCityId);
  const feed = useLiveWeatherQuoteBins(city);
  const { bins } = feed;
  const liveCity = city ? { ...city, bins } : null;
  const topBookBin = bestBookQuoteBin(liveCity);
  const topBin = topBookBin;
  const topBookPrice = bookMidPrice(topBookBin);
  const topLabel = topBin ? quoteBinLabel(topBin) : null;
  return (
    <Panel
      title={copy('title', 'WEATHER QUOTE TABLE')}
      className="wm-market-panel wm-weather-quote-table-only-panel"
      dataPanelId="weather-quote-table"
    >
      {city ? (
        <section className="wm-weather-quote-table-panel">
          <WeatherQuoteStatus feed={feed} city={city} />
          <div className="wm-weather-quote-table-head">
            <div>
              <span>{copy('tableTitle', '{city} Quote Table', { city: city.city || '--' })}</span>
              {topLabel ? <strong>{topLabel}</strong> : null}
            </div>
            {topBookPrice !== null ? <b>{priceLabel(topBookPrice)}</b> : null}
          </div>
          {!bins.length ? <div className="wm-weather-detail-empty-line">{shared('noMarketBins', 'No published market intervals for this city.')}</div> : null}
          <div className="wm-weather-quote-table-wrap">
            <table className="wm-weather-quote-table">
              <thead>
                <tr>
                  <th>{shared('bin', 'Bin')}</th>
                  <th>{shared('bid', 'Bid')}</th>
                  <th>{shared('ask', 'Ask')}</th>
                  <th>{shared('lastMid', 'Last/Mid')}</th>
                  <th>{shared('book', 'Book')}</th>
                </tr>
              </thead>
              <tbody>
                {bins.map((bin) => (
                  <QuoteRow key={String(bin.marketSlug || bin.label)} bin={bin} active={String(bin.label || '') === String(topBin?.label || '')} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <div className="wm-weather-detail-empty">{copy('empty', 'Select a city to inspect quote bins.')}</div>
      )}
    </Panel>
  );
}

const renderers: PanelRenderMap<'selectedWeatherCityId'> = {
  'weather-quote-table': {
    render: (ctx) => (
      <WeatherQuoteTablePanel
        payload={ctx.runtimeData['global-temperature-monitor'] as RuntimeGlobalWeatherMapPayload | undefined}
        selectedCityId={ctx.selectedWeatherCityId}
      />
    ),
  },
};

export const panel = panelFromRenderer(renderers, {
  contextKeys: ['selectedWeatherCityId'],
  id: 'weather-quote-table',
  title: 'Weather Quote Table',
  eyebrow: 'weather',
  description: 'Selected city temperature market quote bins in a compact table.',
  defaultEnabled: true,
  dataSourceId: 'global-temperature-monitor',
});
