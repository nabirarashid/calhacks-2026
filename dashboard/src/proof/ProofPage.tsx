import { useEffect, useState } from 'react';

import './proof.css';

type Row = { method: string; label: string; median_final: number; pct_of_best: number; reached_95pct: number;
  median_sims_to_95pct: number | null };
type Goal = { goal: string; label: string; metric: string; unit: string; best_known: number; rows: Row[] };
type Summary = { sims_budget: number; repeats: number; generated_at: string; goals: Goal[] };

// D5: the C5 proof bench (scripts/plot_bench.py writes the chart and this summary into public/proof/).
export default function ProofPage() {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch('/proof/bench_wing_summary.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`bench summary ${r.status}`))))
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);
  return (
    <div className="proof">
      <main>
        <h1>Proof bench: does the reasoning beat search?</h1>
        <p className="lede">
          Same rear-wing solver, same {data?.sims_budget ?? 20}-simulation budget, {data?.repeats ?? 3} runs per goal.
          Darwin plans each simulation from aero principles and the last result; CMA-ES and random search try the same
          editable parameters with no reasoning. "Darwin, no principles" is the same agent with its knowledge layer
          removed.
        </p>
        <figure>
          <picture>
            <source srcSet="/proof/bench_wing_dark.png" media="(prefers-color-scheme: dark)" />
            <img src="/proof/bench_wing_light.png"
              alt="Median result as a percentage of the best design known, per goal: Darwin beats CMA-ES and random search on all three goals." />
          </picture>
        </figure>
        {error ? <p className="note">Couldn't load the numbers ({error}).</p> : null}
        {data?.goals.map((g) => (
          <div className="scroll" key={g.goal}>
            <table>
              <caption>{g.label} (best known {g.best_known} {g.unit})</caption>
              <thead>
                <tr><th>Method</th><th>Median result ({g.unit})</th><th>% of best</th><th>Runs reaching 95%</th>
                  <th>Median simulations to 95%</th></tr>
              </thead>
              <tbody>
                {g.rows.map((r) => (
                  <tr key={r.method}>
                    <td>{r.label}</td><td>{r.median_final}</td><td>{r.pct_of_best}%</td>
                    <td>{r.reached_95pct}/{data.repeats}</td><td>{r.median_sims_to_95pct ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
        <p className="note">
          Solver: rear_wing_v1 (AeroSandbox vortex lattice + NeuralFoil sections), the same one the live demo uses.
          Darwin planned with Claude Sonnet 5.5 for this bench (Sat Oct 24); the live demo runs Claude Haiku 5.5.
          Raw runs: demo/bench_wing.json. The earlier population dashboard is at <a href="/population">/population</a>.
        </p>
      </main>
    </div>
  );
}
