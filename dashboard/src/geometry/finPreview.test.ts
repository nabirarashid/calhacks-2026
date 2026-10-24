import { Box3, type BufferAttribute } from 'three';
import { describe, expect, it } from 'vitest';

import {
  FIN_PREVIEW_POSITION_COUNT,
  analyzeFinGeometry,
  bufferGeometryVolumeMm3,
  buildFinPreviewGeometry,
  finPlanformCorners,
  type FinPreviewParams,
} from './finPreview';

const cases: FinPreviewParams[] = [
  {
    root_chord: 90,
    taper_ratio: 0.5,
    semi_span: 60,
    sweep_deg: 30,
    thickness: 3,
    edge_profile: 'rounded',
    fin_count: 4,
  },
  {
    root_chord: 76,
    taper_ratio: 0.76,
    semi_span: 47.5,
    sweep_deg: 48,
    thickness: 3.9,
    edge_profile: 'beveled',
    fin_count: 4,
  },
  {
    root_chord: 51,
    taper_ratio: 0.66,
    semi_span: 39,
    sweep_deg: 44.5,
    thickness: 5,
    edge_profile: 'square',
    fin_count: 3,
  },
  {
    root_chord: 50,
    taper_ratio: 0.58,
    semi_span: 68,
    sweep_deg: 46,
    thickness: 3.9,
    edge_profile: 'beveled',
    fin_count: 4,
  },
  {
    root_chord: 111.5,
    taper_ratio: 0.61,
    semi_span: 43,
    sweep_deg: 26.5,
    thickness: 3.4,
    edge_profile: 'rounded',
    fin_count: 4,
  },
];

function contractFormula(params: FinPreviewParams) {
  const cT = params.root_chord * params.taper_ratio;
  const sweep = (params.sweep_deg * Math.PI) / 180;
  const xTipLe = params.semi_span * Math.tan(sweep);
  const xTipTe = xTipLe + cT;
  const area = (params.semi_span * (params.root_chord + cT)) / 2;
  const le = params.semi_span / Math.cos(sweep);
  const te = Math.hypot(params.semi_span, xTipTe - params.root_chord);
  let removed = 0;
  if (params.edge_profile === 'rounded') {
    removed = (0.5 - Math.PI / 8) * params.thickness ** 2 * (le + cT);
  } else if (params.edge_profile === 'beveled') {
    const bevel = Math.min(3 * params.thickness, 0.25 * cT);
    removed = 0.5 * bevel * params.thickness * (le + te);
  }
  return {
    volume: area * params.thickness - removed,
    xTipLe,
    xTipTe,
    bbox: [
      Math.min(0, xTipLe),
      -params.thickness / 2,
      0,
      Math.max(params.root_chord, xTipTe),
      params.thickness / 2,
      params.semi_span,
    ],
  };
}

describe('fin preview geometry', () => {
  it.each(cases)('matches the contract for %#', (params) => {
    const expected = contractFormula(params);
    const analysis = analyzeFinGeometry(params);
    expect(analysis.volume_mm3).toBeCloseTo(expected.volume, 8);
    expect(analysis.bbox_mm).toEqual(expected.bbox);
    expect(finPlanformCorners(params)).toEqual([
      [0, 0],
      [params.root_chord, 0],
      [expected.xTipTe, params.semi_span],
      [expected.xTipLe, params.semi_span],
    ]);

    const geometry = buildFinPreviewGeometry(params);
    const meshVolume = bufferGeometryVolumeMm3(geometry);
    expect(Math.abs(meshVolume - expected.volume) / expected.volume).toBeLessThan(0.01);

    const box = new Box3().setFromBufferAttribute(
      geometry.getAttribute('position') as BufferAttribute,
    );
    const actualBox = [box.min.x, box.min.y, box.min.z, box.max.x, box.max.y, box.max.z];
    actualBox.forEach((value, index) => expect(value).toBeCloseTo(expected.bbox[index], 4));
    geometry.dispose();
  });

  it('keeps one position topology across every edge profile', () => {
    const counts = (['square', 'rounded', 'beveled'] as const).map((edge_profile) => {
      const geometry = buildFinPreviewGeometry({ ...cases[0], edge_profile });
      const count = geometry.getAttribute('position').count;
      geometry.dispose();
      return count;
    });

    expect(new Set(counts).size).toBe(1);
    expect(counts[0]).toBe(FIN_PREVIEW_POSITION_COUNT);
  });
});
