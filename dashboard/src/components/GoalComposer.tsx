import type { Goal, Preset } from '@shared/contracts';
import { useState } from 'react';

interface GoalComposerProps {
  presets: Preset[];
  goal: Goal | null;
  running: boolean;
  disabled?: boolean;
  onParse: (text: string) => Promise<Goal>;
  onGoalChange: (goal: Goal) => void;
  onRun: (goal: Goal) => Promise<void>;
}

const goalLabel = (goal: Goal) =>
  goal.objectives.map((objective) => `${objective.direction} ${objective.metric}`).join(' · ');

export function GoalComposer({
  presets,
  goal,
  running,
  disabled,
  onParse,
  onGoalChange,
  onRun,
}: GoalComposerProps) {
  const [text, setText] = useState(goal?.source_text ?? 'Design a stable, low-drag rocket fin under 40 grams.');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parse = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await onParse(text.trim());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const runGoal = !goal || goal.source_text !== text.trim()
        ? await onParse(text.trim())
        : goal;
      await onRun(runGoal);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-w-0 flex-1">
      <div className="flex min-w-0 items-center gap-2">
        <div className="group relative min-w-0 flex-1">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 font-mono text-[9px] uppercase tracking-[0.16em] text-slate-600">
            Goal
          </span>
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void parse();
            }}
            disabled={disabled || running}
            aria-label="Engineering goal"
            className="h-11 w-full rounded-xl border border-line bg-ink/70 pl-[4.25rem] pr-3 text-sm text-slate-100 outline-none transition focus:border-mint/60 focus:ring-2 focus:ring-mint/10 disabled:opacity-60"
          />
        </div>
        <button className="control-button secondary" type="button" disabled={busy || disabled || running} onClick={() => void parse()}>
          Interpret
        </button>
        <button className="control-button primary" type="button" disabled={busy || disabled || running || !text.trim()} onClick={() => void run()}>
          {busy ? 'Working…' : running ? 'Running' : 'Run evolution'}
        </button>
      </div>

      <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5">
        {presets.slice(0, 3).map((preset) => (
          <button
            key={preset.label}
            type="button"
            disabled={running}
            onClick={() => {
              setText(preset.text);
              onGoalChange(preset.goal);
            }}
            className="rounded-full border border-line bg-white/[0.025] px-2.5 py-1 text-[10px] text-slate-400 transition hover:border-cyan/40 hover:text-cyan disabled:opacity-50"
          >
            {preset.label}
          </button>
        ))}
        {goal ? (
          <span className="ml-1 max-w-full truncate font-mono text-[9px] text-mint/70" title={goalLabel(goal)}>
            ✓ {goalLabel(goal)}
          </span>
        ) : null}
        {error ? <span className="font-mono text-[9px] text-coral">{error}</span> : null}
      </div>

      {goal ? (
        <details className="goal-strip mt-2">
          <summary>
            Interpreted goal · {goal.objectives.length} objectives · {goal.constraints.length} constraints · {goal.parsed_by}
          </summary>
          <div className="mt-2 flex flex-wrap gap-2">
            {goal.objectives.map((objective, index) => (
              <label key={`${objective.metric}-${index}`} className="goal-chip objective">
                <span>{objective.direction} {objective.metric}</span>
                {objective.direction === 'target' ? (
                  <input
                    aria-label={`${objective.metric} target`}
                    type="number"
                    value={objective.target ?? 0}
                    onChange={(event) => {
                      const objectives = [...goal.objectives];
                      objectives[index] = { ...objective, target: Number(event.target.value) };
                      onGoalChange({ ...goal, objectives });
                    }}
                  />
                ) : null}
              </label>
            ))}
            {goal.constraints.map((constraint, index) => (
              <label key={`${constraint.ref}-${index}`} className={`goal-chip ${constraint.hard ? 'hard' : 'soft'}`}>
                <span>{constraint.label || `${constraint.ref} ${constraint.op}`}</span>
                <input
                  aria-label={`${constraint.ref} limit`}
                  type="number"
                  value={constraint.value}
                  onChange={(event) => {
                    const constraints = [...goal.constraints];
                    constraints[index] = { ...constraint, value: Number(event.target.value) };
                    onGoalChange({ ...goal, constraints });
                  }}
                />
              </label>
            ))}
            {goal.assumptions.map((assumption) => (
              <span key={assumption} className="goal-chip assumption" title={assumption}>Assumption · {assumption}</span>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  );
}
