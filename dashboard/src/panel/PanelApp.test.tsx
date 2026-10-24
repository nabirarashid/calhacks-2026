import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDashboardStore } from '@/store';
import PanelApp from './PanelApp';

const fixture = readFileSync(
  resolve(process.cwd(), '../shared/fixtures/v2/sample_investigation.jsonl'),
  'utf8',
);

const inspect = {
  project_id: 'rear_wing',
  fixed: [],
  params: [
    { name: 'aoa_deg', unit: 'deg', value: 6, min: 0, max: 16 },
    { name: 'span_mm', unit: 'mm', value: 850, min: 700, max: 1000 },
    { name: 'chord_mm', unit: 'mm', value: 280, min: 200, max: 350 },
  ],
};

describe('compact investigation panel', () => {
  beforeEach(() => {
    useDashboardStore.getState().reset();
    window.history.pushState({}, '', '/panel?session=session_fixture_wing');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/inspect') return new Response(JSON.stringify(inspect), { status: 200, headers: { 'Content-Type': 'application/json' } });
      if (url === '/api/runs/session_fixture_wing/events') return new Response(fixture, { status: 200 });
      throw new Error(`Unexpected request: ${url}`);
    }));
  });

  afterEach(() => vi.unstubAllGlobals());

  it('renders the complete fixture as a reasoning timeline and final summary', async () => {
    render(<PanelApp />);

    await waitFor(() => expect(screen.getByText('Investigation complete')).toBeInTheDocument());
    expect(screen.getByText('Hypothesis 1')).toBeInTheDocument();
    expect(screen.getAllByText('accepted').length).toBeGreaterThan(0);
    expect(screen.getAllByText('rejected').length).toBeGreaterThan(0);
    expect(screen.getByText('Lab notebook')).toBeInTheDocument();
    expect(screen.getByLabelText(/Prediction accuracy \d+ percent/)).toBeInTheDocument();
    expect(screen.getByText(/Onshape version · Darwin:/)).toBeInTheDocument();
  });
});
