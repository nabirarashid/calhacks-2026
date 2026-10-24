import { describe, expect, it } from 'vitest';
import { clampMaturity, MATURITY_PERMISSIONS } from './projects';

describe('project maturity', () => {
  it('clamps untrusted API values to the supported ladder', () => {
    expect(clampMaturity(-2)).toBe(0);
    expect(clampMaturity(3.8)).toBe(3);
    expect(clampMaturity(99)).toBe(4);
    expect(clampMaturity('4')).toBe(0);
  });

  it('never grants write language below level four', () => {
    expect(Object.entries(MATURITY_PERMISSIONS).filter(([level, copy]) => level !== '4' && /apply|write/i.test(copy))).toEqual([]);
  });
});
