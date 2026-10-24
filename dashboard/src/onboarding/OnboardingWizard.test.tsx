import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CapabilityReport } from './CapabilityReport';
import {
  OnboardingWizard,
  questionInputKind,
  serializeQuestionAnswers,
} from './OnboardingWizard';
import type {
  BlockingQuestion,
  CapabilityReportData,
  OnboardingInspection,
  ProbeResult,
  ProjectManifestDraft,
} from './types';

afterEach(cleanup);

const questions: BlockingQuestion[] = [
  { id: 'material', field: 'material.name', prompt: 'Material', why: 'Material properties drive stress.', required_for: 2, options: ['PLA', 'PETG'] },
  { id: 'source', field: 'material.source.source_id', prompt: 'Material source', why: 'Values require provenance.', required_for: 2, options: ['pla_tds_2024'] },
  { id: 'load', field: 'load_cases[0].vector_n', prompt: 'Load vector', why: 'Loads cannot be inferred.', required_for: 3 },
  { id: 'fixture', field: 'load_cases[0].fixtures', prompt: 'Fixtures', why: 'Boundary conditions are authoritative.', required_for: 3, options: ['mount_a', 'mount_b'] },
  { id: 'sf', field: 'requirements.safety_factor', prompt: 'Safety factor', why: 'The engineer owns the acceptance threshold.', required_for: 3 },
];

const report: CapabilityReportData = {
  project_id: 'bracket', maturity: 1, found: { domain_candidate: 'static structural', configured_inputs: 1 },
  missing: questions, unsupported: [], required_adapter: null,
};

const manifest: ProjectManifestDraft = {
  project_id: 'bracket', revision: 1, name: 'Bracket',
  semantics: [{ name: 'thickness', cad_ref: 'thickness', role: 'editable', meaning: 'Wall thickness', confidence: 0.82, confirmed: false }],
  open_questions: questions,
  authority: { maturity: 1, permitted: ['inspect'] },
};

const inspection: OnboardingInspection = {
  project_id: 'bracket', manifest, report,
  inventory: {
    provider: 'onshape', source_microversion: 'redacted', units: { length: 'mm' }, onshape_calls: 4,
    parts: [{ part_id: 'p1', name: 'L bracket', mass_g: 24, volume_mm3: 12_000 }],
    config_inputs: [{ id: 'thickness', name: 'thickness', kind: 'quantity', unit: 'mm', min: 2, max: 8, default: 4 }],
    features: [], mate_connectors: [{ id: 'mount_a', name: 'Mount A' }], export_formats: ['stl'],
  },
};

const probes: ProbeResult[] = [{
  case: 'seed', params: { thickness: 4 }, geometry: { geometry_key: 'g1', status: 'ready' },
  evidence: { parse_ok: true, watertight: true, checks: [{ id: 'protected_holes', passed: true, detail: 'unchanged' }] },
}];

describe('deterministic question fields', () => {
  it('derives controls and serializes authoritative values only from fields and options', () => {
    expect(questions.map(questionInputKind)).toEqual(['select', 'select', 'vector', 'multi-select', 'number']);
    expect(serializeQuestionAnswers(questions, {
      'material.name': 'PLA',
      'material.source.source_id': 'pla_tds_2024',
      'load_cases[0].vector_n': ['0', '-125', '0'],
      'load_cases[0].fixtures': ['mount_a', 'mount_b'],
      'requirements.safety_factor': '2',
    })).toEqual({
      'material.name': 'PLA',
      'material.source.source_id': 'pla_tds_2024',
      'load_cases[0].vector_n': [0, -125, 0],
      'load_cases[0].fixtures': ['mount_a', 'mount_b'],
      'requirements.safety_factor': 2,
    });
  });
});

describe('OnboardingWizard', () => {
  it('reviews semantics and blocking answers before probes and reports the exact achieved maturity', async () => {
    const reviewedManifest: ProjectManifestDraft = {
      ...manifest, revision: 2, semantics: [{ ...manifest.semantics[0], confidence: null, confirmed: true }],
      authority: { maturity: 2, permitted: ['inspect', 'probe'] },
    };
    const activatedReport = {
      ...report,
      maturity: 3 as const,
      missing: [{ id: 'write', field: 'cad.write_target_ref', prompt: 'Acknowledge an isolated write target', why: 'Writes require recovery isolation.', required_for: 4 as const }],
    };
    const onInspect = vi.fn().mockResolvedValue(inspection);
    const onReview = vi.fn().mockResolvedValue(reviewedManifest);
    const onProbe = vi.fn().mockResolvedValue(probes);
    const onActivate = vi.fn().mockResolvedValue({ maturity: 3, evidence: ['probe:seed', 'golden:beam'], report: activatedReport });

    render(<OnboardingWizard onActivate={onActivate} onInspect={onInspect} onProbe={onProbe} onReview={onReview} />);

    fireEvent.change(screen.getByLabelText('Onshape Part Studio URL'), { target: { value: 'https://cad.onshape.com/documents/demo/w/demo/e/demo' } });
    fireEvent.click(screen.getByRole('button', { name: 'Inspect read-only' }));
    expect(await screen.findByText('Inventory captured')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Review inventory' }));

    expect(screen.getByText('Draft confidence 82%')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Confirm thickness'));
    fireEvent.click(screen.getByRole('button', { name: 'Continue to engineering inputs' }));

    fireEvent.change(screen.getByLabelText('Material'), { target: { value: 'PLA' } });
    fireEvent.change(screen.getByLabelText('Material source'), { target: { value: 'pla_tds_2024' } });
    fireEvent.change(screen.getByLabelText('Load vector X'), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText('Load vector Y'), { target: { value: '-125' } });
    fireEvent.change(screen.getByLabelText('Load vector Z'), { target: { value: '0' } });
    fireEvent.click(screen.getByLabelText('Fixtures: mount_a'));
    fireEvent.change(screen.getByLabelText('Safety factor'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save reviewed manifest' }));

    expect(await screen.findByText('Verify the configured design space')).toBeInTheDocument();
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({
      project_id: 'bracket',
      answers: expect.objectContaining({ 'load_cases[0].vector_n': [0, -125, 0], 'requirements.safety_factor': 2 }),
    }));
    fireEvent.click(screen.getByRole('button', { name: 'Run deterministic probes' }));
    expect(await screen.findByText('protected_holes · unchanged')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Review activation' }));
    fireEvent.click(screen.getByRole('button', { name: 'Activate project' }));

    expect(await screen.findByText('Level 3 · Solver-ready')).toBeInTheDocument();
    expect(screen.getByText('Acknowledge an isolated write target')).toBeInTheDocument();
    await waitFor(() => expect(onActivate).toHaveBeenCalledWith(reviewedManifest));
  });
});

describe('CapabilityReport', () => {
  it('presents an unsupported object as a retained inventory result', () => {
    render(<CapabilityReport report={{
      project_id: 'duct', maturity: 1, found: { parts: 1, configuration_inputs: 3 }, missing: [],
      unsupported: ['Internal-flow analysis is not installed; CFD was not attempted by design.'],
      required_adapter: 'cfd_solver_adapter',
    }} />);

    expect(screen.getByText('Inspection complete')).toBeInTheDocument();
    expect(screen.getByText('Inventory-only')).toBeInTheDocument();
    expect(screen.getByText('cfd_solver_adapter')).toBeInTheDocument();
    expect(screen.getByText(/Inventory remains available/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
