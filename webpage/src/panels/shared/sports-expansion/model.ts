import { isBasePayload, record, type BasePayload } from '../external/resource';

export type Team = { id: string; name: string; short: string; side: string; score: number | null; periods: (number | null)[] };
export type Player = { id: string; name: string; jersey: string | null; team: string; starter: boolean | null; didNotPlay: boolean; minutes: string | null; points: number | null; rebounds: number | null; assists: number | null; url: string | null };
export type Quote = { provider: string; details: string; homeLine: number | null; totalLine: number | null; homePrice: number | null; awayPrice: number | null; overPrice: number | null; underPrice: number | null; quoteAt: string | null };
export type Game = { eventId: string; name: string; eventTime: string | null; state: string; statusText: string; teams: Team[]; players: Player[]; odds: Quote[]; url: string | null };
export type Standing = { id: string; name: string; short: string; wins: number | null; losses: number | null; winPercent: number | null; gamesBehind: number | null; rank: number | null; differential: number | null; streak: string | null };
export type Group = { id: string; name: string; season: string; rows: Standing[] };
export type Leader = { id: string; name: string; jersey: string | null; team: string | null; rank: number; value: number | null; displayValue: string; url: string | null };
export type Category = { id: string; name: string; abbreviation: string; rows: Leader[] };
export type TennisMatch = { id: string; date: string; round: string | null; roundId: string | null; state: string; players: { id: string; name: string; winner?: boolean; seed: number | null; sets: (number | null)[] }[] };
export type Tournament = { id: string; name: string; date: string; endDate: string; matches: TennisMatch[]; url: string | null };
export type ProMatch = { id: string; leagueId: string; league: string; seriesId: string; seriesType: number; radiant: string; dire: string; radiantScore: number | null; direScore: number | null; radiantWin: boolean | null; duration: number | null; eventTime: string | null };
export type DotaMatch = ProMatch & { patchId: number | null; goldAdvantage: (number | null)[]; xpAdvantage: (number | null)[]; picksBans: { heroId: number; team: number; pick: boolean; order: number }[]; players: { id: number | null; name: string | null; radiant: boolean; heroId: number; kills: number | null; deaths: number | null; assists: number | null; netWorth: number | null; goldPerMinute: number | null }[] };
export type SportsPayload = BasePayload & { game?: Game | null; groups?: Group[]; categories?: Category[]; season?: string; tournaments?: Tournament[]; match?: DotaMatch | null; matches?: ProMatch[] };
const nullableNumber = (v: unknown) => v === null || typeof v === 'number' && Number.isFinite(v);
const rows = (v: unknown, valid: (row: Record<string, unknown>) => boolean) => Array.isArray(v) && v.length <= 250 && v.every(r => record(r) && valid(r));
const numbered = (v: unknown) => Array.isArray(v) && v.length <= 180 && v.every(nullableNumber);
const identified = (r: Record<string, unknown>) => typeof r.id === 'string' && typeof r.name === 'string';
export function validateSports(v: unknown): v is SportsPayload {
  if (!isBasePayload(v)) return false;
  const p = v as Record<string, unknown>;
  if (v.panelId === 'sports-season-race') return rows(p.groups, g => typeof g.id === 'string' && rows(g.rows, r => identified(r) && ['wins', 'losses', 'winPercent', 'rank', 'gamesBehind', 'differential'].every(k => nullableNumber(r[k]))));
  if (v.panelId === 'sports-awards-watch') return p.categories === undefined || rows(p.categories, c => typeof c.id === 'string' && rows(c.rows, r => identified(r) && nullableNumber(r.value)));
  if (v.panelId === 'sports-tournament-path') return rows(p.tournaments, t => identified(t) && rows(t.matches, m => typeof m.id === 'string' && rows(m.players, r => identified(r) && numbered(r.sets))));
  if (v.panelId === 'esports-tournament-path') return rows(p.matches, m => typeof m.id === 'string' && typeof m.radiant === 'string' && typeof m.dire === 'string' && nullableNumber(m.radiantScore) && nullableNumber(m.direScore));
  if (v.panelId === 'esports-map-state') return p.match === null || record(p.match) && typeof p.match.id === 'string' && numbered(p.match.goldAdvantage) && numbered(p.match.xpAdvantage) && rows(p.match.players, r => typeof r.radiant === 'boolean' && ['kills', 'deaths', 'assists', 'netWorth'].every(k => nullableNumber(r[k])));
  return p.game === null || record(p.game) && typeof p.game.eventId === 'string'
    && rows(p.game.teams, r => identified(r) && nullableNumber(r.score) && numbered(r.periods))
    && rows(p.game.players, r => identified(r) && ['points', 'rebounds', 'assists'].every(k => nullableNumber(r[k])))
    && rows(p.game.odds, r => ['homeLine', 'totalLine', 'homePrice', 'awayPrice', 'overPrice', 'underPrice'].every(k => nullableNumber(r[k])));
}
export const num = (value: number | null | undefined, digits = 0) => value == null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: digits });
export const signed = (value: number | null | undefined) => value == null ? '—' : `${value > 0 ? '+' : ''}${num(value, 1)}`;
export const date = (value: string | null | undefined) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : 'Time unavailable';
export function seriesScores(match: ProMatch, firstTeam: string): [number | null, number | null] {
  if (match.radiant === firstTeam) return [match.radiantScore, match.direScore];
  if (match.dire === firstTeam) return [match.direScore, match.radiantScore];
  return [null, null];
}
