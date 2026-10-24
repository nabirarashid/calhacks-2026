import type { DesignResult, RunSummary } from '@shared/contracts';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WinnerModal } from './WinnerModal';

const champion: DesignResult = {
  design_id: 'champion', run_id: 'run-1', generation: 2, origin: 'agent',
  params: { chord_mm: 12 }, param_hash: 'exact-hash', parent_ids: [], operator: 'refine', rationale: 'Best feasible result.',
  score: { metrics: { drag_n: 1.2 }, objective_scores: {}, violations: [], feasible: true, aggregate: 0.9, warnings: [], fidelity: 'high', eval_ms: 1 },
  geometry: { geometry_key: 'g1', status: 'ready', source: 'onshape_config', regen_status: 'OK', onshape_calls: 1, elapsed_ms: 10 },
  timings_ms: {},
};

const summary: RunSummary = {
  run_id: 'run-1', status: 'complete', goal: { source_text: 'Improve it', objectives: [], constraints: [], fixed_params: {}, context_overrides: {}, assumptions: [], parsed_by: 'manual' },
  design_space_id: 'fin_v1',
  config: { population: 1, generations: 1, elites: 1, seed: 1, baselines: [], early_stop_patience: 1, min_improvement: 0, geometry_max_builds: 1, geometry_min_improvement: 0, llm_max_calls: 0, llm_max_spend_usd: 0, profile: 'demo' },
  started_at: '2026-10-24T00:00:00Z', champion, seed_design: { ...champion, design_id: 'seed', params: { chord_mm: 10 } },
  baseline_best: {}, curves: {}, pareto_ids: ['champion'], degradations: [],
};

const preview = {
  target: 'Disposable fin copy',
  param_diff: [{ name: 'chord_mm', before: 10, after: 12 }],
  expected_calls: 4,
  checks_planned: ['Read configuration back', 'Verify exported geometry'],
  maturity: 4,
};

const baseProps = {
  summary,
  designs: [champion],
  onClose: vi.fn(),
  onReport: vi.fn(),
};

afterEach(cleanup);

describe('WinnerModal Onshape version flow', () => {
  it('keeps version creation disabled below maturity 4 even with exact approval', async () => {
    render(<WinnerModal
      {...baseProps}
      onApprove={vi.fn()}
      onApprovalStatus={() => Promise.resolve({ status: 'approved', design_id: 'champion', param_hash: 'exact-hash' })}
      onCommitPreview={() => Promise.resolve({ ...preview, maturity: 3 })}
    />);

    const createButton = screen.getByRole('button', { name: 'Create Onshape Version' });
    await waitFor(() => expect(screen.getByText('Maturity 3 · write blocked')).toBeInTheDocument());
    expect(createButton).toBeDisabled();
  });

  it('keeps creation disabled for stale approval, then confirms and renders complete evidence', async () => {
    const onApprove = vi.fn().mockResolvedValue({ status: 'approved', design_id: 'champion', param_hash: 'exact-hash' });
    const onCommit = vi.fn().mockResolvedValue({
      geometry: { geometry_key: 'g1', status: 'ready', source: 'onshape_config', onshape_calls: 4, elapsed_ms: 100 },
      written_values: { chord_mm: 12 }, read_back: { chord_mm: 12 },
      geometry_check: { passed: true, detail: 'bounds match' },
      version_name: 'Darwin verified g1',
    });
    render(<WinnerModal
      {...baseProps}
      onApprove={onApprove}
      onApprovalStatus={() => Promise.resolve({ status: 'approved', design_id: 'champion', param_hash: 'stale-hash' })}
      onCommitPreview={() => Promise.resolve(preview)}
      onCommit={onCommit}
    />);

    const createButton = screen.getByRole('button', { name: 'Create Onshape Version' });
    await waitFor(() => expect(screen.getByText('Maturity 4 · write-enabled')).toBeInTheDocument());
    expect(createButton).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Approve design' }));
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);

    expect(screen.getByRole('alertdialog', { name: 'Confirm Onshape version creation' })).toBeInTheDocument();
    expect(screen.getByText('Disposable fin copy')).toBeInTheDocument();
    expect(screen.getByText('4 Onshape calls')).toBeInTheDocument();
    expect(screen.getByText(/Read configuration back/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm write, verify & version' }));
    await waitFor(() => expect(screen.getByText('Verified version created')).toBeInTheDocument());
    expect(screen.getByText('Darwin verified g1')).toBeInTheDocument();
    expect(screen.getByText(/Passed · ready · bounds match/)).toBeInTheDocument();
    expect(onCommit).toHaveBeenCalledWith(champion);
  });

  it('shows recovery guidance and never success for a partial write', async () => {
    render(<WinnerModal
      {...baseProps}
      onApprove={vi.fn()}
      onApprovalStatus={() => Promise.resolve({ status: 'approved', design_id: 'champion', param_hash: 'exact-hash' })}
      onCommitPreview={() => Promise.resolve(preview)}
      onCommit={() => Promise.resolve({
        status: 'partial',
        geometry: { geometry_key: 'g1', status: 'failed', source: 'onshape_config', onshape_calls: 3, elapsed_ms: 100 },
        written_values: { chord_mm: 12 }, read_back: { chord_mm: 11 },
        geometry_check: { passed: false, detail: 'read-back mismatch' },
        recovery_steps: ['Restore the previous Onshape version.'],
      })}
    />);

    const createButton = screen.getByRole('button', { name: 'Create Onshape Version' });
    await waitFor(() => expect(createButton).toBeEnabled());
    fireEvent.click(createButton);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm write, verify & version' }));

    await waitFor(() => expect(screen.getByText('Partial write · recovery required')).toBeInTheDocument());
    expect(screen.getByText('Recovery steps')).toBeInTheDocument();
    expect(screen.getByText('1. Restore the previous Onshape version.')).toBeInTheDocument();
    expect(screen.queryByText('Verified version created')).not.toBeInTheDocument();
  });
});
