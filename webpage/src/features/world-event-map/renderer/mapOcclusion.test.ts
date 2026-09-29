import { describe, expect, it } from 'vitest';
import { boxesOverlap, clearMapPosition } from './mapOcclusion';
import type { ScreenBox } from './layerFactories/eventClusters';

describe('shared tooltip and selection safe areas', () => {
  const controls: ScreenBox[] = [[10, 10, 90, 150], [760, 10, 990, 360], [10, 540, 450, 590]];
  for (const [x, y] of [[0, 0], [995, 0], [0, 595], [995, 595]]) {
    it(`keeps the corner ${x},${y} visible without covering controls`, () => {
      const p = clearMapPosition({ x: x!, y: y! }, [200, 90], [1000, 600], controls);
      const box: ScreenBox = [p.x, p.y, p.x + 200, p.y + 90];
      expect(p.x).toBeGreaterThanOrEqual(12); expect(p.y).toBeGreaterThanOrEqual(12);
      expect(box[2]).toBeLessThanOrEqual(988); expect(box[3]).toBeLessThanOrEqual(588);
      expect(controls.some(control => boxesOverlap(box, control))).toBe(false);
    });
  }
});
