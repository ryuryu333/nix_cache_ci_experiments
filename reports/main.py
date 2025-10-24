from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class BuildRow:
    run_id: str
    run_number: int
    job_name_raw: str
    job_name: str  # friendly: "marp_build" | "zenn_build"
    target: str  # marp | zenn
    tool: str  # none | cachix | cache-nix-action | magic-nix-cache
    phase: str  # generate-cache | use-cache | other
    duration_s: float


@dataclass
class AllowedEntry:
    """Represents a single analysis target run.

    Selection CSV lists run_id (and optional run_number, note). All build_* jobs
    within the listed runs are included in analysis.
    """
    run_id: str
    run_number: Optional[int] = None
    note: str = ""


# ジョブ名から target/tool/phase を抽出する正規表現
JOB_NAME_RE = re.compile(r"^build_(?P<target>[^_]+)_cachetool_(?P<tool>[^_]+)_phase_(?P<phase>.+)$")

TOOL_NORMALIZE = {
    "none": "none",
    "cachix-action": "cachix",
    "cache-nix-action": "cache-nix-action",
    "magic-nix-cache-action": "magic-nix-cache",
}


def read_csv(path: Path) -> List[dict]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def read_selection_csv(path: Optional[Path]) -> List[AllowedEntry]:
    rules: List[AllowedEntry] = []
    if not path:
        raise FileNotFoundError("--selection-csv is required for analysis")
    if not path.exists():
        raise FileNotFoundError(f"selection csv not found: {path}")
    rows = read_csv(path)
    for r in rows:
        run_id = (r.get("run_id") or "").strip('"')
        rn_s = (r.get("run_number") or r.get("run_no") or "").strip()
        note = (r.get("note") or r.get("reason") or "").strip()
        if not run_id:
            continue
        try:
            rn = int(rn_s) if rn_s else None
        except Exception:
            rn = None
        rules.append(AllowedEntry(run_id=run_id, run_number=rn, note=note))
    return rules


def make_selector(rules: List[AllowedEntry]):
    """Whitelist selector: include all build_* jobs for listed run_id(s)."""
    allowed_runs = {r.run_id for r in rules}

    def include(run_id: str, job_name_raw: str) -> bool:
        return run_id in allowed_runs

    return include


def parse_job(job_name: str) -> Optional[Tuple[str, str, str]]:
    m = JOB_NAME_RE.match(job_name)
    if not m:
        return None
    target = m.group("target")
    raw_tool = m.group("tool")
    phase = m.group("phase")
    tool = TOOL_NORMALIZE.get(raw_tool, raw_tool)
    return target, tool, phase


def map_run_number(run_rows: Iterable[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in run_rows:
        run_id = str(r.get("run_id") or r.get("id"))
        run_id = run_id.strip('"')
        rn = int(r.get("run_number") or 0)
        out[run_id] = rn
    return out


def load_build_rows(steps_csv: Path, runs_csv: Path, selector=None) -> List[BuildRow]:
    steps = read_csv(steps_csv)
    runs = read_csv(runs_csv)
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
        if duration <= 0:
            # 無効（skip/計測不能）の可能性が高いので除外
            continue
        run_id = r["run_id"].strip('"')
        run_number = rn_by_run.get(run_id)
        if run_number is None:
            continue
        job_name_raw = r.get("job_name", "")
        if selector and not selector(run_id, job_name_raw):
            continue
        parsed = parse_job(job_name_raw)
        if not parsed:
            # 現行ワークフロー以外のジョブは除外
            continue
        target, tool, phase = parsed
        job_name_friendly = f"{target}_build"
        rows.append(
            BuildRow(
                run_id=run_id,
                run_number=run_number,
                job_name_raw=job_name_raw,
                job_name=job_name_friendly,
                target=target,
                tool=tool,
                phase=phase,
                duration_s=duration,
            )
        )
    return rows

def group_cycle_index(rows: List[BuildRow]) -> Dict[Tuple[str, str, str], Dict[str, int]]:
    """各 (target, tool, phase) の組み合わせ内で run_number に基づき 1..N のサイクル番号を割り当てる。"""
    mapping: Dict[Tuple[str, str, str], Dict[str, int]] = {}
    bucket: Dict[Tuple[str, str, str], List[BuildRow]] = defaultdict(list)
    for r in rows:
        bucket[(r.target, r.tool, r.phase)].append(r)
    for key, lst in bucket.items():
        lst_sorted = sorted(lst, key=lambda x: x.run_number)
        mapping[key] = {r.run_id: i + 1 for i, r in enumerate(lst_sorted)}
    return mapping


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
        totals[(run_id, job_name)] = d
    return totals


def write_combined_csv(rows: List[BuildRow], job_totals: Dict[tuple, float], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_number", "job_name", "tool", "phase", "build_s", "job_total_s", "build_share", "run_id"])
        for r in sorted(rows, key=lambda x: (x.job_name, x.run_number, x.tool)):
            tot = job_totals.get((r.run_id, r.job_name_raw))
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

def plot_errorbars_job_totals(rows: List[BuildRow], job_totals: Dict[tuple, float], out_dir: Path) -> None:
    """Errorbar bars for job total duration (mean ± std) per tool/phase.

    Aggregates totals across cycles for each label using jobs.csv-derived totals.
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as e:
        print(f"matplotlib の読み込みに失敗しました: {e}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    order = _fixed_order_labels()

    def mean(xs: List[float]):
        return sum(xs) / len(xs) if xs else None

    def std(xs: List[float]):
        if len(xs) < 2:
            return 0.0 if xs else None
        m = mean(xs)
        return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5

    for job in sorted({r.job_name for r in rows}):
        jrows = [r for r in rows if r.job_name == job]
        labels = []
        means = []
        stds = []
        for ph, tool in order:
            totals = []
            for r in jrows:
                if r.phase == ph and r.tool == tool:
                    tot = job_totals.get((r.run_id, r.job_name_raw))
                    if isinstance(tot, float):
                        totals.append(tot)
            m = mean(totals)
            if m is None:
                continue
            labels.append(f"{tool}\n{ph}")
            means.append(m)
            stds.append(std(totals) or 0.0)
        if not means:
            continue
        x = np.arange(len(means))
        try:
            plt.figure(figsize=(10, 4))
            plt.bar(x, means, yerr=stds, capsize=4, color="#72B7B2", alpha=0.9)
            plt.title(f"{job} - Mean ± Std of job total (s)")
            plt.ylabel("seconds")
            plt.xticks(x, labels, rotation=30, ha="right")
            plt.tight_layout()
            plt.savefig(out_dir / f"errorbars_job_total_{job}.png", dpi=150)
            plt.close()
        except Exception as e:
            print(f"job total errorbars failed for {job}: {e}")


def _fixed_order_labels() -> List[tuple]:
    return [
        ("generate-cache", "none"),
        ("generate-cache", "cachix"), ("use-cache", "cachix"),
        ("generate-cache", "cache-nix-action"), ("use-cache", "cache-nix-action"),
        ("generate-cache", "magic-nix-cache"), ("use-cache", "magic-nix-cache"),
    ]


def plot_errorbars_means(rows: List[BuildRow], summary_csv: Path, out_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
        import csv as _csv
    except Exception as e:
        print(f"matplotlib の読み込みに失敗しました: {e}")
        return

    if not summary_csv.exists():
        return
    # Read summary to get mean/std per (job, tool, phase)
    data = {}
    with summary_csv.open() as f:
        rdr = _csv.DictReader(f)
        for r in rdr:
            job = r["job_name"]
            key = (job, r["tool"], r["phase"])
            try:
                mean = float(r["build_mean_s"]) if r["build_mean_s"] else None
                std = float(r["build_std_s"]) if r["build_std_s"] else None
            except ValueError:
                mean = std = None
            data[key] = (mean, std)

    out_dir.mkdir(parents=True, exist_ok=True)
    order = _fixed_order_labels()

    for job in sorted({r.job_name for r in rows}):
        labels = []
        means = []
        stds = []
        for ph, tool in order:
            m_s = data.get((job, tool, ph))
            if not m_s or m_s[0] is None:
                continue
            labels.append(f"{tool}\n{ph}")
            means.append(m_s[0])
            stds.append(m_s[1] or 0.0)
        if not means:
            continue
        import numpy as np
        x = np.arange(len(means))
        try:
            plt.figure(figsize=(10, 4))
            plt.bar(x, means, yerr=stds, capsize=4, color="#4C78A8", alpha=0.9)
            plt.title(f"{job} - Mean ± Std of Run nix build (s)")
            plt.ylabel("seconds")
            plt.xticks(x, labels, rotation=30, ha="right")
            plt.tight_layout()
            plt.savefig(out_dir / f"errorbars_build_{job}.png", dpi=150)
            plt.close()
        except Exception as e:
            print(f"errorbars plot failed for {job}: {e}")


def write_detail_csv(rows: List[BuildRow], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        idx_map = group_cycle_index(rows)
        w.writerow(["run_number", "job_name", "tool", "phase", "cycle_index", "duration_s", "run_id"])
        for r in sorted(rows, key=lambda x: (x.job_name, x.tool, x.phase, x.run_number)):
            cidx = idx_map.get((r.target, r.tool, r.phase), {}).get(r.run_id, "")
            w.writerow([r.run_number, r.job_name, r.tool, r.phase, cidx, f"{r.duration_s:.3f}", r.run_id])


def compute_baseline(rows: List[BuildRow], job_name: str) -> Optional[float]:
    # ベースラインは tool=none かつ phase=generate-cache の平均
    vals = [
        r.duration_s
        for r in rows
        if r.job_name == job_name and r.tool == "none" and r.phase == "generate-cache"
    ]
    if not vals:
        return None
    return sum(vals) / len(vals)


def write_speed_csv(rows: List[BuildRow], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["job_name", "tool", "phase", "run_number", "duration_s", "speedup_vs_baseline"])
        for job in sorted({r.job_name for r in rows}):
            base = compute_baseline(rows, job)
            for r in sorted([x for x in rows if x.job_name == job], key=lambda x: (x.run_number, x.tool, x.phase)):
                speed = (base / r.duration_s) if base and r.duration_s else None
                w.writerow([job, r.tool, r.phase, r.run_number, f"{r.duration_s:.3f}", f"{speed:.3f}" if speed else ""])


def write_summary_csv(rows: List[BuildRow], job_totals: Dict[tuple, float], out_csv: Path) -> None:
    from math import sqrt

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    grouped: Dict[Tuple[str, str, str], List[Tuple[float, Optional[float]]]] = defaultdict(list)
    for r in rows:
        tot = job_totals.get((r.run_id, r.job_name_raw))
        grouped[(r.job_name, r.tool, r.phase)].append((r.duration_s, tot))

    def mean(xs: List[float]) -> Optional[float]:
        return sum(xs) / len(xs) if xs else None

    def std(xs: List[float]) -> Optional[float]:
        if len(xs) < 2:
            return 0.0 if xs else None
        m = mean(xs)
        return sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "job_name", "tool", "phase", "n", "build_mean_s", "build_std_s", "job_total_mean_s", "build_share_mean",
        ])
        for key in sorted(grouped.keys()):
            vals = grouped[key]
            build_vals = [b for (b, _) in vals if isinstance(b, float)]
            total_vals = [t for (_, t) in vals if isinstance(t, float)]
            share_vals = [b / t for (b, t) in vals if isinstance(t, float) and t > 0]
            bm = mean(build_vals)
            bs = std(build_vals)
            tm = mean(total_vals)
            sm = mean(share_vals)
            w.writerow([
                key[0], key[1], key[2], len(vals),
                f"{bm:.3f}" if bm is not None else "",
                f"{bs:.3f}" if bs is not None else "",
                f"{tm:.3f}" if tm is not None else "",
                f"{sm:.3f}" if sm is not None else "",
            ])


def main():
    parser = argparse.ArgumentParser(description="Analyze GitHub Actions nix build durations for specific cache tools")
    base_dir = Path(__file__).parent
    # デフォルトの入力は actions_log/ 配下へ変更
    log_dir = base_dir / "actions_log"
    result_dir = base_dir / "my_result"
    # 入力は reports/actions_log 固定
    steps_p = log_dir / "actions_steps.csv"
    runs_p = log_dir / "actions_runs.csv"
    jobs_p = log_dir / "actions_jobs.csv"
    # 出力先は result/ 配下へ
    parser.add_argument("--out-detail", type=Path, default=result_dir / "detail.csv", help="Detailed rows CSV")
    parser.add_argument("--out-speed", type=Path, default=result_dir / "speedup.csv", help="Speedup CSV")
    parser.add_argument("--out-combined", type=Path, default=result_dir / "combined.csv", help="Combined build vs total CSV")
    parser.add_argument("--fig-dir", type=Path, default=result_dir / "figures", help="Output figures directory")
    parser.add_argument("--selection-csv", type=Path, default=log_dir / "selection.csv", help="Whitelist CSV. Columns: run_id[, run_number, note]")
    args = parser.parse_args()

    rules = read_selection_csv(args.selection_csv)
    selector = make_selector(rules)

    # Validate expected CSV locations under reports/actions_log
    missing = [p for p in [steps_p, runs_p, jobs_p, args.selection_csv] if not p.exists()]
    if missing:
        msg = ["Input CSV missing under reports/actions_log:"]
        for p in missing:
            msg.append(f" - {p}")
        msg.append("Place actions_runs.csv, actions_jobs.csv, actions_steps.csv, selection.csv in reports/actions_log.")
        msg.append("You can fetch them via: OWNER=<OWNER> REPO=<REPO> WORKFLOW=build.yml OUTDIR=reports/actions_log GH_TOKEN=$GH_TOKEN bash reports/actions_log/export_actions_csv.sh")
        raise FileNotFoundError("\n".join(msg))

    rows = load_build_rows(steps_p, runs_p, selector=selector)

    write_detail_csv(rows, args.out_detail)
    write_speed_csv(rows, args.out_speed)
    job_totals = load_job_totals(jobs_p, runs_p)
    write_combined_csv(rows, job_totals, args.out_combined)
    write_summary_csv(rows, job_totals, result_dir / "summary.csv")
    plot_errorbars_means(rows, result_dir / "summary.csv", args.fig_dir)
    plot_errorbars_job_totals(rows, job_totals, args.fig_dir)

    print(f"wrote: {args.out_detail}")
    print(f"wrote: {args.out_speed}")
    print(f"wrote: {args.out_combined}")
    print(f"wrote: {result_dir / 'summary.csv'}")
    print(f"figures: {args.fig_dir}/*.png")


if __name__ == "__main__":
    main()
