import { describe, expect, it } from 'vitest';
import { countMentions, mentionPattern } from './model';

describe('written-remark counts', () => {
  it('counts only whole words case-insensitively, not prefixes or missing coverage', () => {
    expect(countMentions(['Inflation is not disinflation. INFLATION remains.'], 'inflation')).toBe(2);
    expect(countMentions([], 'inflation')).toBeNull();
    expect(countMentions(['Text exists'], '')).toBeNull();
    expect(countMentions(['Text exists'], 'inflation')).toBe(0);
  });
  it('escapes input regex syntax and highlights exactly the counted occurrences', () => {
    const input = 'Model 1.0 matters; model 1x0 differs.';
    expect(countMentions([input], '1.0')).toBe(1);
    expect(input.split(mentionPattern('1.0', true)!)).toEqual(['Model ', '1.0', ' matters; model 1x0 differs.']);
  });
});
