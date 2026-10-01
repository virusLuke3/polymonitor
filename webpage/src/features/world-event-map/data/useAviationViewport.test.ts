import { describe, it, expect } from 'vitest';
import { aviationQueryBounds } from './useAviationViewport';
import { splitViewportBounds, type RendererViewport } from '../renderer/MapRenderer';

const viewport=(bounds:RendererViewport['bounds'],width=500):RendererViewport=>({revision:1,bounds,center:[0,20],zoom:3,widthCssPx:width,heightCssPx:500});
describe('actual aviation viewport',()=>{
  it('splits both date-line halves, normalizes repeated worlds and preserves latitude',()=>{
    expect(splitViewportBounds(170,-30,200,55)).toEqual([[170,-30,180,55],[-180,-30,-160,55]]);
    expect(splitViewportBounds(170,-30,-160,55)).toEqual([[170,-30,180,55],[-180,-30,-160,55]]);
    expect(splitViewportBounds(-200,-80,200,80)).toEqual([[-180,-80,180,80]]);
    expect(splitViewportBounds(NaN,-30,200,55)).toEqual([]);
  });
  it('outward cache quantization covers all corners instead of snapping a center',()=>{
    const b=[-127.023,18.123,-61.045,55.889] as [number,number,number,number];
    const q=aviationQueryBounds(viewport([b]))[0]!;
    expect(q[0]).toBeLessThanOrEqual(b[0]);expect(q[1]).toBeLessThanOrEqual(b[1]);
    expect(q[2]).toBeGreaterThanOrEqual(b[2]);expect(q[3]).toBeGreaterThanOrEqual(b[3]);
    expect(aviationQueryBounds(viewport([[-140,18,-50,62]],800))).not.toEqual([q]);
  });
  it('does not query a global camera below the documented threshold',()=>{
    expect(aviationQueryBounds({...viewport([[-180,-85,180,85]]),zoom:1.5})).toEqual([]);
    expect(aviationQueryBounds(null)).toEqual([]);
  });
});
