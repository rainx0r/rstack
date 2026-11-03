"""Figure: <what this figure shows>.

x: <quantity>   y: <quantity>   colour: <grouping>

Run: uv run --with wandb <make-plot skill dir>/plotkit.py fig.py [--refresh] [--dark] [--transparent] [--title T] [--formats png html]
"""

import argparse
from pathlib import Path

import altair as alt
import plotkit as pk
import polars as pl

HERE = Path(__file__).resolve().parent
NAME = Path(__file__).stem

CONDITIONS: dict[str, str] = {
    "Ours": "<wandb group>",
    "Baseline": "<wandb group>",
}
PROJECT = "<entity>/<project>"
# Every metric this figure might plot for caching purposes
METRICS = ["charts/mean_success_rate"]
METRIC = METRICS[0]


def fetch(refresh: bool) -> pl.DataFrame:
    cache = HERE / f"{NAME}.parquet"
    if cache.exists() and not refresh:
        return pl.read_parquet(cache)
    import wandb

    api = wandb.Api()
    rows = []
    for name, group in CONDITIONS.items():
        for run in api.runs(PROJECT, filters={"group": group, "state": "finished"}):
            hist = run.history(keys=[*METRICS, "_step"], samples=2000, pandas=False)
            seed = run.config.get("seed", run.id)
            for r in hist:
                for m in METRICS:
                    if r.get(m) is not None:
                        rows.append(
                            {
                                "condition": name,
                                "group": group,
                                "run_id": run.id,
                                "run_name": run.name,
                                "seed": seed,
                                "step": r["_step"],
                                "metric": m,
                                "value": r[m],
                            }
                        )
    df = pl.DataFrame(rows)
    df.write_parquet(cache)
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="refetch from wandb instead of using the cache",
    )
    ap.add_argument("--dark", action="store_true", help="dark theme")
    ap.add_argument("--transparent", action="store_true", help="no background fill")
    ap.add_argument("--title", default=None, help="plot title (none by default)")
    ap.add_argument(
        "--formats",
        nargs="+",
        default=["png"],
        help="png (default), svg, pdf, html, json",
    )
    args = ap.parse_args()

    pk.enable(theme="dark" if args.dark else "light", transparent=args.transparent)
    df = fetch(args.refresh).filter(pl.col("metric") == METRIC)

    df, _ = pk.ema(df, x="step", y="value", seed="seed", by="condition")
    agg = pk.aggregate(df, x="step", y="value", seed="seed", by="condition")

    chart = pk.curves(
        agg,
        x="step",
        group="condition",
        order=list(CONDITIONS),
        title=args.title,
        x_title="Number of environment steps",
        y_title="Success rate",
        legend_title="Algorithm",
        legend_orient="bottom-right",
        y_scale=alt.Scale(domain=[0, 1]),
        y_axis=pk.percent_axis(),
    )
    # chart = chart + pk.reference(0.85, "Published SOTA")

    for p in pk.save(chart, HERE / NAME, formats=args.formats):
        print(p)


if __name__ == "__main__":
    main()
