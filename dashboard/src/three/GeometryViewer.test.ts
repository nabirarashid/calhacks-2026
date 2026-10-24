import type { GeometryRef } from '@shared/contracts';
import { describe, expect, it } from 'vitest';
import { geometryViewerState } from './GeometryViewer';

const geometry = (status: GeometryRef['status'], stl_url?: string): GeometryRef => ({
  geometry_key: 'fixture',
  status,
  source: 'mock',
  stl_url,
  onshape_calls: 0,
  elapsed_ms: 0,
});

describe('geometryViewerState', () => {
  it('renders only ready geometry with an STL URL', () => {
    expect(geometryViewerState(geometry('ready', '/fixture.stl'))).toBe('loading');
    expect(geometryViewerState(geometry('ready'))).toBe('failed');
    expect(geometryViewerState(geometry('failed', '/stale.stl'))).toBe('failed');
    expect(geometryViewerState(geometry('pending', '/early.stl'))).toBe('pending');
  });
});
