import type { ParamValue } from '@shared/contracts';
import {
  BufferGeometry,
  Float32BufferAttribute,
  type BufferAttribute,
} from 'three';

export type FinEdgeProfile = 'square' | 'rounded' | 'beveled';

export interface FinPreviewParams {
  root_chord: number;
  taper_ratio: number;
  semi_span: number;
  sweep_deg: number;
  thickness: number;
  edge_profile: FinEdgeProfile;
  fin_count: number;
}

export type FinParamInput = Record<string, ParamValue> | Partial<FinPreviewParams>;

export interface FinGeometryAnalysis {
  c_r: number;
  c_t: number;
  s: number;
  sweep_rad: number;
  t: number;
  x_tip_le: number;
  x_tip_te: number;
  area_mm2: number;
  mac_mm: number;
  le_len_mm: number;
  te_len_mm: number;
  tip_len_mm: number;
  aft_overhang_mm: number;
  bevel_mm: number;
  volume_mm3: number;
  bbox_mm: [number, number, number, number, number, number];
}

/**
 * All profiles deliberately use the same topology. The slices are only moved,
 * never added or removed, so every generated geometry can be vertex-lerped.
 */
export const FIN_PROFILE_SLICES = 33;
export const FIN_RING_VERTICES = 4;
export const FIN_PREVIEW_TRIANGLES = (FIN_PROFILE_SLICES - 1) * 8 + 4;
export const FIN_PREVIEW_POSITION_COUNT = FIN_PREVIEW_TRIANGLES * 3;

export const DEFAULT_FIN_PARAMS: FinPreviewParams = {
  root_chord: 90,
  taper_ratio: 0.5,
  semi_span: 60,
  sweep_deg: 30,
  thickness: 3,
  edge_profile: 'rounded',
  fin_count: 4,
};

const ROUNDED_REMOVAL_T2 = 0.5 - Math.PI / 8;

function finiteNumber(value: ParamValue | undefined, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function normalizeFinParams(
  params: FinParamInput | Partial<FinPreviewParams> | null | undefined,
): FinPreviewParams {
  const input = (params ?? {}) as Partial<Record<keyof FinPreviewParams, ParamValue>>;
  const profile = input.edge_profile;

  return {
    root_chord: Math.max(0.001, finiteNumber(input.root_chord, DEFAULT_FIN_PARAMS.root_chord)),
    taper_ratio: Math.max(0.001, finiteNumber(input.taper_ratio, DEFAULT_FIN_PARAMS.taper_ratio)),
    semi_span: Math.max(0.001, finiteNumber(input.semi_span, DEFAULT_FIN_PARAMS.semi_span)),
    sweep_deg: finiteNumber(input.sweep_deg, DEFAULT_FIN_PARAMS.sweep_deg),
    thickness: Math.max(0.001, finiteNumber(input.thickness, DEFAULT_FIN_PARAMS.thickness)),
    edge_profile:
      profile === 'square' || profile === 'rounded' || profile === 'beveled'
        ? profile
        : DEFAULT_FIN_PARAMS.edge_profile,
    fin_count: Math.max(1, Math.round(finiteNumber(input.fin_count, DEFAULT_FIN_PARAMS.fin_count))),
  };
}

/** Exact frozen-contract planform, bbox, and approximate edge-removal volume. */
export function analyzeFinGeometry(
  input: FinParamInput | Partial<FinPreviewParams>,
): FinGeometryAnalysis {
  const params = normalizeFinParams(input);
  const c_r = params.root_chord;
  const c_t = c_r * params.taper_ratio;
  const s = params.semi_span;
  const sweep_rad = (params.sweep_deg * Math.PI) / 180;
  const t = params.thickness;
  const x_tip_le = s * Math.tan(sweep_rad);
  const x_tip_te = x_tip_le + c_t;
  const area_mm2 = (s * (c_r + c_t)) / 2;
  const mac_mm =
    ((2 / 3) * c_r * (1 + params.taper_ratio + params.taper_ratio ** 2)) /
    (1 + params.taper_ratio);
  const le_len_mm = s / Math.cos(sweep_rad);
  const te_len_mm = Math.hypot(s, x_tip_te - c_r);
  const tip_len_mm = c_t;
  const bevel = Math.min(3 * t, 0.25 * c_t);

  let removed = 0;
  if (params.edge_profile === 'rounded') {
    removed = ROUNDED_REMOVAL_T2 * t ** 2 * (le_len_mm + tip_len_mm);
  } else if (params.edge_profile === 'beveled') {
    removed = 0.5 * bevel * t * (le_len_mm + te_len_mm);
  }

  return {
    c_r,
    c_t,
    s,
    sweep_rad,
    t,
    x_tip_le,
    x_tip_te,
    area_mm2,
    mac_mm,
    le_len_mm,
    te_len_mm,
    tip_len_mm,
    aft_overhang_mm: Math.max(0, x_tip_te - c_r),
    bevel_mm: params.edge_profile === 'beveled' ? bevel : 0,
    volume_mm3: area_mm2 * t - removed,
    bbox_mm: [
      Math.min(0, x_tip_le),
      -t / 2,
      0,
      Math.max(c_r, x_tip_te),
      t / 2,
      s,
    ],
  };
}

export function finBoundingBoxMm(
  params: FinParamInput | Partial<FinPreviewParams>,
): FinGeometryAnalysis['bbox_mm'] {
  return analyzeFinGeometry(params).bbox_mm;
}

export function finVolumeMm3(
  params: FinParamInput | Partial<FinPreviewParams>,
): number {
  return analyzeFinGeometry(params).volume_mm3;
}

/** Frozen-contract corners in root-LE, root-TE, tip-TE, tip-LE order. */
export function finPlanformCorners(
  params: FinParamInput | Partial<FinPreviewParams>,
): [[number, number], [number, number], [number, number], [number, number]] {
  const d = analyzeFinGeometry(params);
  return [
    [0, 0],
    [d.c_r, 0],
    [d.x_tip_te, d.s],
    [d.x_tip_le, d.s],
  ];
}

type Point = [number, number, number];

function ringAtY(params: FinPreviewParams, d: FinGeometryAnalysis, y: number): Point[] {
  const normalizedY = Math.min(1, Math.abs(y) / (d.t / 2));
  let leadingOffset = 0;
  let trailingOffset = 0;
  let tipOffset = 0;

  if (params.edge_profile === 'rounded') {
    // A sampled semicircle: u = r - sqrt(r^2 - y^2). Multiplying the
    // leading-edge normal offset by sec(sweep) turns it into an x offset.
    const normalOffset = (d.t / 2) * (1 - Math.sqrt(Math.max(0, 1 - normalizedY ** 2)));
    leadingOffset = normalOffset * (d.le_len_mm / d.s);
    tipOffset = normalOffset;
  } else if (params.edge_profile === 'beveled') {
    // Sharp at the mid-plane, linearly inset toward both plate faces. Scale
    // chordwise offsets so their swept-edge volume matches the frozen model.
    leadingOffset = d.bevel_mm * normalizedY * (d.le_len_mm / d.s);
    trailingOffset = d.bevel_mm * normalizedY * (d.te_len_mm / d.s);
  }

  const tipZ = Math.max(0, d.s - tipOffset);
  return [
    [leadingOffset, y, 0],
    [d.c_r - trailingOffset, y, 0],
    [d.x_tip_te - trailingOffset, y, tipZ],
    [d.x_tip_le + leadingOffset, y, tipZ],
  ];
}

/**
 * Build the display mesh in the frozen Onshape frame (x chord, y thickness,
 * z span). Rotate it -PI/2 about x in a Three.js scene to make span point up.
 */
export function buildFinPreviewGeometry(
  input: FinParamInput | Partial<FinPreviewParams>,
): BufferGeometry {
  const params = normalizeFinParams(input);
  const derived = analyzeFinGeometry(params);
  const positions: number[] = [];

  for (let slice = 0; slice < FIN_PROFILE_SLICES; slice += 1) {
    const y = -derived.t / 2 + (derived.t * slice) / (FIN_PROFILE_SLICES - 1);
    for (const point of ringAtY(params, derived, y)) positions.push(...point);
  }

  const indices: number[] = [];
  for (let slice = 0; slice < FIN_PROFILE_SLICES - 1; slice += 1) {
    const lower = slice * FIN_RING_VERTICES;
    const upper = (slice + 1) * FIN_RING_VERTICES;
    for (let edge = 0; edge < FIN_RING_VERTICES; edge += 1) {
      const next = (edge + 1) % FIN_RING_VERTICES;
      indices.push(lower + edge, upper + edge, upper + next);
      indices.push(lower + edge, upper + next, lower + next);
    }
  }

  // End caps. The ring order is counter-clockwise in the x/z plane.
  indices.push(0, 1, 2, 0, 2, 3);
  const top = (FIN_PROFILE_SLICES - 1) * FIN_RING_VERTICES;
  indices.push(top, top + 2, top + 1, top, top + 3, top + 2);

  const indexed = new BufferGeometry();
  indexed.setAttribute('position', new Float32BufferAttribute(positions, 3));
  indexed.setIndex(indices);
  const geometry = indexed.toNonIndexed();
  indexed.dispose();
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  geometry.userData.fin = { params, analysis: derived };
  return geometry;
}

/** Signed-tetrahedron volume, useful for geometry regression tests and QA. */
export function bufferGeometryVolumeMm3(geometry: BufferGeometry): number {
  const position = geometry.getAttribute('position') as BufferAttribute;
  const index = geometry.getIndex();
  let signedSixVolume = 0;

  const addTriangle = (a: number, b: number, c: number) => {
    const ax = position.getX(a);
    const ay = position.getY(a);
    const az = position.getZ(a);
    const bx = position.getX(b);
    const by = position.getY(b);
    const bz = position.getZ(b);
    const cx = position.getX(c);
    const cy = position.getY(c);
    const cz = position.getZ(c);
    signedSixVolume +=
      ax * (by * cz - bz * cy) -
      ay * (bx * cz - bz * cx) +
      az * (bx * cy - by * cx);
  };

  if (index) {
    for (let i = 0; i < index.count; i += 3) {
      addTriangle(index.getX(i), index.getX(i + 1), index.getX(i + 2));
    }
  } else {
    for (let i = 0; i < position.count; i += 3) addTriangle(i, i + 1, i + 2);
  }
  return Math.abs(signedSixVolume) / 6;
}
