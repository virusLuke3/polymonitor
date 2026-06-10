import type { WorldCupMatch } from '../types';

export function sameBeijingDate(match: WorldCupMatch, now: Date) {
  const matchDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date(match.kickoffUtc));
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(now);
  return matchDate === today;
}

export function stageLabel(stage: string) {
  const labels: Record<string, string> = {
    group: 'GROUP',
    round32: 'R32',
    round16: 'R16',
    quarterfinal: 'QF',
    semifinal: 'SF',
    third_place: '3RD',
    final: 'FINAL',
  };
  return labels[stage] || String(stage || 'stage').toUpperCase();
}

export function scoreText(match: WorldCupMatch) {
  if (match.homeScore === undefined || match.awayScore === undefined) return 'VS';
  return `${match.homeScore}-${match.awayScore}`;
}

export function kickoffDay(match: WorldCupMatch) {
  const kickoff = match.kickoffBeijing || match.kickoffUtc || '';
  const suffix = kickoff.split(',').pop()?.trim();
  return suffix ? kickoff.replace(`, ${suffix}`, '') : kickoff || 'Kickoff pending';
}

export function kickoffTime(match: WorldCupMatch) {
  return match.kickoffBeijing.split(',').pop()?.trim() || match.kickoffBeijing;
}
