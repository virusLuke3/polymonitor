import {isBasePayload,record,type BasePayload} from '../external/resource';
export type WeatherPayload=BasePayload&{weeks?:{date:string;region:string;cumulative:number[];shares:number[];validEnd:string}[];cities?:{cityId:string;city:string;country:string;timezone:string;source:string|null;sourceUrl:string|null;forecastFetchedAt:string;hourly:{time:string;precipitation:number|null;precipitationProbability:number|null}[];daily:{date:string;precipitationSum:number|null;precipitationProbabilityMax:number|null}[]}[];events?:{id:string;title:string;summary:string;severity:string;updatedAt:string;expiresAt:string|null;locationLabel:string;metrics:{maximumWind?:{value:number;unit:string};pressureHpa?:number|null;categoryLabel?:string;advisoryNumber?:string;instruction?:string};sources:{provider:string;url:string}[]}[];total?:number};
export function validateWeather(v:unknown):v is WeatherPayload {
 if(!record(v)||!isBasePayload(v))return false; const r=v as Record<string,unknown>;
 if(r.weeks!==undefined)return Array.isArray(r.weeks)&&r.weeks.every(x=>record(x)&&typeof x.date==='string'&&typeof x.region==='string'&&Array.isArray(x.shares)&&x.shares.length===6&&x.shares.every(y=>typeof y==='number'&&Number.isFinite(y)&&y>=0&&y<=100)&&Array.isArray(x.cumulative)&&x.cumulative.length===5&&x.cumulative.every(y=>typeof y==='number'&&Number.isFinite(y)));
 if(r.cities!==undefined)return Array.isArray(r.cities)&&r.cities.every(x=>record(x)&&typeof x.cityId==='string'&&typeof x.city==='string'&&Array.isArray(x.hourly)&&Array.isArray(x.daily));
 if(r.events!==undefined)return Array.isArray(r.events)&&r.events.every(x=>record(x)&&typeof x.id==='string'&&typeof x.title==='string'&&record(x.metrics)&&Array.isArray(x.sources));
 return false;
}
