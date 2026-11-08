import { expect, it } from 'vitest';
import { Panel } from '@/components/Panel';
import { Frame as EvidenceFrame } from './ui';
import { Frame as SportsFrame } from '../sports-expansion/ui';
import { Frame as CultureFrame } from '../culture-tech';

it('keeps the real workspace shell and refresh controls through loading, empty and available states', () => {
  // The workspace provides runtime state but does not wrap renderer bodies in Panel.
  for (const status of [undefined, 'unavailable', 'ok']) {
    const data = status ? { panelId: 'test', schemaVersion: 1, generatedAt: null, status, sources: [], items: [] } : undefined;
    for (const Frame of [EvidenceFrame, SportsFrame, CultureFrame]) {
      const result = Frame({ id: 'test', title: 'Test evidence', data, children: 'Observation' });
      expect(result.type).toBe(Panel);
      expect(result.props).toMatchObject({ title: 'Test evidence', dataPanelId: 'test' });
      expect(result.props.controls).toBeTruthy();
    }
  }
});
