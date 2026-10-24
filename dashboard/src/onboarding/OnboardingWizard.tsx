import { useMemo, useState } from 'react';

import { CapabilityReport } from './CapabilityReport';
import type { DroidDraftResult } from './DroidDraftPanel';
import type {
  ActivationResult,
  BlockingQuestion,
  Maturity,
  OnboardingInspection,
  ParamRole,
  ParamSemantics,
  ProbeResult,
  ProjectManifestDraft,
  QuestionValue,
  ReviewSubmission,
} from './types';

const stages = [
  { id: 'source', label: 'URL' },
  { id: 'inventory', label: 'Inventory' },
  { id: 'semantics', label: 'Semantics' },
  { id: 'questions', label: 'Inputs' },
  { id: 'probes', label: 'Probes' },
  { id: 'activate', label: 'Activate' },
] as const;

type WizardStage = (typeof stages)[number]['id'];
type DraftAnswer = string | string[];
type QuestionInputKind = 'select' | 'multi-select' | 'number' | 'vector' | 'text';

const maturityNames: Record<Maturity, string> = {
  0: 'Unsupported',
  1: 'Inventory-only',
  2: 'Manifest-reviewed',
  3: 'Solver-ready',
  4: 'Write-enabled',
};

export function questionInputKind(question: BlockingQuestion): QuestionInputKind {
  const field = question.field.toLowerCase();
  if (field.includes('fixture')) return 'multi-select';
  if (field.endsWith('vector_n') || field.includes('load_vector')) return 'vector';
  if (question.options?.length) return 'select';
  if (field.includes('safety_factor')) return 'number';
  return 'text';
}

function isFiniteNumber(value: string): boolean {
  return value.trim() !== '' && Number.isFinite(Number(value));
}

export function isQuestionAnswered(question: BlockingQuestion, answer: DraftAnswer | undefined): boolean {
  const kind = questionInputKind(question);
  if (kind === 'vector') {
    return Array.isArray(answer) && answer.length === 3 && answer.every(isFiniteNumber);
  }
  if (kind === 'multi-select') return Array.isArray(answer) && answer.length > 0;
  if (kind === 'number') return typeof answer === 'string' && isFiniteNumber(answer);
  return typeof answer === 'string' && answer.trim().length > 0;
}

export function serializeQuestionAnswers(
  questions: BlockingQuestion[],
  draftAnswers: Record<string, DraftAnswer>,
): Record<string, QuestionValue> {
  return Object.fromEntries(questions.map((question) => {
    const answer = draftAnswers[question.field];
    const kind = questionInputKind(question);
    if (kind === 'vector') return [question.field, (answer as string[]).map(Number)];
    if (kind === 'number') return [question.field, Number(answer)];
    return [question.field, answer];
  }));
}

function initialAnswers(questions: BlockingQuestion[]): Record<string, DraftAnswer> {
  return Object.fromEntries(questions.map((question) => {
    const kind = questionInputKind(question);
    return [question.field, kind === 'vector' ? ['', '', ''] : kind === 'multi-select' ? [] : ''];
  }));
}

function formatRange(input: OnboardingInspection['inventory']['config_inputs'][number]): string {
  if (input.choices?.length) return input.choices.join(' · ');
  if (input.min === undefined && input.max === undefined) return '—';
  return `${input.min ?? '—'} – ${input.max ?? '—'}`;
}

function probeState(probe: ProbeResult): boolean | null {
  if (!probe.evidence || !probe.evidence.parse_ok || !probe.evidence.watertight) return false;
  if (probe.evidence.checks.some((check) => check.passed === false)) return false;
  if (probe.evidence.checks.some((check) => check.passed === null)) return null;
  return true;
}

interface StepActionsProps {
  back?: () => void;
  next?: () => void;
  nextLabel: string;
  disabled?: boolean;
  busy?: boolean;
}

function StepActions({ back, next, nextLabel, disabled, busy }: StepActionsProps) {
  return (
    <div className="mt-5 flex items-center justify-between gap-3 border-t border-line pt-4">
      {back ? <button className="control-button secondary" type="button" onClick={back}>Back</button> : <span />}
      <button className="control-button primary" type="button" disabled={disabled || busy} onClick={next}>
        {busy ? 'Working…' : nextLabel}
      </button>
    </div>
  );
}

interface QuestionFieldProps {
  question: BlockingQuestion;
  value: DraftAnswer | undefined;
  onChange: (value: DraftAnswer) => void;
}

function QuestionField({ question, value, onChange }: QuestionFieldProps) {
  const kind = questionInputKind(question);
  const baseClass = 'mt-2 w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan/60';

  if (kind === 'select') {
    return (
      <select aria-label={question.prompt} className={baseClass} value={typeof value === 'string' ? value : ''} onChange={(event) => onChange(event.target.value)}>
        <option value="">Select a confirmed value…</option>
        {question.options?.map((option) => <option value={option} key={option}>{option}</option>)}
      </select>
    );
  }

  if (kind === 'multi-select') {
    const selected = Array.isArray(value) ? value : [];
    return (
      <fieldset className="mt-2 flex flex-wrap gap-2">
        <legend className="sr-only">{question.prompt}</legend>
        {question.options?.map((option) => (
          <label className="flex items-center gap-2 rounded-lg border border-line bg-ink px-3 py-2 text-xs text-slate-300" key={option}>
            <input
              aria-label={`${question.prompt}: ${option}`}
              type="checkbox"
              checked={selected.includes(option)}
              onChange={(event) => onChange(event.target.checked
                ? [...selected, option]
                : selected.filter((item) => item !== option))}
            />
            {option}
          </label>
        ))}
      </fieldset>
    );
  }

  if (kind === 'vector') {
    const vector = Array.isArray(value) ? value : ['', '', ''];
    return (
      <div className="mt-2 grid grid-cols-3 gap-2">
        {(['X', 'Y', 'Z'] as const).map((axis, index) => (
          <label className="text-[10px] text-slate-500" key={axis}>
            {axis} (N)
            <input
              aria-label={`${question.prompt} ${axis}`}
              className={baseClass}
              inputMode="decimal"
              type="number"
              value={vector[index] ?? ''}
              onChange={(event) => {
                const next = [...vector];
                next[index] = event.target.value;
                onChange(next);
              }}
            />
          </label>
        ))}
      </div>
    );
  }

  return (
    <input
      aria-label={question.prompt}
      className={baseClass}
      inputMode={kind === 'number' ? 'decimal' : undefined}
      min={kind === 'number' ? 0 : undefined}
      step={kind === 'number' ? 'any' : undefined}
      type={kind === 'number' ? 'number' : 'text'}
      value={typeof value === 'string' ? value : ''}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

export interface ProbeCardProps {
  probe: ProbeResult;
  onPreviewGeometry?: (probe: ProbeResult) => void;
}

export function ProbeCard({ probe, onPreviewGeometry }: ProbeCardProps) {
  const passed = probeState(probe);
  const tone = passed === true ? 'border-mint/30' : passed === false ? 'border-coral/30' : 'border-amber/30';
  const label = passed === true ? 'Pass' : passed === false ? 'Fail' : 'Blocked';
  const labelTone = passed === true ? 'text-mint' : passed === false ? 'text-coral' : 'text-amber';
  const previewReady = probe.geometry.status === undefined || probe.geometry.status === 'ready';

  return (
    <article className={`rounded-xl border bg-ink/45 p-3 ${tone}`}>
      <div className="flex gap-3">
        <button
          aria-label={`Preview STL for ${probe.case}`}
          className="group flex h-20 w-24 shrink-0 flex-col items-center justify-center rounded-lg border border-line bg-white/[.025] text-slate-500 transition hover:border-cyan/40 hover:text-cyan disabled:hover:border-line disabled:hover:text-slate-500"
          disabled={!previewReady || !onPreviewGeometry}
          onClick={() => onPreviewGeometry?.(probe)}
          type="button"
        >
          <span aria-hidden="true" className="mb-1 h-7 w-9 skew-x-[-12deg] border border-current bg-cyan/5" />
          <span className="font-mono text-[8px] uppercase tracking-wider">Preview STL</span>
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <h4 className="truncate font-mono text-xs text-slate-200">{probe.case}</h4>
            <span className={`font-mono text-[10px] font-semibold uppercase ${labelTone}`}>{label}</span>
          </div>
          <div className="mt-1 text-[10px] text-slate-500">
            {Object.entries(probe.params).map(([name, value]) => `${name}=${value}`).join(' · ')}
          </div>
          <ul className="mt-2 space-y-1 text-[10px] text-slate-400">
            {probe.evidence?.checks.map((check) => (
              <li key={check.id}>
                <span className={check.passed === true ? 'text-mint' : check.passed === false ? 'text-coral' : 'text-amber'}>
                  {check.passed === true ? '✓' : check.passed === false ? '×' : '—'}
                </span>{' '}
                {check.id}{check.detail ? ` · ${check.detail}` : ''}
              </li>
            )) ?? <li>No geometry evidence returned.</li>}
          </ul>
        </div>
      </div>
    </article>
  );
}

export interface OnboardingWizardProps {
  onInspect: (docUrl: string) => Promise<OnboardingInspection>;
  onReview: (submission: ReviewSubmission) => Promise<ProjectManifestDraft>;
  onProbe: (manifest: ProjectManifestDraft) => Promise<ProbeResult[]>;
  onActivate: (manifest: ProjectManifestDraft) => Promise<ActivationResult>;
  onPreviewGeometry?: (probe: ProbeResult) => void;
  onComplete?: (result: ActivationResult) => void;
  onCancel?: () => void;
  reviewer?: string;
  onDraftAdapter?: (report: ActivationResult['report']) => Promise<DroidDraftResult>;
  onOpenDraftPr?: (result: DroidDraftResult) => void;
}

export function OnboardingWizard({
  onInspect,
  onReview,
  onProbe,
  onActivate,
  onPreviewGeometry,
  onComplete,
  onCancel,
  reviewer = 'engineer',
  onDraftAdapter,
  onOpenDraftPr,
}: OnboardingWizardProps) {
  const [stage, setStage] = useState<WizardStage>('source');
  const [url, setUrl] = useState('');
  const [inspection, setInspection] = useState<OnboardingInspection | null>(null);
  const [manifest, setManifest] = useState<ProjectManifestDraft | null>(null);
  const [semantics, setSemantics] = useState<ParamSemantics[]>([]);
  const [answers, setAnswers] = useState<Record<string, DraftAnswer>>({});
  const [probes, setProbes] = useState<ProbeResult[]>([]);
  const [activation, setActivation] = useState<ActivationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stageIndex = stages.findIndex((item) => item.id === stage);
  const questions = inspection?.manifest.open_questions ?? [];
  const semanticsConfirmed = semantics.length > 0 && semantics.every((item) => item.confirmed && item.meaning.trim());
  const questionsAnswered = useMemo(
    () => questions.every((question) => isQuestionAnswered(question, answers[question.field])),
    [answers, questions],
  );

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const inspect = () => run(async () => {
    const result = await onInspect(url.trim());
    setInspection(result);
    setManifest(result.manifest);
    setSemantics(result.manifest.semantics.map((item) => ({ ...item })));
    setAnswers(initialAnswers(result.manifest.open_questions));
    setStage('inventory');
  });

  const review = () => run(async () => {
    if (!inspection) return;
    const reviewed = await onReview({
      project_id: inspection.project_id,
      revision: inspection.manifest.revision,
      by: reviewer,
      semantics,
      answers: serializeQuestionAnswers(questions, answers),
    });
    setManifest(reviewed);
    setStage('probes');
  });

  const probe = () => run(async () => {
    if (!manifest) return;
    setProbes(await onProbe(manifest));
  });

  const activate = () => run(async () => {
    if (!manifest) return;
    const result = await onActivate(manifest);
    setActivation(result);
    onComplete?.(result);
  });

  const patchSemantic = (index: number, patch: Partial<ParamSemantics>) => {
    setSemantics((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  };

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-panel/95 shadow-glow" aria-labelledby="onboarding-title">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <div className="eyebrow text-cyan">Read-only onboarding</div>
          <h2 id="onboarding-title" className="mt-1 text-xl font-semibold text-slate-100">Onboard an engineering object</h2>
          <p className="mt-1 text-xs text-slate-400">Review every inferred meaning. Darwin never invents material, load, fixture, or safety inputs.</p>
        </div>
        {onCancel ? <button className="control-button secondary" type="button" onClick={onCancel}>Close</button> : null}
      </header>

      <ol className="grid grid-cols-3 border-b border-line bg-ink/35 sm:grid-cols-6" aria-label="Onboarding progress">
        {stages.map((item, index) => (
          <li className={`border-r border-line px-2 py-3 text-center font-mono text-[9px] uppercase tracking-wider ${index === stageIndex ? 'bg-mint/5 text-mint' : index < stageIndex ? 'text-cyan/70' : 'text-slate-600'}`} aria-current={index === stageIndex ? 'step' : undefined} key={item.id}>
            <span className="mr-1">{index < stageIndex ? '✓' : index + 1}</span>{item.label}
          </li>
        ))}
      </ol>

      <div className="p-5">
        {error ? (
          <div className="mb-4 rounded-xl border border-coral/30 bg-coral/5 p-3 text-xs text-coral" role="alert">
            {error} No onboarding state was advanced.
          </div>
        ) : null}

        {stage === 'source' ? (
          <div>
            <h3 className="text-base font-semibold text-slate-100">Connect a Part Studio</h3>
            <p className="mt-1 text-xs text-slate-400">The URL is inspected read-only and is never placed in the committed manifest.</p>
            <label className="mt-5 block text-xs text-slate-400">
              Onshape Part Studio URL
              <input
                aria-label="Onshape Part Studio URL"
                autoFocus
                className="mt-2 w-full rounded-xl border border-line bg-ink px-3 py-3 text-sm text-slate-100 outline-none focus:border-cyan/60"
                placeholder="https://cad.onshape.com/documents/…/w/…/e/…"
                type="url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
              />
            </label>
            <StepActions busy={busy} disabled={!url.trim()} next={() => void inspect()} nextLabel="Inspect read-only" />
          </div>
        ) : null}

        {stage === 'inventory' && inspection ? (
          <div>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold text-slate-100">Inventory captured</h3>
                <p className="mt-1 text-xs text-slate-400">{inspection.inventory.parts.length} parts · {inspection.inventory.config_inputs.length} inputs · {inspection.inventory.onshape_calls} read calls</p>
              </div>
              <div className="rounded-lg border border-mint/25 bg-mint/5 px-3 py-2 font-mono text-[10px] text-mint">Read-only result</div>
            </div>
            <div className="mt-4 overflow-auto rounded-xl border border-line">
              <table className="w-full min-w-[620px] text-left text-xs">
                <thead className="bg-ink/60 font-mono text-[9px] uppercase tracking-wider text-slate-500">
                  <tr><th className="p-3">Input</th><th>Kind</th><th>Unit</th><th>Range / choices</th><th>Default</th></tr>
                </thead>
                <tbody>
                  {inspection.inventory.config_inputs.map((input) => (
                    <tr className="border-t border-line" key={input.id}>
                      <td className="p-3 font-mono text-cyan">{input.name}</td><td>{input.kind}</td><td>{input.unit ?? '—'}</td><td>{formatRange(input)}</td><td>{input.default ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {inspection.inventory.parts.map((part) => (
                <div className="rounded-xl border border-line bg-ink/35 p-3" key={part.part_id}>
                  <div className="text-xs font-semibold text-slate-200">{part.name}</div>
                  <div className="mt-1 font-mono text-[10px] text-slate-500">Mass {part.mass_g ?? '—'} g · Volume {part.volume_mm3 ?? '—'} mm³</div>
                </div>
              ))}
            </div>
            {inspection.report.unsupported.length ? <CapabilityReport className="mt-4" report={inspection.report} onDraftAdapter={onDraftAdapter} onOpenDraftPr={onOpenDraftPr} /> : null}
            <StepActions back={() => setStage('source')} next={() => setStage('semantics')} nextLabel="Review inventory" />
          </div>
        ) : null}

        {stage === 'semantics' ? (
          <div>
            <h3 className="text-base font-semibold text-slate-100">Confirm parameter semantics</h3>
            <p className="mt-1 text-xs text-slate-400">Confidence is a drafting aid only. Every row needs an engineer-confirmed role and meaning.</p>
            <div className="mt-4 space-y-3">
              {semantics.map((semantic, index) => (
                <div className="grid gap-3 rounded-xl border border-line bg-ink/35 p-3 md:grid-cols-[minmax(140px,.8fr)_minmax(220px,1.6fr)_140px_120px] md:items-center" key={semantic.name}>
                  <div>
                    <div className="font-mono text-xs text-cyan">{semantic.name}</div>
                    <div className="mt-1 font-mono text-[9px] text-slate-600">{semantic.cad_ref}</div>
                  </div>
                  <label className="text-[10px] text-slate-500">
                    Engineering meaning
                    <input aria-label={`${semantic.name} meaning`} className="mt-1 w-full rounded-lg border border-line bg-ink px-2 py-2 text-xs text-slate-200 outline-none focus:border-cyan/60" value={semantic.meaning} onChange={(event) => patchSemantic(index, { meaning: event.target.value, confirmed: false })} />
                  </label>
                  <label className="text-[10px] text-slate-500">
                    Role
                    <select aria-label={`${semantic.name} role`} className="mt-1 w-full rounded-lg border border-line bg-ink px-2 py-2 text-xs text-slate-200" value={semantic.role} onChange={(event) => patchSemantic(index, { role: event.target.value as ParamRole, confirmed: false })}>
                      <option value="editable">Editable</option><option value="fixed">Fixed</option><option value="protected">Protected</option>
                    </select>
                  </label>
                  <div>
                    {!semantic.confirmed && semantic.confidence !== null && semantic.confidence !== undefined ? (
                      <div className="mb-1 font-mono text-[9px] text-amber">Draft confidence {Math.round(semantic.confidence * 100)}%</div>
                    ) : null}
                    <label className="flex items-center gap-2 text-xs text-slate-300">
                      <input aria-label={`Confirm ${semantic.name}`} type="checkbox" checked={semantic.confirmed} onChange={(event) => patchSemantic(index, { confirmed: event.target.checked, confidence: event.target.checked ? null : semantic.confidence })} />
                      Confirm
                    </label>
                  </div>
                </div>
              ))}
            </div>
            <StepActions back={() => setStage('inventory')} disabled={!semanticsConfirmed} next={() => setStage('questions')} nextLabel="Continue to engineering inputs" />
          </div>
        ) : null}

        {stage === 'questions' ? (
          <div>
            <h3 className="text-base font-semibold text-slate-100">Supply blocking engineering inputs</h3>
            <p className="mt-1 text-xs text-slate-400">These values are deterministic manifest fields, recorded with their source. Draft confidence cannot answer them.</p>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {questions.map((question) => (
                <div className="rounded-xl border border-line bg-ink/35 p-4" key={question.id}>
                  <div className="flex items-start justify-between gap-3">
                    <label className="text-sm font-semibold text-slate-200" htmlFor={`question-${question.id}`}>{question.prompt}</label>
                    <span className="shrink-0 font-mono text-[9px] text-amber">For level {question.required_for}</span>
                  </div>
                  <p className="mt-1 text-[10px] leading-relaxed text-slate-500">{question.why}</p>
                  <QuestionField question={question} value={answers[question.field]} onChange={(value) => setAnswers((current) => ({ ...current, [question.field]: value }))} />
                  <div className="mt-2 font-mono text-[9px] text-slate-600">{question.field}</div>
                </div>
              ))}
            </div>
            <StepActions back={() => setStage('semantics')} busy={busy} disabled={!questionsAnswered} next={() => void review()} nextLabel="Save reviewed manifest" />
          </div>
        ) : null}

        {stage === 'probes' ? (
          <div>
            <h3 className="text-base font-semibold text-slate-100">Verify the configured design space</h3>
            <p className="mt-1 text-xs text-slate-400">Each case must regenerate and pass geometry checks. A missing check blocks; it never counts as a pass.</p>
            {probes.length ? (
              <div className="mt-4 grid gap-3 lg:grid-cols-2">
                {probes.map((result) => <ProbeCard key={result.case} probe={result} onPreviewGeometry={onPreviewGeometry} />)}
              </div>
            ) : (
              <div className="mt-5 rounded-xl border border-dashed border-line p-8 text-center text-xs text-slate-500">No probes have run for this reviewed manifest.</div>
            )}
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
              <button className="control-button secondary" type="button" onClick={() => setStage('questions')}>Back</button>
              <div className="flex gap-2">
                <button className="control-button secondary" disabled={busy} type="button" onClick={() => void probe()}>{busy ? 'Running…' : probes.length ? 'Run probes again' : 'Run deterministic probes'}</button>
                <button className="control-button primary" disabled={!probes.length || busy} type="button" onClick={() => setStage('activate')}>Review activation</button>
              </div>
            </div>
          </div>
        ) : null}

        {stage === 'activate' && inspection ? (
          <div>
            <h3 className="text-base font-semibold text-slate-100">Activate at the evidenced level</h3>
            <p className="mt-1 text-xs text-slate-400">Activation recomputes maturity from the reviewed manifest and probe evidence. It cannot promote beyond that evidence.</p>
            {activation ? (
              <div className="mt-5">
                <div className="rounded-xl border border-mint/30 bg-mint/5 p-5">
                  <div className="eyebrow text-mint">Level reached</div>
                  <div className="mt-1 text-2xl font-semibold text-mint">Level {activation.maturity} · {maturityNames[activation.maturity]}</div>
                  <div className="mt-3 font-mono text-[10px] text-slate-400">{activation.evidence.length} recorded evidence items</div>
                </div>
                <CapabilityReport className="mt-4" inventory={inspection.inventory} report={activation.report} onDraftAdapter={onDraftAdapter} onOpenDraftPr={onOpenDraftPr} />
              </div>
            ) : (
              <div className="mt-5 rounded-xl border border-line bg-ink/35 p-5">
                <div className="text-sm font-semibold text-slate-200">Ready for deterministic maturity evaluation</div>
                <p className="mt-1 text-xs text-slate-500">{probes.length} probe cases will be evaluated with the current manifest revision.</p>
              </div>
            )}
            <StepActions back={() => setStage('probes')} busy={busy} next={() => void activate()} nextLabel={activation ? 'Re-evaluate activation' : 'Activate project'} />
          </div>
        ) : null}
      </div>
    </section>
  );
}

