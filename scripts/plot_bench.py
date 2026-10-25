"""C5 proof-bench chart for the pitch deck and the /proof page (PLAN.md D4/D5).

Reads demo/bench_wing.json; writes demo/bench_wing_{light,dark}.png and copies them, plus a small
summary JSON, to dashboard/public/proof/. Run: PYTHONPATH=. ~/.venvs/darwin/bin/python scripts/plot_bench.py
Each panel is one goal; bars are each method's median final result as % of the best design known for
that goal (for minimum drag: best / result), so all three goals share one scale.
"""
import json
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
METHODS = [("darwin", "Darwin"), ("darwin_noknow", "Darwin, no principles"), ("cmaes", "CMA-ES"), ("random", "Random")]
GOALS = [("downforce_drag15", "Max downforce, drag ≤ 15 N"), ("downforce_span_fixed", "Same, span locked"),
         ("min_drag_df120", "Min drag, downforce ≥ 120 N")]
THEMES = {  # dataviz reference palette: categorical slots 1-4 (validated), chart chrome per mode
    "light": dict(series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100"], surface="#fcfcfb", ink="#0b0b0b",
                  ink2="#52514e", muted="#898781", grid="#e1e0d9", axis="#c3c2b7"),
    "dark": dict(series=["#3987e5", "#d95926", "#199e70", "#c98500"], surface="#1a1a19", ink="#f0efec",
                 ink2="#c3c2b7", muted="#898781", grid="#2c2c2a", axis="#383835"),
}


def summary():
    d = json.load(open(ROOT / "demo" / "bench_wing.json"))
    out = {"sims_budget": d["sims_budget"], "repeats": d["repeats"], "generated_at": d["generated_at"], "goals": []}
    for gid, label in GOALS:
        g = d["goals"][gid]
        best = g["best_known"]
        rows = []
        for mid, name in METHODS:
            s = g["summary"][mid]
            v = s["median_final"]
            pct = 100.0 * (v / best if g["maximize"] else best / v)
            rows.append({"method": mid, "label": name, "median_final": round(v, 2), "pct_of_best": round(pct, 1),
                         "reached_95pct": s["reached_95pct"], "median_sims_to_95pct": s["median_sims_to_95pct"]})
        out["goals"].append({"goal": gid, "label": label, "metric": g["objective"], "unit": "N",
                             "best_known": round(best, 2), "rows": rows})
    return out


def plot(data, mode):
    t = THEMES[mode]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, axes = plt.subplots(1, 3, figsize=(16, 6.2), dpi=150, facecolor=t["surface"])
    fig.subplots_adjust(left=0.13, right=0.98, top=0.74, bottom=0.12, wspace=0.18)
    fig.text(0.01, 0.94, "Same 20-simulation budget: Darwin beats CMA-ES and random search on every goal", color=t["ink"],
             fontsize=19, fontweight="bold")
    fig.text(0.01, 0.885, "Median of %d runs per goal, as %% of the best design known for that goal. "
             "“n/3” = runs that reached 95%% of it." % data["repeats"], color=t["ink2"], fontsize=12)
    for ax, g in zip(axes, data["goals"]):
        ax.set_facecolor(t["surface"])
        ys = list(range(len(g["rows"])))[::-1]
        for y, row, color in zip(ys, g["rows"], t["series"]):
            ax.barh(y, row["pct_of_best"], height=0.62, color=color, edgecolor=t["surface"], linewidth=2)
            ax.text(row["pct_of_best"] + 1.2, y, "%.1f%%  ·  %d/3" % (row["pct_of_best"], row["reached_95pct"]),
                    va="center", ha="left", color=t["ink"], fontsize=11)
        ax.set_yticks(ys)
        ax.set_yticklabels([r["label"] for r in g["rows"]] if ax is axes[0] else [""] * len(ys), color=t["ink"],
                           fontsize=12)
        ax.set_xlim(0, 125)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.set_xticklabels(["0", "25", "50", "75", "100%"], color=t["muted"], fontsize=10)
        ax.grid(axis="x", color=t["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(t["axis"])
        ax.tick_params(length=0)
        ax.set_title(g["label"], loc="left", color=t["ink"], fontsize=13, fontweight="bold", pad=10)
    fig.text(0.01, 0.025, "Real rear_wing_v1 solver (AeroSandbox + NeuralFoil). Darwin planned with Claude Sonnet 5.5 "
             "(Sat Oct 24); CMA-ES and random search the same editable parameters.", color=t["muted"], fontsize=10)
    out = ROOT / "demo" / ("bench_wing_%s.png" % mode)
    fig.savefig(out, facecolor=t["surface"])
    plt.close(fig)
    return out


if __name__ == "__main__":
    data = summary()
    pub = ROOT / "dashboard" / "public" / "proof"
    pub.mkdir(parents=True, exist_ok=True)
    for mode in THEMES:
        shutil.copy2(plot(data, mode), pub)
    (pub / "bench_wing_summary.json").write_text(json.dumps(data, indent=1))
    print("wrote demo/bench_wing_{light,dark}.png and dashboard/public/proof/")
