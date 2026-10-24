import type { AnyDarwinEvent, DesignResult, DesignSpace, Goal, HealthResponse, Preset, RunSummary } from '@shared/contracts';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { GoalComposer } from '@/components/GoalComposer';
import { MetricChips } from '@/components/MetricChips';
import {
  AgentFeed,
  BudgetMeters,
  LineageTree,
  PanelErrorBoundary,
  ParallelCoordinates,
  ParetoChart,
  ScoreChart,
} from '@/components/panels';
import { WinnerModal } from '@/components/WinnerModal';
import { api } from '@/lib/api';
import {
  fileSource,
  parseJsonl,
  selectActiveRun,
  selectSelectedDesign,
  useDashboardStore,
  wsSource,
  type EventSource,
  type SourceStatus,
} from '@/store';
import { FinHero } from '@/three';

type SourceKind = 'live' | 'replay' | 'file' | 'idle';

function StatusPill({
  sourceKind,
  sourceStatus,
  summary,
  connected,
}: {
  sourceKind: SourceKind;
  sourceStatus: SourceStatus | 'idle';
  summary?: RunSummary | null;
  connected: boolean;
}) {
  const degradations = summary?.degradations ?? [];
  const label = sourceKind === 'replay' || sourceKind === 'file'
    ? 'REPLAY'
    : degradations.some((value) => /llm|fallback/i.test(value))
      ? 'FALLBACK'
      : degradations.some((value) => /cache|onshape/i.test(value))
        ? 'CACHE'
        : sourceStatus === 'reconnecting' || sourceStatus === 'connecting'
          ? 'CONNECTING'
          : connected
            ? 'LIVE'
            : 'READY';
  return <span className={`status-pill status-${label.toLowerCase()}`}><i />{label}</span>;
}

function DarwinMark() {
  return (
    <div className="flex shrink-0 items-center gap-2.5" aria-label="Darwin">
      <svg width="28" height="32" viewBox="0 0 28 32" fill="none" aria-hidden="true">
        <path d="M5 3c11 0 18 5 18 13S16 29 5 29" stroke="currentColor" strokeWidth="2.4" />
        <path d="M5 8h8M5 16h13M5 24h8" stroke="currentColor" strokeWidth="1.4" opacity=".45" />
      </svg>
      <div><div className="text-lg font-semibold tracking-[.16em] text-white">DARWIN</div><div className="font-mono text-[8px] uppercase tracking-[.22em] text-mint/60">evolutionary engineering</div></div>
    </div>
  );
}

function ReplayControls({
  runs,
  disabled,
  onReplay,
  onInspect,
  onFile,
}: {
  runs: RunSummary[];
  disabled: boolean;
  onReplay: (recording: string, speed: number) => Promise<void>;
  onInspect: (runId: string) => Promise<void>;
  onFile: (file: File, speed: number) => Promise<void>;
}) {
  const [speed, setSpeed] = useState(2);
  const [busy, setBusy] = useState(false);
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const recordings = runs.filter((run) => Boolean(run.recording));
  const act = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
      if (detailsRef.current) detailsRef.current.open = false;
    } finally {
      setBusy(false);
    }
  };
  return (
    <details ref={detailsRef} className="relative">
      <summary className="control-button secondary list-none cursor-pointer">Replay ▾</summary>
      <div className="popover right-0 top-12 w-80">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <div><div className="eyebrow">Offline-safe</div><strong className="text-sm text-white">Recorded runs</strong></div>
          <select aria-label="Replay speed" className="rounded-lg border border-line bg-ink px-2 py-1 text-xs" value={speed} onChange={(event) => setSpeed(Number(event.target.value))}><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select>
        </div>
        <div className="mt-2 max-h-56 space-y-1 overflow-auto">
          {recordings.length ? recordings.map((run) => (
            <div key={run.run_id} className="flex items-center gap-2 rounded-lg border border-transparent p-2 hover:border-line hover:bg-white/[.02]">
              <button className="min-w-0 flex-1 text-left" onClick={() => void act(() => onInspect(run.run_id))}><div className="truncate text-xs text-slate-300">{run.goal.source_text}</div><div className="font-mono text-[9px] text-slate-600">{run.recording}</div></button>
              <button className="rounded-md border border-mint/30 px-2 py-1 text-[10px] text-mint" disabled={disabled || busy} onClick={() => void act(() => onReplay(run.recording!, speed))}>Play</button>
            </div>
          )) : <p className="p-3 text-center text-xs text-slate-500">No backend recordings yet.</p>}
        </div>
        <label className="mt-3 flex cursor-pointer items-center justify-center rounded-lg border border-dashed border-line px-3 py-2 text-xs text-slate-400 hover:border-cyan/40 hover:text-cyan">
          Load JSONL file
          <input className="sr-only" type="file" accept=".jsonl,application/x-ndjson" disabled={disabled || busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) void act(() => onFile(file, speed)); event.target.value = ''; }} />
        </label>
      </div>
    </details>
  );
}

function ReportViewer({ runId, onClose }: { runId: string; onClose: () => void }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Engineering report">
      <div className="modal-card h-[86vh] max-w-5xl p-2">
        <div className="flex items-center justify-between px-3 py-2"><div><div className="eyebrow text-mint">Engineering report</div><div className="font-mono text-[10px] text-slate-600">{runId}</div></div><button className="control-button secondary" onClick={onClose}>Close</button></div>
        <iframe className="h-[calc(100%-3.5rem)] w-full rounded-xl bg-white" src={`/api/runs/${runId}/report`} title="Darwin engineering report" />
      </div>
    </div>
  );
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [spaces, setSpaces] = useState<DesignSpace[]>([]);
  const [selectedSpaceId, setSelectedSpaceId] = useState('fin_v1');
  const [presets, setPresets] = useState<Preset[]>([]);
  const [goal, setGoal] = useState<Goal | null>(null);
  const [runList, setRunList] = useState<RunSummary[]>([]);
  const [sourceKind, setSourceKind] = useState<SourceKind>('idle');
  const [winnerOpen, setWinnerOpen] = useState(false);
  const [reportRunId, setReportRunId] = useState<string | null>(null);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [notice, setNotice] = useState<string | null>(null);
  const [startupError, setStartupError] = useState<string | null>(null);
  const connectionRef = useRef<(() => void) | null>(null);
  const winnerSeenRef = useRef<string | null>(null);

  const activeRun = useDashboardStore(selectActiveRun);
  const selectedDesign = useDashboardStore(selectSelectedDesign);
  const sourceStatus = useDashboardStore((state) => state.sourceStatus);
  const sourceError = useDashboardStore((state) => state.sourceError);
  const selectDesign = useDashboardStore((state) => state.selectDesign);
  const ingest = useDashboardStore((state) => state.ingest);
  const ingestMany = useDashboardStore((state) => state.ingestMany);
  const resetStore = useDashboardStore((state) => state.reset);
  const setActiveRun = useDashboardStore((state) => state.setActiveRun);
  const setSourceStatus = useDashboardStore((state) => state.setSourceStatus);
  const setSourceError = useDashboardStore((state) => state.setSourceError);
  const selectedSpace = spaces.find((space) => space.id === selectedSpaceId) ?? spaces[0] ?? null;
  const running = activeRun?.status === 'running';

  useEffect(() => {
    let cancelled = false;
    void Promise.allSettled([api.health(), api.spaces(), api.presets(), api.runs(), api.budget()]).then((results) => {
      if (cancelled) return;
      const [healthResult, spacesResult, presetsResult, runsResult, budgetResult] = results;
      if (healthResult.status === 'fulfilled') setHealth(healthResult.value);
      if (spacesResult.status === 'fulfilled') {
        setSpaces(spacesResult.value);
        if (spacesResult.value[0]) setSelectedSpaceId(spacesResult.value[0].id);
      }
      if (presetsResult.status === 'fulfilled') {
        setPresets(presetsResult.value);
        if (presetsResult.value[0]) setGoal(presetsResult.value[0].goal);
      }
      if (runsResult.status === 'fulfilled') setRunList(runsResult.value);
      if (budgetResult.status === 'fulfilled') {
        // Budget events remain the run source of truth; this confirms backend reachability.
      }
      const rejected = results.find((result): result is PromiseRejectedResult => result.status === 'rejected');
      if (rejected) setStartupError(rejected.reason instanceof Error ? rejected.reason.message : String(rejected.reason));
    });
    return () => { cancelled = true; connectionRef.current?.(); };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const error = activeRun?.errors.at(-1);
    if (error) setNotice(`${error.component}: ${error.message}`);
  }, [activeRun?.errors.length]);

  useEffect(() => {
    if (sourceError) setNotice(sourceError);
  }, [sourceError]);

  useEffect(() => {
    if (activeRun?.status === 'complete' && winnerSeenRef.current !== activeRun.runId) {
      winnerSeenRef.current = activeRun.runId;
      setWinnerOpen(true);
    }
  }, [activeRun?.runId, activeRun?.status]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const subscribe = useCallback((source: EventSource, kind: SourceKind) => {
    connectionRef.current?.();
    resetStore();
    setSourceKind(kind);
    setSourceError(null);
    let firstRunId: string | null = null;
    connectionRef.current = source.subscribe({
      status: (status) => setSourceStatus(kind === 'file' ? 'replay' : status),
      next: (event: AnyDarwinEvent) => {
        ingest(event);
        if (!firstRunId) {
          firstRunId = event.run_id;
          setActiveRun(event.run_id);
        }
      },
      error: (error) => setSourceError(error),
      complete: () => setSourceStatus('complete'),
    });
  }, [ingest, resetStore, setActiveRun, setSourceError, setSourceStatus]);

  const parseGoal = async (text: string) => {
    const parsed = await api.parseGoal(text, selectedSpaceId);
    setGoal(parsed);
    return parsed;
  };

  const startRun = async (runGoal: Goal) => {
    const response = await api.startRun(runGoal, selectedSpaceId, { profile: 'demo' });
    subscribe(wsSource(response.run_id), 'live');
    setWinnerOpen(false);
  };

  const replayRecording = async (recording: string, speed: number) => {
    const response = await api.replay(recording, speed);
    subscribe(wsSource(response.run_id), 'replay');
    setWinnerOpen(false);
  };

  const inspectRun = async (runId: string) => {
    connectionRef.current?.();
    resetStore();
    const events = parseJsonl(await api.events(runId));
    ingestMany(events);
    if (events[0]) setActiveRun(events[0].run_id);
    setSourceKind('replay');
    setSourceStatus('complete');
  };

  const replayFile = async (file: File, speed: number) => {
    subscribe(fileSource(await file.text(), speed), 'file');
    setWinnerOpen(false);
  };

  const chooseDesign = (design: DesignResult) => {
    try { selectDesign(design.design_id); } catch { setNotice('That referenced design is not in the active run.'); }
  };

  const displayDesign = selectedDesign ?? activeRun?.champion ?? activeRun?.seedDesign ?? null;
  const geometry = displayDesign
    ? activeRun?.geometriesByDesignId[displayDesign.design_id] ?? displayDesign.geometry
    : null;
  const objectiveMetrics = activeRun?.summary?.goal.objectives.map((objective) => objective.metric) ?? goal?.objectives.map((objective) => objective.metric) ?? [];
  const critic = activeRun?.agentMessages.filter((message) => message.agent === 'critic').at(-1);
  const defaultParams = useMemo(() => Object.fromEntries(selectedSpace?.parameters.map((parameter) => [parameter.name, parameter.default]) ?? []), [selectedSpace]);
  const resetKey = `${activeRun?.runId ?? 'empty'}:${activeRun?.lastSeq ?? 0}`;

  return (
    <div className="min-h-screen bg-ink text-slate-200">
      <header className="top-shell">
        <div className="flex items-start gap-5">
          <DarwinMark />
          <GoalComposer presets={presets} goal={goal} running={Boolean(running)} disabled={!selectedSpace} onParse={parseGoal} onGoalChange={setGoal} onRun={startRun} />
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
            {running && activeRun ? <button className="control-button danger" onClick={() => void api.stopRun(activeRun.runId)}>Stop</button> : null}
            <ReplayControls runs={runList} disabled={Boolean(running)} onReplay={replayRecording} onInspect={inspectRun} onFile={replayFile} />
            <button className="icon-button" type="button" aria-label="Toggle color theme" title="Toggle color theme" onClick={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? '☼' : '◐'}</button>
            <StatusPill sourceKind={sourceKind} sourceStatus={sourceStatus} summary={activeRun?.summary} connected={Boolean(health?.ok)} />
          </div>
        </div>
        <div className="mt-3 flex items-center gap-4 border-t border-line/70 pt-3">
          <label className="flex shrink-0 items-center gap-2 font-mono text-[9px] uppercase tracking-wider text-slate-500">Design space<select className="rounded-md border border-line bg-ink px-2 py-1 text-[10px] normal-case text-slate-300" value={selectedSpaceId} disabled={Boolean(running)} onChange={(event) => { setSelectedSpaceId(event.target.value); setGoal(null); }}>
            {spaces.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
          </select></label>
          <BudgetMeters budget={activeRun?.budget} compact className="flex-1" />
          <span className="hidden font-mono text-[9px] text-slate-600 2xl:block">{health ? `${health.modes.sim} sim · ${health.modes.cad} cad · ${health.modes.llm} llm` : 'backend unavailable'}</span>
        </div>
      </header>

      <main className="dashboard-shell">
        {(startupError && !health) ? <div className="mb-3 rounded-xl border border-amber/30 bg-amber/5 p-3 text-xs text-amber">Backend is unavailable: {startupError}. Load a JSONL recording from Replay for offline kiosk mode.</div> : null}
        <div className="dashboard-grid">
          <PanelErrorBoundary name="3D champion" resetKey={resetKey} className="hero-panel">
            <div className="hero-panel relative">
              <FinHero
                championParams={activeRun?.champion?.params ?? defaultParams}
                selectedParams={displayDesign?.params}
                seedParams={activeRun?.seedDesign?.params}
                geometry={geometry}
                generation={displayDesign?.generation}
                designLabel={displayDesign ? displayDesign.design_id.split('-').at(-1) : 'Default fin'}
                className="h-full min-h-0 !rounded-2xl"
                onStlError={() => setNotice('CAD STL could not load; analytic preview remains active.')}
              />
              <MetricChips design={displayDesign} catalog={activeRun?.metricCatalog ?? []} />
            </div>
          </PanelErrorBoundary>

          <div className="center-stack">
            <PanelErrorBoundary name="Score vs. evaluations" resetKey={resetKey}>
              <ScoreChart curves={{ agent: activeRun?.summary?.curves.agent ?? [], cmaes: activeRun?.baselineCurves.cmaes ?? [], random: activeRun?.baselineCurves.random ?? [] }} height={184} />
            </PanelErrorBoundary>
            <PanelErrorBoundary name="Pareto landscape" resetKey={resetKey}>
              <ParetoChart designs={activeRun?.designs} paretoIds={activeRun?.paretoIds} landscape={activeRun?.landscape} metricCatalog={activeRun?.metricCatalog} objectiveMetrics={objectiveMetrics} selectedDesignId={displayDesign?.design_id} onSelectDesign={chooseDesign} height={200} />
            </PanelErrorBoundary>
          </div>

          <PanelErrorBoundary name="Agent feed" resetKey={resetKey}>
            <AgentFeed className="feed-panel" messages={activeRun?.agentMessages} errors={activeRun?.errors} highlightedRef={displayDesign?.design_id} onReferenceClick={(designId) => { const design = activeRun?.designsById[designId]; if (design) chooseDesign(design); }} maxHeight={414} />
          </PanelErrorBoundary>

          <PanelErrorBoundary name="Design lineage" resetKey={resetKey}>
            <LineageTree className="lineage-panel" designs={activeRun?.designs} championId={activeRun?.championId} selectedDesignId={displayDesign?.design_id} onSelectDesign={chooseDesign} height={210} />
          </PanelErrorBoundary>
          <PanelErrorBoundary name="Parameter trade space" resetKey={resetKey}>
            <ParallelCoordinates className="parallel-panel" designs={activeRun?.designs} parameters={activeRun?.designSpace?.parameters} selectedDesignId={displayDesign?.design_id} onSelectDesign={chooseDesign} height={210} />
          </PanelErrorBoundary>
        </div>
      </main>

      {winnerOpen && activeRun?.summary?.status === 'complete' ? (
        <WinnerModal
          summary={activeRun.summary}
          designs={activeRun.designs}
          critic={critic}
          docUrl={activeRun.designSpace?.source.doc_url}
          onClose={() => setWinnerOpen(false)}
          onApprove={(design, approvedBy) => api.approve(activeRun.runId, design.design_id, approvedBy)}
          onReport={() => setReportRunId(activeRun.runId)}
        />
      ) : null}
      {reportRunId ? <ReportViewer runId={reportRunId} onClose={() => setReportRunId(null)} /> : null}
      {notice ? <div className="toast" role="status"><span>!</span>{notice}</div> : null}
    </div>
  );
}
