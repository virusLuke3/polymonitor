import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { geoBounds } from 'd3-geo';
import { useI18n } from '@/services/i18n';
import { fetchMapForecast, searchMapPlaces, searchMapAirports, type MapForecast, type MapPlace } from '@/services/api';
import type { CountryGeometry, CountryGeometryIndex } from '../domain/countryGeometry';
import type { GeoEvent } from '../domain/types';
import type { MapCountryTarget } from '../renderer/MapRenderer';

export function MapExplore({ countries, events, onLocate, onCountry, onEvent, center }: {
  countries?: CountryGeometryIndex | null; events: GeoEvent[]; center: {lat: number; lon: number};
  onLocate: (point: [number, number]) => void; onCountry: (country: MapCountryTarget) => void; onEvent: (id: string) => void;
}) {
  const { locale } = useI18n(); const zh = locale === 'zh';
  const [open, setOpen] = useState(false), [query, setQuery] = useState('');
  const [places, setPlaces] = useState<MapPlace[]>([]), [searchError, setSearchError] = useState(''), [searching, setSearching] = useState(false);
  const [place, setPlace] = useState<MapPlace | null>(null), [forecast, setForecast] = useState<MapForecast | null>(null);
  const [weatherError, setWeatherError] = useState(''), [loading, setLoading] = useState(false), [attempt, setAttempt] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const normalized = query.trim().toLocaleLowerCase();
  const countryNames = useMemo(() => new Intl.DisplayNames([locale], {type: 'region'}), [locale]);
  const localCountries = useMemo(() => !normalized ? [] : (countries?.countries || []).filter(c =>
    [c.name, c.iso2, c.iso3, countryNames.of(c.iso2)].some(v => v?.toLocaleLowerCase().includes(normalized))), [countries, normalized, countryNames]);
  const localEvents = useMemo(() => !normalized ? [] : events.filter(e =>
    [e.title, e.locationLabel, e.properties.iata, e.properties.icao24, e.properties.callsign].some(v => String(v || '').toLocaleLowerCase().includes(normalized))), [events, normalized]);
  useEffect(() => {
    if (!open || normalized.length < 2) { setPlaces([]); setSearching(false); return; }
    const controller = new AbortController(); let active = true;
    setPlaces([]); setSearchError(''); setSearching(true);
    const timer = setTimeout(() => { void Promise.allSettled([searchMapPlaces(query.trim(), locale, controller.signal), searchMapAirports(query.trim(), controller.signal)]).then(results => {
      if (!active) return;
      setPlaces(results.flatMap(result => result.status === 'fulfilled' ? result.value.places : []));
      const failures = results.map((result, i) => result.status === 'rejected' ? `${i === 0 ? 'GeoNames' : 'Airports'}: ${String(result.reason)}` : '').filter(Boolean);
      setSearchError(failures.join(' · '));
    }).catch(error => { if (active) setSearchError(String(error)); }).finally(() => { if (active) setSearching(false); }); }, 350);
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [normalized, locale, open]);
  useEffect(() => {
    if (!open || !place) return;
    const controller = new AbortController(); let active = true;
    setForecast(null); setWeatherError(''); setLoading(true);
    void fetchMapForecast(place.lat, place.lon, controller.signal).then(result => { if (active) setForecast(result); })
      .catch(error => { if (active) setWeatherError(String(error)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [open, place, attempt]);
  useEffect(() => { if (open) inputRef.current?.focus({preventScroll: true}); }, [open]);
  const selectCountry = (country: CountryGeometry) => {
    onCountry({iso2: country.iso2, name: countryNames.of(country.iso2) || country.name,
      bounds: geoBounds({type: 'Feature', properties: {}, geometry: country.geometry})}); setOpen(false);
  };
  const choosePlace = (next: MapPlace) => { setPlace(next); onLocate([next.lon, next.lat]); };
  const hourly = forecast?.hourly.time?.map((time, i) => ({time, temp: forecast.hourly.temperature_2m?.[i]}))
    .filter(row => row.time >= (forecast?.current.time || '')).slice(0, 24) || [];
  return <details className="wm-map-explore" open={open} onToggle={e => setOpen(e.currentTarget.open)} onKeyDown={e => { if (e.key === 'Escape') {setOpen(false); e.stopPropagation();} }}>
    <summary>{zh ? '搜索 · 地区温度' : 'Search · Temperature'}</summary>
    {open ? <section aria-label={zh ? '地理搜索与天气' : 'Geographic search and weather'}>
      <label>{zh ? '国家、地点、机场或已加载飞机' : 'Country, place, airport or loaded aircraft'}
        <input ref={inputRef} value={query} onInput={e => setQuery(e.currentTarget.value)} type="search" placeholder={zh ? '名称、机场代码、航班呼号…' : 'Name, airport code, callsign…'} />
      </label>
      <button type="button" onClick={() => choosePlace({id: 'map-center', name: zh ? '地图中心' : 'Map center', lat: center.lat, lon: center.lon, country: '', region: ''})}>{zh ? '查询地图中心温度' : 'Temperature at map center'}</button>
      <div className="wm-map-search-results">
        {localCountries.map(c => <button type="button" key={c.iso2} onClick={() => selectCountry(c)}>{countryNames.of(c.iso2) || c.name} · {zh ? '国家简报' : 'Country brief'}</button>)}
        {localEvents.map(e => <button type="button" key={e.id} onClick={() => { if (e.geometry?.type === 'Point') onLocate(e.geometry.coordinates); onEvent(e.id); setOpen(false); }}>{e.title} · {e.locationLabel}</button>)}
        {places.map(p => <button type="button" key={p.id} onClick={() => choosePlace(p)}>{p.name} · {p.region} · {p.country}</button>)}
      </div>
      {searching ? <p role="status">{zh ? '查询地点…' : 'Searching places…'}</p> : null}
      {searchError ? <p role="alert">{zh ? '地点来源不可用：' : 'Place source unavailable: '}{searchError}</p> : null}
      {normalized.length >= 2 && !searching && !searchError && !places.length && !localCountries.length && !localEvents.length ? <p>{zh ? '未找到匹配记录。飞机搜索仅覆盖已加载观测。' : 'No matches. Aircraft search covers loaded observations only.'}</p> : null}
      {place ? <article className="wm-map-temperature">
        <h3>{place.name} · {place.lat.toFixed(3)}, {place.lon.toFixed(3)}</h3>
        {loading ? <p role="status">{zh ? '加载温度…' : 'Loading temperature…'}</p> : null}
        {weatherError ? <p role="alert">{zh ? '天气来源不可用：' : 'Weather source unavailable: '}{weatherError}</p> : null}
        {forecast ? <>
          <strong>{forecast.current.temperature_2m ?? '—'} °C</strong>
          <p>{forecast.current.time} UTC · {zh ? '模式估计，非灾害预警' : 'Model estimate, not a hazard warning'}</p>
          <p>{zh ? '风速' : 'Wind'} {forecast.current.wind_speed_10m ?? '—'} km/h · {zh ? '湿度' : 'Humidity'} {forecast.current.relative_humidity_2m ?? '—'}%</p>
          <details><summary>{zh ? '未来 24 小时' : 'Next 24 hours'}</summary><table><tbody>{hourly.map(row => <tr key={row.time}><td>{row.time.slice(5).replace('T', ' ')} UTC</td><td>{row.temp ?? '—'} °C</td></tr>)}</tbody></table></details>
          <table><caption>{zh ? '七天最低 / 最高温度' : 'Seven-day low / high'}</caption><tbody>{forecast.daily.time?.map((day, i) => <tr key={day}><td>{day}</td><td>{forecast.daily.temperature_2m_min?.[i] ?? '—'} / {forecast.daily.temperature_2m_max?.[i] ?? '—'} °C</td></tr>)}</tbody></table>
          <a href={forecast.sourceUrl} target="_blank" rel="noreferrer">{forecast.source} · CC BY 4.0</a>
        </> : null}
        <button type="button" disabled={loading} onClick={() => setAttempt(a => a + 1)}>{zh ? '重新查询' : 'Refresh forecast'}</button>
      </article> : null}
      <small>Geocoding: Open-Meteo / GeoNames</small>
    </section> : null}
  </details>;
}
