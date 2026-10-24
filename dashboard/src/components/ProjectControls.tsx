import type { Maturity, ProjectSummary } from '@/lib/projects';
import { MATURITY_LABELS, MATURITY_PERMISSIONS } from '@/lib/projects';

const MATURITY_STYLES: Record<Maturity, string> = {
  0: 'border-slate-600 bg-slate-500/5 text-slate-400',
  1: 'border-cyan/30 bg-cyan/5 text-cyan',
  2: 'border-amber/30 bg-amber/5 text-amber',
  3: 'border-mint/30 bg-mint/5 text-mint',
  4: 'border-mint/50 bg-mint/10 text-mint',
};

export function MaturityBadge({ maturity, compact = false }: { maturity: Maturity; compact?: boolean }) {
  const label = MATURITY_LABELS[maturity];
  const permission = MATURITY_PERMISSIONS[maturity];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-mono font-semibold uppercase tracking-wider ${MATURITY_STYLES[maturity]} ${compact ? 'px-2 py-1 text-[8px]' : 'px-2.5 py-1.5 text-[9px]'}`}
      title={`Level ${maturity}: ${label}. ${permission}.`}
      aria-label={`Maturity level ${maturity}, ${label}. ${permission}.`}
    >
      <i className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      L{maturity} · {label}
    </span>
  );
}

export function ProjectSwitcher({
  projects,
  selectedId,
  disabled,
  onChange,
}: {
  projects: ProjectSummary[];
  selectedId: string;
  disabled?: boolean;
  onChange: (projectId: string) => void;
}) {
  const selected = projects.find((project) => project.project_id === selectedId) ?? projects[0];
  return (
    <div className="flex min-w-0 items-center gap-2">
      <label className="flex min-w-0 items-center gap-2 font-mono text-[9px] uppercase tracking-wider text-slate-500">
        Project
        <select
          aria-label="Project"
          className="max-w-56 truncate rounded-md border border-line bg-ink px-2 py-1 text-[10px] normal-case text-slate-300"
          value={selected?.project_id ?? ''}
          disabled={disabled || projects.length === 0}
          onChange={(event) => onChange(event.target.value)}
        >
          {projects.map((project) => (
            <option key={project.project_id} value={project.project_id}>{project.name}</option>
          ))}
        </select>
      </label>
      {selected ? <MaturityBadge maturity={selected.maturity} compact /> : <MaturityBadge maturity={0} compact />}
    </div>
  );
}

