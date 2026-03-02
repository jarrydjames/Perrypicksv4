"""Diagnostics: explain winner accuracy drop from holdout -> future.

Reads:
- Maximus/artifacts/HOLDOUT_PREDICTIONS.csv
- Maximus/artifacts/FUTURE_PREDICTIONS.csv

Writes:
- Maximus/reports/WINNER_DIAGNOSTICS.md

This does NOT change the model. It only analyzes prediction behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from Maximus.src.eval.decision import DecisionPolicy, win_acc_with_abstain
from Maximus.src.paths import artifacts_dir, reports_dir


BINS = [0, 1, 2, 3, 5, 7, 10, 15, 25, 1e9]


def _load_preds(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    # only evaluate margin predictions
    df = df[(df["target"] == "margin") & (df["model"] == "catboost")].copy()
    df["abs_pred"] = df["y_pred"].abs()
    return df


def _bin_table(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for lo, hi in zip(BINS[:-1], BINS[1:]):
        m = (df["abs_pred"] >= lo) & (df["abs_pred"] < hi)
        if m.sum() == 0:
            continue
        y = df.loc[m, "y_true"].to_numpy(float)
        p = df.loc[m, "y_pred"].to_numpy(float)
        met = win_acc_with_abstain(y, p, DecisionPolicy(threshold=0.0))
        out.append(
            {
                "bin": f"[{lo},{hi})",
                "n": int(m.sum()),
                "win_acc": met["win_acc"],
                "mean_abs_pred": float(df.loc[m, "abs_pred"].mean()),
                "mean_true_margin": float(y.mean()),
            }
        )
    return pd.DataFrame(out)


def _threshold_sweep(df: pd.DataFrame) -> pd.DataFrame:
    y = df["y_true"].to_numpy(float)
    p = df["y_pred"].to_numpy(float)

    rows = []
    for t in [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7, 10]:
        met = win_acc_with_abstain(y, p, DecisionPolicy(threshold=float(t)))
        rows.append({"threshold": float(t), "win_acc": met["win_acc"], "coverage": met["coverage"]})
    return pd.DataFrame(rows)


def main() -> int:
    reports_dir().mkdir(parents=True, exist_ok=True)

    hold_path = artifacts_dir() / "HOLDOUT_PREDICTIONS.csv"
    fut_path = artifacts_dir() / "FUTURE_PREDICTIONS.csv"

    if not hold_path.exists() or not fut_path.exists():
        raise FileNotFoundError("Missing HOLDOUT_PREDICTIONS.csv or FUTURE_PREDICTIONS.csv")

    hold = _load_preds(hold_path)
    fut = _load_preds(fut_path)

    # headline metrics (forced picks)
    hold_forced = win_acc_with_abstain(hold["y_true"], hold["y_pred"], DecisionPolicy(threshold=0.0))
    fut_forced = win_acc_with_abstain(fut["y_true"], fut["y_pred"], DecisionPolicy(threshold=0.0))

    hold_bins = _bin_table(hold)
    fut_bins = _bin_table(fut)

    hold_thr = _threshold_sweep(hold)
    fut_thr = _threshold_sweep(fut)

    out_path = reports_dir() / "WINNER_DIAGNOSTICS.md"

    lines = [
        "# Winner Accuracy Diagnostics (Maximus)",
        "",
        "Analyzes why win accuracy drops from holdout to future block.",
        "",
        "## Headline (CatBoost margin)",
        f"- Holdout forced-pick win_acc: {hold_forced['win_acc']*100:.2f}%",
        f"- Future forced-pick win_acc: {fut_forced['win_acc']*100:.2f}%",
        f"- Drop (pp): {(hold_forced['win_acc']-fut_forced['win_acc'])*100:.2f}",
        "",
        "## Win accuracy by |pred_margin| bin (holdout)",
        "```",
        hold_bins.to_string(index=False),
        "```",
        "",
        "## Win accuracy by |pred_margin| bin (future)",
        "```",
        fut_bins.to_string(index=False),
        "```",
        "",
        "## Threshold sweep (abstention) — holdout",
        "```",
        hold_thr.to_string(index=False),
        "```",
        "",
        "## Threshold sweep (abstention) — future",
        "```",
        fut_thr.to_string(index=False),
        "```",
        "",
        "## Interpretation guide",
        "- If future drop is concentrated in low-|pred| bins, a confidence threshold may fix it.",
        "- If drop persists at high-|pred| bins, it’s likely real drift / feature weakness.",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
