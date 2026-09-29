import { describe, expect, it } from 'vitest';
import { enrichLocationPages } from '../src/modules/protocols/location-geometry';

const box = (x: number) => [x, 0.1, x + 0.01, 0.2];

describe('enrichLocationPages', () => {
  const group = {
    finding_group_id: 'G1',
    location_pages: {
      '140': [
        { stage: 'PD', file_id: 'F1', pdf_page_number: 88, is_anchor: true },
        { stage: 'RD', file_id: 'F2', pdf_page_number: 18, is_anchor: true },
      ],
      '142': [{ stage: 'PD', file_id: 'F1', pdf_page_number: 88, is_anchor: true }],
    },
  };
  const findings = [
    { finding_group_id: 'G1', location: '140', evidence: [{ stage: 'PD', file_id: 'F1', pdf_page_number: 88, geometry: { boxes: [box(0.2)] } }, { stage: 'RD', file_id: 'F2', pdf_page_number: 18, geometry: { boxes: [box(0.9)] } }] },
    { finding_group_id: 'G1', location: '142', evidence: [{ stage: 'PD', file_id: 'F1', pdf_page_number: 88, geometry: { boxes: [box(0.1)] } }] },
  ];

  it('copies each location boxes onto its own page refs, per stage', () => {
    type Out = { location_pages: Record<string, Array<{ geometry?: { boxes: number[][] } }>> };
    const [out] = enrichLocationPages([group], findings) as Out[];
    expect(out!.location_pages['140']![0]!.geometry!.boxes).toEqual([box(0.2)]);
    expect(out!.location_pages['140']![1]!.geometry!.boxes).toEqual([box(0.9)]);
    expect(out!.location_pages['142']![0]!.geometry!.boxes).toEqual([box(0.1)]);
  });

  it('does not mutate the cached input and skips refs on another page', () => {
    const moved = { ...group, location_pages: { '140': [{ stage: 'RD', file_id: 'F2', pdf_page_number: 20, is_anchor: false }] } };
    const out = enrichLocationPages([moved], findings) as Array<typeof moved>;
    expect(out[0]).toBe(moved);
    expect(enrichLocationPages([group], findings)[0]).not.toBe(group);
    expect((group.location_pages['140'][0] as { geometry?: unknown }).geometry).toBeUndefined();
  });

  it('passes groups without location_pages through', () => {
    const plain = { finding_group_id: 'G2' };
    expect(enrichLocationPages([plain], findings)[0]).toBe(plain);
  });
});
