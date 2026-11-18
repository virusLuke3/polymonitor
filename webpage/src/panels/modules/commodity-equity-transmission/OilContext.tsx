import type { OilMarketContext, OilObservationSeries, OilSettlementMarket } from '@/types';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import './oil-context.css';

const number = (value?: number | null, digits = 2) => value == null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: digits });
const signed = (value: number, digits = 2) => `${value > 0 ? '+' : ''}${number(value, digits)}`;

function changes(series: OilObservationSeries, percent = false) {
  const [prior, latest] = series.points?.slice(-2) ?? [];
  const difference = latest && prior && (!percent || prior.value !== 0)
    ? percent ? (latest.value / prior.value - 1) * 100 : latest.value - prior.value : null;
  return { latest, difference };
}

function Observation({ label, series, percent, localizedUnit, zh }: {
  label: string; series: OilObservationSeries; percent?: boolean; localizedUnit: string; zh: boolean;
}) {
  const { latest, difference } = changes(series, percent);
  return <div className="wm-oil-observation">
    <span>{label}</span>
    <strong>{number(latest?.value, percent ? 2 : 3)} {latest && localizedUnit}</strong>
    <small>{[series.source ?? 'EIA', latest?.period, series.status === 'stale' ? (zh ? '保留值' : 'Retained') : null].filter(Boolean).join(' · ')}</small>
    {difference != null && <small>{percent ? (zh ? '较前一观测日' : 'vs previous observation') : (zh ? '较前周' : 'vs previous week')}
      {' '}{signed(difference, percent ? 2 : 3)} {percent ? '%' : localizedUnit}</small>}
    {series.releaseOn && !percent && <small>{zh ? '发布日' : 'Released'} · {series.releaseOn}</small>}
  </div>;
}

function Markets({ data, zh }: { data: OilMarketContext; zh: boolean }) {
  const { formatDateTime } = useSpecialistCopy('commodity-equity-transmission');
  const groups = new Map<string, OilSettlementMarket[]>();
  for (const market of data.markets.items) {
    const key = `${market.eventTitle}\n${market.source}`;
    const group = groups.get(key);
    if (group) group.push(market);
    else groups.set(key, [market]);
  }
  const price = (value?: number | null) => value == null ? '—' : `${number(value * 100, 1)}¢`;
  return <section className="wm-oil-section">
    <h4>{zh ? 'Polymarket · 按结算依据匹配' : 'Polymarket · settlement matches'}</h4>
    {data.markets.status !== 'ok' && <p>{data.markets.status === 'stale'
      ? (zh ? '盘口列表为保留记录' : 'Retained market list')
      : (zh ? '盘口来源暂不可用' : 'Market source unavailable')}</p>}
    {data.markets.status === 'ok' && !data.markets.items.some(row => row.benchmark === 'brent') && <p>{zh ? '布伦特 · 暂无已核验的开放盘口' : 'Brent · No verified open markets'}</p>}
    {data.markets.status === 'ok' && !data.markets.items.some(row => row.benchmark === 'eia') && <p>{zh ? 'EIA 数据 · 暂无同口径开放盘口' : 'EIA · No verified open markets'}</p>}
    {[...groups.values()].map(rows => {
      const first = rows[0];
      if (!first) return null;
      return <details className="wm-oil-market" key={first.id}>
        <summary>{first.eventTitle} <span>· {rows.length}</span></summary>
        <small><a href={first.sourceUrl} target="_blank" rel="noreferrer">{first.source}</a> · {first.basis}</small>
        {rows.map(row => <div className="wm-oil-market-row" key={row.id}>
          <a href={row.url} title={row.title} target="_blank" rel="noreferrer">{row.label}</a>
          <span>{row.outcome === 'up' ? 'Up' : 'Yes'} {price(row.bestBid)} / {price(row.bestAsk)}</span>
          <small>{row.benchmark === 'brent' && row.windowStartsAt
            ? `${formatDateTime(row.windowStartsAt)} → ${formatDateTime(row.endsAt)}`
            : `${zh ? '截止' : 'Ends'} · ${formatDateTime(row.endsAt)}`}</small>
        </div>)}
      </details>;
    })}
    {data.markets.status === 'ok' && groups.size === 0 && <p>{zh ? '当前没有通过规则核验的在售盘口。' : 'No open markets with verified rules.'}</p>}
    {data.markets.checkedAt && <small>{zh ? '盘口检查' : 'Markets checked'} · {formatDateTime(data.markets.checkedAt)} · {zh ? '买价／卖价' : 'Bid / ask'}</small>}
  </section>;
}

export function OilContext({ data }: { data?: OilMarketContext }) {
  const { locale, formatDateTime } = useSpecialistCopy('commodity-equity-transmission');
  const zh = locale === 'zh';
  if (!data) return <p className="wm-oil-section">{zh ? '正在读取原油数据…' : 'Loading oil data…'}</p>;
  const futures = new Map(data.futures.map(row => [row.id, row]));
  const days = data.hormuz.points?.slice(-7) ?? [];
  const latest = days[days.length - 1];
  const first = days[0];
  const span = days.length === 7 && latest && first && Date.parse(latest.period) - Date.parse(first.period) === 6 * 86400000;
  return <div className="wm-oil-context">
    <section className="wm-oil-section">
      <h4>{zh ? '布伦特与 WTI · 美元/桶' : 'Brent and WTI · USD/bbl'}</h4>
      <div className="wm-oil-grid">
        {(['brent', 'oil'] as const).map(id => {
          const row = futures.get(id);
          return <div className="wm-oil-observation" key={id}>
            <span>{id === 'brent' ? (zh ? '布伦特期货' : 'Brent futures') : (zh ? 'WTI 期货' : 'WTI futures')}</span>
            <strong>{number(row?.price)} {row?.changeBasis === 'previous-close' && row.changePercent != null && <em>{signed(row.changePercent)}%</em>}</strong>
            <small>Yahoo Finance · {row?.symbol || (id === 'brent' ? 'BZ=F' : 'CL=F')}</small>
            {row?.quoteAt && <small>{formatDateTime(row.quoteAt)}{row.acquisitionState !== 'ok' ? (zh ? ' · 保留值' : ' · Retained') : ''}</small>}
          </div>;
        })}
        <Observation series={data.brentSpot} label={zh ? '布伦特现货' : 'Brent spot'} localizedUnit="" percent zh={zh} />
        <Observation series={data.wtiSpot} label={zh ? 'WTI 现货' : 'WTI spot'} localizedUnit="" percent zh={zh} />
      </div>
    </section>
    <section className="wm-oil-section">
      <h4>{zh ? '美国油品周报与海峡通行' : 'U.S. weekly petroleum and Hormuz traffic'}</h4>
      <div className="wm-oil-grid">
        <Observation series={data.inventory} label={zh ? '商业原油库存（不含 SPR）' : 'Commercial crude stocks (excl. SPR)'} localizedUnit={zh ? '百万桶' : 'M bbl'} zh={zh} />
        <Observation series={data.spr} label={zh ? '战略石油储备（SPR）' : 'Strategic Petroleum Reserve'} localizedUnit={zh ? '百万桶' : 'M bbl'} zh={zh} />
        <Observation series={data.production} label={zh ? '美国原油日产量' : 'U.S. crude production'} localizedUnit={zh ? '百万桶/日' : 'M bbl/d'} zh={zh} />
      </div>
      <details className="wm-oil-market" open>
        <summary>{zh ? '霍尔木兹海峡' : 'Strait of Hormuz'} · {number(latest?.value, 0)} {zh ? '艘次' : 'transits'}</summary>
        <small>IMF PortWatch{latest ? ` · ${latest.period}` : ''}{data.hormuz.status === 'stale' ? (zh ? ' · 保留值' : ' · Retained') : ''}</small>
        {latest && <small>{zh ? '其中油轮' : 'Tankers'} {number(latest.tankers, 0)} {span && ` · ${zh ? '7 日均值' : '7d average'} ${number(days.reduce((total, day) => total + day.value, 0) / 7, 1)}`}</small>}
        <table><thead><tr><th>{zh ? '观测日' : 'Date'}</th><th>{zh ? '总艘次' : 'Total'}</th><th>{zh ? '油轮' : 'Tankers'}</th></tr></thead>
          <tbody>{days.slice().reverse().map(day => <tr key={day.period}><td>{day.period}</td><td>{day.value}</td><td>{number(day.tankers, 0)}</td></tr>)}</tbody></table>
      </details>
    </section>
    <Markets data={data} zh={zh} />
  </div>;
}
