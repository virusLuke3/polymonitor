export function mentionPattern(term: string, capture = false): RegExp | null {
  const word = term.trim().slice(0, 40);
  if (!word) return null;
  const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const expression = `\\b${escaped}\\b`;
  return new RegExp(capture ? `(${expression})` : expression, 'gi');
}

export function countMentions(paragraphs: string[], term: string): number | null {
  const pattern = mentionPattern(term);
  return !paragraphs.length || !pattern ? null
    : paragraphs.reduce((sum, paragraph) => sum + [...paragraph.matchAll(pattern)].length, 0);
}
