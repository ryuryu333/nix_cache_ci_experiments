from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass
class BuildRow:
    run_id: str
    run_number: int
    job_name: str
    tool: str  # none | cachix | cache-nix-action | magic-nix-cache | mixed
    phase: str  # baseline | first | second | other
    duration_s: float


# 検出ルール（ステップ名に含まれる文字列）
CACHE_KEYWORDS = {
    "magic-nix-cache": ["DeterminateSystems/magic-nix-cache-action"],
    "cachix": ["cachix/cachix-action"],
    "cache-nix-action": ["cache-nix-action"],
}


TARGET_RUNS = {2, 3, 4, 7, 8, 9, 10}
BASELINE_RUN = 2
TOOL_BY_RUN_NUMBER = {
    2: "none",
    3: "cachix",
    4: "cachix",
    7: "cache-nix-action",
    8: "cache-nix-action",
    9: "magic-nix-cache",
    10: "magic-nix-cache",
}


def read_csv(path: Path) -> List[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def map_run_cache(step_rows: Iterable[dict]) -> Dict[str, str]:
    flags: Dict[str, Dict[str, bool]] = defaultdict(lambda: defaultdict(bool))
    for r in step_rows:
        run_id = r["run_id"].strip('"')
        name = r.get("step_name", "")
        for tool, needles in CACHE_KEYWORDS.items():
            if any(n in name for n in needles):
                flags[run_id][tool] = True
    tools: Dict[str, str] = {}
    for run_id, d in flags.items():
        found = [k for k, v in d.items() if v]
        if not found:
            tools[run_id] = "none"
        elif len(found) == 1:
            tools[run_id] = found[0]
        else:
            tools[run_id] = "+".join(sorted(found))
    return tools


def map_run_number(run_rows: Iterable[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in run_rows:
        run_id = str(r.get("run_id") or r.get("id"))
        run_id = run_id.strip('"')
        rn = int(r.get("run_number") or 0)
        out[run_id] = rn
    return out


def phase_from_run_number(run_number: int) -> str:
    if run_number == BASELINE_RUN:
        return "baseline"
    if run_number in {3, 7, 9}:
        return "first"
    if run_number in {4, 8, 10}:
        return "second"
    return "other"


def load_build_rows(steps_csv: Path, runs_csv: Path) -> List[BuildRow]:
    steps = read_csv(steps_csv)
    runs = read_csv(runs_csv)
    tool_by_run = map_run_cache(steps)
    rn_by_run = map_run_number(runs)

    rows: List[BuildRow] = []
    for r in steps:
        if r.get("step_name") != "Run nix build":
            continue
        dur = r.get("duration_s")
        if not dur or dur == "null":
            continue
        try:
            duration = float(dur)
        except ValueError:
            continue
        run_id = r["run_id"].strip('"')
        run_number = rn_by_run.get(run_id)
        if run_number is None:
            continue
        detected = tool_by_run.get(run_id, "none")
        tool = TOOL_BY_RUN_NUMBER.get(run_number, detected)
        rows.append(
            BuildRow(
                run_id=run_id,
                run_number=run_number,
                job_name=r.get("job_name", ""),
                tool=tool,
                phase=phase_from_run_number(run_number),
                duration_s=duration,
            )
        )
    return rows


def filter_target(rows: List[BuildRow]) -> List[BuildRow]:
    return [r for r in rows if r.run_number in TARGET_RUNS]


def load_job_totals(jobs_csv: Path, runs_csv: Path) -> Dict[tuple, float]:
    """Return mapping (run_id, job_name) -> job total duration in seconds."""
    jobs = read_csv(jobs_csv)
    runs = read_csv(runs_csv)
    rn_by_run = map_run_number(runs)
    totals: Dict[tuple, float] = {}
    for j in jobs:
        run_id = str(j.get("run_id", "")).strip('"')
        job_name = j.get("job_name", "")
        dur = j.get("duration_s")
        try:
            d = float(dur) if dur not in (None, "", "null") else None
        except ValueError:
            d = None
        if not run_id or d is None:
            continue
        # Keep only target runs
        rn = rn_by_run.get(run_id)
        if rn not in TARGET_RUNS:
            continue
        totals[(run_id, job_name)] = d
    return totals


def write_combined_csv(rows: List[BuildRow], job_totals: Dict[tuple, float], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_number", "job_name", "tool", "phase", "build_s", "job_total_s", "build_share", "run_id"])
        for r in sorted(rows, key=lambda x: (x.job_name, x.run_number, x.tool)):
            tot = job_totals.get((r.run_id, r.job_name))
            share = (r.duration_s / tot) if (tot and tot > 0) else ""
            w.writerow([
                r.run_number,
                r.job_name,
                r.tool,
                r.phase,
                f"{r.duration_s:.3f}",
                (f"{tot:.3f}" if isinstance(tot, float) else ""),
                (f"{share:.3f}" if isinstance(share, float) else ""),
                r.run_id,
            ])


def plot_total_vs_build(rows: List[BuildRow], job_totals: Dict[tuple, float], out_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"matplotlib の読み込みに失敗しました: {e}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    order = [
        ("baseline", "none"),
        ("first", "cachix"), ("second", "cachix"),
        ("first", "cache-nix-action"), ("second", "cache-nix-action"),
        ("first", "magic-nix-cache"), ("second", "magic-nix-cache"),
    ]

    for job in sorted({r.job_name for r in rows}):
        jrows = [r for r in rows if r.job_name == job]
        labels: List[str] = []
        totals: List[float] = []
        builds: List[float] = []
        for ph, tool in order:
            match = [r for r in jrows if r.phase == ph and r.tool == tool]
            if not match:
                continue
            r = sorted(match, key=lambda x: x.run_number)[0]
            tot = job_totals.get((r.run_id, r.job_name))
            if tot is None:
                continue
            labels.append(f"{tool}\n{ph}")
            totals.append(tot)
            builds.append(r.duration_s)

        if not labels:
            continue

        import numpy as np
        x = np.arange(len(labels))
        width = 0.38

        plt.figure(figsize=(10, 4))
        b1 = plt.bar(x - width/2, totals, width, label="job total", color="#4C78A8")
        b2 = plt.bar(x + width/2, builds, width, label="build step", color="#F58518")
        plt.title(f"{job} - Job total vs Run nix build (s)")
        plt.ylabel("seconds")
        plt.xticks(x, labels, rotation=30, ha="right")
        plt.legend()
        for bars in (b1, b2):
            for b in bars:
                h = b.get_height()
                plt.text(b.get_x() + b.get_width()/2, h, f"{h:.1f}s", ha="center", va="bottom", fontsize=8)
        plt.tight_layout()
        plt.savefig(out_dir / f"total_vs_build_{job}.png", dpi=150)
        plt.close()


def plot_job_totals_only(rows: List[BuildRow], job_totals: Dict[tuple, float], out_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"matplotlib の読み込みに失敗しました: {e}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    order = [
        ("baseline", "none"),
        ("first", "cachix"), ("second", "cachix"),
        ("first", "cache-nix-action"), ("second", "cache-nix-action"),
        ("first", "magic-nix-cache"), ("second", "magic-nix-cache"),
    ]

    for job in sorted({r.job_name for r in rows}):
        jrows = [r for r in rows if r.job_name == job]
        labels: List[str] = []
        totals: List[float] = []
        for ph, tool in order:
            match = [r for r in jrows if r.phase == ph and r.tool == tool]
            if not match:
                continue
            r = sorted(match, key=lambda x: x.run_number)[0]
            tot = job_totals.get((r.run_id, r.job_name))
            if tot is None:
                continue
            labels.append(f"{tool}\n{ph}")
            totals.append(tot)

        if not labels:
            continue

        plt.figure(figsize=(9, 4))
        bars = plt.bar(range(len(totals)), totals, color="#4C78A8")
        plt.title(f"{job} - Job total duration (s)")
        plt.ylabel("seconds")
        plt.xticks(range(len(labels)), labels, rotation=30, ha="right")
        for i, b in enumerate(bars):
            h = b.get_height()
            plt.text(b.get_x() + b.get_width()/2, h, f"{h:.1f}s", ha="center", va="bottom", fontsize=8)
        plt.tight_layout()
        plt.savefig(out_dir / f"job_totals_{job}.png", dpi=150)
        plt.close()
def write_detail_csv(rows: List[BuildRow], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_number", "job_name", "tool", "phase", "duration_s", "run_id"])
        for r in sorted(rows, key=lambda x: (x.job_name, x.run_number, x.tool)):
            w.writerow([r.run_number, r.job_name, r.tool, r.phase, f"{r.duration_s:.3f}", r.run_id])


def compute_baseline(rows: List[BuildRow], job_name: str) -> Optional[float]:
    vals = [r.duration_s for r in rows if r.job_name == job_name and r.run_number == BASELINE_RUN]
    return vals[0] if vals else None


def write_speed_csv(rows: List[BuildRow], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["job_name", "tool", "phase", "run_number", "duration_s", "speedup_vs_baseline"])
        for job in sorted({r.job_name for r in rows}):
            base = compute_baseline(rows, job)
            for r in sorted([x for x in rows if x.job_name == job], key=lambda x: (x.run_number, x.tool)):
                speed = (base / r.duration_s) if base and r.duration_s else None
                w.writerow([job, r.tool, r.phase, r.run_number, f"{r.duration_s:.3f}", f"{speed:.3f}" if speed else ""])


def plot_charts(rows: List[BuildRow], out_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"matplotlib の読み込みに失敗しました: {e}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    # 並び順を固定
    order = [
        ("baseline", "none"),
        ("first", "cachix"), ("second", "cachix"),
        ("first", "cache-nix-action"), ("second", "cache-nix-action"),
        ("first", "magic-nix-cache"), ("second", "magic-nix-cache"),
    ]

    for job in sorted({r.job_name for r in rows}):
        jrows = [r for r in rows if r.job_name == job]
        base = compute_baseline(rows, job)

        labels = []
        durations = []
        speedups = []
        for ph, tool in order:
            match = [r for r in jrows if r.phase == ph and r.tool == tool]
            if not match:
                continue
            r = sorted(match, key=lambda x: x.run_number)[0]
            labels.append(f"{tool}\n{ph}")
            durations.append(r.duration_s)
            speedups.append((base / r.duration_s) if base else None)

        # Duration chart
        plt.figure(figsize=(9, 4))
        bars = plt.bar(range(len(durations)), durations, color="#4C78A8")
        plt.title(f"{job} - Run nix build duration (s)")
        plt.ylabel("seconds")
        plt.xticks(range(len(labels)), labels, rotation=30, ha="right")
        for i, b in enumerate(bars):
            h = b.get_height()
            plt.text(b.get_x() + b.get_width()/2, h, f"{h:.1f}s", ha="center", va="bottom", fontsize=8)
        plt.tight_layout()
        plt.savefig(out_dir / f"durations_{job}.png", dpi=150)
        plt.close()

        # Speedup chart
        if base:
            plt.figure(figsize=(9, 4))
            bars = plt.bar(range(len(speedups)), speedups, color="#72B7B2")
            plt.axhline(1.0, color="gray", linestyle="--", linewidth=1)
            plt.title(f"{job} - Speedup vs baseline (run {BASELINE_RUN})")
            plt.ylabel("x faster (baseline=1.0)")
            plt.xticks(range(len(labels)), labels, rotation=30, ha="right")
            for i, b in enumerate(bars):
                h = b.get_height()
                plt.text(b.get_x() + b.get_width()/2, h, f"{h:.2f}x", ha="center", va="bottom", fontsize=8)
            plt.tight_layout()
            plt.savefig(out_dir / f"speedup_{job}.png", dpi=150)
            plt.close()


def main():
    parser = argparse.ArgumentParser(description="Analyze GitHub Actions nix build durations for specific cache tools")
    base_dir = Path(__file__).parent
    # デフォルトの入力は actions_log/ 配下へ変更
    log_dir = base_dir / "actions_log"
    result_dir = base_dir / "my_result"
    parser.add_argument("--steps", type=Path, default=log_dir / "actions_steps.csv", help="Path to actions_steps.csv")
    parser.add_argument("--runs", type=Path, default=log_dir / "actions_runs.csv", help="Path to actions_runs.csv")
    parser.add_argument("--jobs", type=Path, default=log_dir / "actions_jobs.csv", help="Path to actions_jobs.csv")
    # 出力先は result/ 配下へ
    parser.add_argument("--out-detail", type=Path, default=result_dir / "detail.csv", help="Detailed rows CSV")
    parser.add_argument("--out-speed", type=Path, default=result_dir / "speedup.csv", help="Speedup CSV")
    parser.add_argument("--out-combined", type=Path, default=result_dir / "combined.csv", help="Combined build vs total CSV")
    parser.add_argument("--fig-dir", type=Path, default=result_dir / "figures", help="Output figures directory")
    args = parser.parse_args()

    rows = load_build_rows(args.steps, args.runs)
    rows = filter_target(rows)

    write_detail_csv(rows, args.out_detail)
    write_speed_csv(rows, args.out_speed)
    job_totals = load_job_totals(args.jobs, args.runs)
    write_combined_csv(rows, job_totals, args.out_combined)
    plot_charts(rows, args.fig_dir)
    plot_total_vs_build(rows, job_totals, args.fig_dir)
    plot_job_totals_only(rows, job_totals, args.fig_dir)

    print(f"wrote: {args.out_detail}")
    print(f"wrote: {args.out_speed}")
    print(f"wrote: {args.out_combined}")
    print(f"figures: {args.fig_dir}/*.png")


if __name__ == "__main__":
    main()
