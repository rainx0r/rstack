# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "altair>=5.5",
#     "vl-convert-python>=1.9",
#     "polars>=1.0",
#     "numpy",
#     "scipy",
# ]
# ///
"""rstack plotkit: house style for Altair figures of experiment results.

Run from the make-plot skill; do not copy into projects.
Usage:

    uv run <skill_dir>/plotkit.py fig.py [args...]
    uv run --with wandb <skill_dir>/plotkit.py fig.py      # extra deps via --with

Inside the figure script:

    import plotkit as pk
    pk.enable()                      # or pk.enable(theme="dark", transparent=True)
    df, _ = pk.ema(df, x="step", y="return", seed="seed", by="algo")
    agg = pk.aggregate(df, x="step", y="return", seed="seed", by="algo")
    chart = pk.curves(agg, x="step", group="algo", order=["Ours", "PPO"],
                      x_title="Number of environment steps", y_title="Episode return")
    pk.save(chart, "out/learning_curves")        # -> out/learning_curves.png
"""

from __future__ import annotations

import base64
import itertools
import json
import os
import re
import sys
import urllib.request
import warnings
from pathlib import Path
from typing import Iterable, Literal, Sequence

import altair as alt
import numpy as np
import polars as pl
import scipy.stats
import vl_convert as vlc

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

# 100 = lightest, 900 = darkest. Main result is primary 500, other conditions start at 600.
COLORS: dict[str, dict[int, str]] = {
    "grey": {
        100: "#F8FBFC",
        200: "#E8F0F3",
        300: "#D9E5E8",
        400: "#C2D2D6",
        500: "#9DB4BB",
        600: "#5C808A",
        700: "#3F6069",
        800: "#29454C",
        900: "#172F36",
    },
    "primary": {  # blue
        100: "#EBFFFF",
        200: "#D6FEFF",
        300: "#A8F8FF",
        400: "#66E5FF",
        500: "#00C2FF",
        600: "#00A1FF",
        700: "#0081CC",
        800: "#005999",
        900: "#00264D",
    },
    "accent": {  # yellow -> orange
        100: "#FFFFE5",
        200: "#FFFFB2",
        300: "#FFFF8F",
        400: "#FFFA66",
        500: "#FFEA00",
        600: "#FFBF00",
        700: "#E57A00",
        800: "#C77100",
        900: "#803500",
    },
    "support 1": {  # green
        100: "#EBFFFA",
        200: "#D6FFF8",
        300: "#A3FFF0",
        400: "#66FFDE",
        500: "#00FFBF",
        600: "#00DB8B",
        700: "#00B271",
        800: "#00804F",
        900: "#004D2D",
    },
    "support 2": {  # pink -> crimson
        100: "#FFE5F4",
        200: "#FFB2CC",
        300: "#FF80BB",
        400: "#FF3D9E",
        500: "#FF006A",
        600: "#F50052",
        700: "#CC0044",
        800: "#B2002D",
        900: "#800015",
    },
    "red": {
        100: "#FFF1EB",
        200: "#FFC8B2",
        300: "#FF8F70",
        400: "#FF5F33",
        500: "#FF1E00",
        600: "#E00F00",
        700: "#B20900",
        800: "#7A0800",
        900: "#4D0400",
    },
}

# LaTeX size names (px)
FONT_SIZES = {
    "tiny": 6,
    "scriptsize": 8,
    "footnotesize": 10,
    "small": 12,
    "normalsize": 14,
    "large": 16,
    "Large": 20,
    "LARGE": 22,
    "huge": 28,
    "Huge": 32,
}
TEXT = {
    "figure_title": FONT_SIZES["huge"],
    "title": FONT_SIZES["LARGE"],
    "axis_title": FONT_SIZES["Large"],
    "axis_label": FONT_SIZES["large"],
    "legend_title": FONT_SIZES["Large"],
    "legend_label": FONT_SIZES["large"],
    "annotation": FONT_SIZES["normalsize"],
}

SIZES = {
    "default": (600, 400),
    "wide": (900, 360),
    "square": (400, 400),
    "panel": (400, 300),
}

OURS = COLORS["primary"][500]  # main result

# Theme-dependent roles
THEMES: dict[str, dict] = {
    "light": {
        "background": "white",
        "ink": "#000000",
        "grid": COLORS["grey"][300],
        "domain": COLORS["grey"][800],
        "legend_fill": "rgba(255,255,255,0.85)",
        "legend_stroke": COLORS["grey"][400],
        "baseline": COLORS["grey"][600],
        "reference": COLORS["grey"][600],
        "band_opacity": 0.2,
    },
    "dark": {
        "background": "#020304",
        "ink": COLORS["grey"][100],
        "grid": COLORS["grey"][800],
        "domain": COLORS["grey"][500],
        "legend_fill": "rgba(2,3,4,0.8)",
        "legend_stroke": COLORS["grey"][700],
        "baseline": COLORS["grey"][500],
        "reference": COLORS["grey"][500],
        "band_opacity": 0.3,
    },
}
BASELINE = THEMES["light"]["baseline"]  # for a single baseline / control
REFERENCE = THEMES["light"]["reference"]
GRID = THEMES["light"]["grid"]
INK = THEMES["light"]["ink"]

# Categorical order for 3+ conditions. Hues
# alternate so legend neighbours are far apart.
CATEGORICAL = [
    COLORS["primary"][500],
    COLORS["support 2"][600],
    COLORS["support 1"][600],
    COLORS["accent"][600],
    COLORS["red"][600],
    COLORS["grey"][600],
    COLORS["primary"][800],
    COLORS["support 2"][800],
]
SHAPES = [
    "circle",
    "triangle-down",
    "square",
    "diamond",
    "cross",
    "triangle-up",
    "triangle-right",
    "triangle-left",
]
DASHES = [[1, 0], [6, 3], [2, 2], [8, 3, 2, 3], [4, 4], [1, 3]]
_SEQ_STOPS = [600, 700, 800, 900]
_SEQ_MAX_LEVELS = 6

# Statistics / smoothing policy
IQM_MIN_SEEDS = 5  # >= this many seeds -> IQM + IQR, else mean + 95% CI
SMOOTH_MIN_POINTS = 100  # curves with fewer logged points are never smoothed
SPARSE_MAX_POINTS = 30  # curves with at most this many points get markers
SMOOTH_SPAN_FRAC = 1 / 20  # EMA span = this fraction of points per curve


def categorical(n: int) -> list[str]:
    if n == 2:
        return [OURS, BASELINE]
    if n > len(CATEGORICAL):
        raise ValueError(
            f"{n} categories > {len(CATEGORICAL)} colours; facet or merge instead"
        )
    return CATEGORICAL[:n]


def sequential(n: int) -> list[str]:
    if n > _SEQ_MAX_LEVELS:
        raise ValueError(
            f"{n} levels > {_SEQ_MAX_LEVELS} shades; use a continuous scale"
        )
    if n == 1:
        return [OURS]
    stops = [COLORS["primary"][s].lstrip("#") for s in _SEQ_STOPS]
    channels = [[int(h[i : i + 2], 16) for h in stops] for i in (0, 2, 4)]
    positions = np.linspace(0, len(stops) - 1, n)
    mixed = [np.interp(positions, range(len(stops)), ch) for ch in channels]
    return [
        "#" + "".join(f"{round(float(ch[i])):02X}" for ch in mixed) for i in range(n)
    ]


def color_scale(
    domain: Sequence,
    range_: Sequence[str] | None = None,
    kind: Literal["categorical", "sequential"] = "categorical",
) -> alt.Scale:
    domain = list(domain)
    if range_ is None:
        range_ = (
            categorical(len(domain))
            if kind == "categorical"
            else sequential(len(domain))
        )
    return alt.Scale(domain=domain, range=list(range_))


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

FONT = {
    "family": "Times New Roman",
    "substitute": {"family": "Tinos", "fontsource": "tinos"},
    "fallback": "Tinos, Times, serif",
}
_WEIGHTS = (400, 700)
_FONT_DIRS = [
    "/System/Library/Fonts",
    "/Library/Fonts",
    "~/Library/Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/.local/share/fonts",
    "~/.fonts",
]
_CACHE = (
    Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "rstack" / "fonts"
)

_state: dict = {"theme": "light", "family": None, "embed": []}


def _system_has(family: str) -> bool:
    key = family.replace(" ", "").lower()
    for d in _FONT_DIRS:
        p = Path(d).expanduser()
        if p.is_dir() and any(
            key in f.name.replace(" ", "").lower()
            for f in p.rglob("*")
            if f.suffix.lower() in {".ttf", ".otf", ".ttc"}
        ):
            return True
    return False


def _fetch(fontsource_id: str) -> list[tuple[int, Path]]:
    """Download (once) latin TTFs for the given Fontsource id. Returns [(weight, path)]."""
    out = []
    d = _CACHE / fontsource_id
    for w in _WEIGHTS:
        p = d / f"{fontsource_id}-latin-{w}-normal.ttf"
        if not p.exists():
            d.mkdir(parents=True, exist_ok=True)
            url = f"https://cdn.jsdelivr.net/fontsource/fonts/{fontsource_id}@latest/latin-{w}-normal.ttf"
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    p.write_bytes(r.read())
            except Exception as e:  # offline etc.
                warnings.warn(f"could not fetch font {fontsource_id} {w}: {e}")
                continue
        out.append((w, p))
    return out


def _setup_font() -> str:
    family, files = FONT["family"], []
    if not _system_has(family):
        sub = FONT["substitute"]
        family, files = sub["family"], _fetch(sub["fontsource"])
    if files:
        vlc.register_font_directory(str(files[0][1].parent))
    _state.update(family=family, embed=[(family, w, p) for w, p in files])
    return f'"{family}", {FONT["fallback"]}'


def _font_face_css() -> str:
    rules = []
    for family, w, p in _state["embed"]:
        b64 = base64.b64encode(p.read_bytes()).decode()
        rules.append(
            f'@font-face{{font-family:"{family}";font-weight:{w};'
            f'src:url(data:font/ttf;base64,{b64}) format("truetype");}}'
        )
    return "".join(rules)


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

Theme = Literal["light", "dark"]


def _theme(font: str, t: dict, background: str) -> dict:
    ink = t["ink"]
    return {
        "config": {
            "background": background,
            "font": font,
            "padding": 8,
            "view": {
                "stroke": None,
                "continuousWidth": SIZES["default"][0],
                "continuousHeight": SIZES["default"][1],
            },
            "title": {
                "font": font,
                "fontSize": TEXT["title"],
                "color": ink,
                "anchor": "start",
                "fontWeight": "normal",
            },
            "axis": {
                "labelFont": font,
                "titleFont": font,
                "labelFontSize": TEXT["axis_label"],
                "titleFontSize": TEXT["axis_title"],
                "labelColor": ink,
                "titleColor": ink,
                "titleFontWeight": "normal",
                "titlePadding": 10,
                "labelPadding": 4,
                "domainColor": t["domain"],
                "tickColor": t["domain"],
                "tickSize": 4,
                "labelFlush": True,
                "grid": True,
                "gridColor": t["grid"],
                "gridWidth": 0.8,
                "tickCount": 5,
                "labelOverlap": "greedy",
            },
            "axisX": {"labelAngle": 0},
            "legend": {
                "labelFont": font,
                "titleFont": font,
                "labelFontSize": TEXT["legend_label"],
                "titleFontSize": TEXT["legend_title"],
                "labelColor": ink,
                "titleColor": ink,
                "titleFontWeight": "normal",
                "symbolOpacity": 1.0,
                "symbolSize": 120,
                "symbolStrokeWidth": 3,
                "orient": "bottom-right",
                "offset": 8,
                "padding": 6,
                "cornerRadius": 2,
                "fillColor": t["legend_fill"],
                "strokeColor": t["legend_stroke"],
                "rowPadding": 2,
            },
            "header": {
                "labelFont": font,
                "titleFont": font,
                "labelFontSize": TEXT["axis_title"],
                "titleFontSize": TEXT["axis_title"],
                "labelColor": ink,
                "titleColor": ink,
            },
            "line": {"strokeWidth": 2.5},
            "point": {"size": 70, "filled": True},
            "area": {"opacity": t["band_opacity"]},
            "rule": {"color": t["reference"], "strokeWidth": 1.5},
            "text": {"font": font, "fontSize": TEXT["annotation"], "color": ink},
            "range": {"category": CATEGORICAL},
        }
    }


def enable(theme: Theme = "light", transparent: bool = False) -> None:
    """Call once at the top of every figure script."""
    global BASELINE, REFERENCE, GRID, INK
    t = THEMES[theme]
    BASELINE, REFERENCE, GRID, INK = t["baseline"], t["reference"], t["grid"], t["ink"]
    font = _setup_font()
    _state.update(theme=theme)
    background = "transparent" if transparent else t["background"]
    alt.theme.register("rstack", enable=True)(lambda: _theme(font, t, background))


# Axis helpers ---------------------------------------------------------------

SI_LABEL_EXPR = (
    "abs(datum.value) >= 1e9 ? format(datum.value / 1e9, '.3~f') + 'B' : "
    "abs(datum.value) >= 1e6 ? format(datum.value / 1e6, '.3~f') + 'M' : "
    "abs(datum.value) >= 1e3 ? format(datum.value / 1e3, '.3~f') + 'K' : "
    "format(datum.value, '.3~f')"
)


def si_axis(**kwargs) -> alt.Axis:
    """Axis with K/M/B tick labels (steps, parameters, FLOPs)."""
    return alt.Axis(labelExpr=SI_LABEL_EXPR, **kwargs)


def percent_axis(**kwargs) -> alt.Axis:
    """Axis for a 0-1 quantity shown as percent."""
    return alt.Axis(format=".0%", **kwargs)


def log_ticks(
    lo: float, hi: float, mantissas: Iterable[int] = (1, 2, 5)
) -> list[float]:
    """1-2-5 ticks per decade within [lo, hi] for log axes."""
    out = []
    for e in range(int(np.floor(np.log10(lo))), int(np.ceil(np.log10(hi))) + 1):
        for m in mantissas:
            v = m * 10.0**e
            if lo <= v <= hi:
                out.append(v)
    return out


_TICK_TAG = "rstack-ticks"  # axis description marker; pk.figure uses it to align x ends


def nice_ticks(
    lo: float, hi: float, width: float, min_labels: int = 5, max_labels: int = 10
) -> tuple[tuple[float, float], list[float], list[float]]:
    """Domain, all tick values, and labelled tick values for a linear axis.

    The domain ends exactly at the data max (hi), which is always a labelled tick
    (e.g. 18.7M). Other labels sit on a 1-2-2.5-5 step from the start; one too close to
    the end is dropped in its favour. As many labels as fit at ~100 px each, clamped to
    [min_labels, max_labels]. One unlabelled tick sits between neighbouring labels.
    """
    n_max = int(np.clip(round(width / 100), min_labels, max_labels))
    span = hi - lo if hi > lo else (abs(hi) or 1.0)
    e0 = int(np.floor(np.log10(span))) - 2
    steps = sorted(m * 10.0**e for e in range(e0, e0 + 5) for m in (1, 2, 2.5, 5))
    for step in steps:
        start = float(np.floor(lo / step + 1e-9) * step)
        majors = [
            start + i * step
            for i in range(int(np.floor((hi - start) / step + 1e-9)) + 1)
        ]
        if hi - majors[-1] > 1e-9 * step:  # data doesn't end on a step
            if (hi - majors[-1]) / (hi - start) * width < 70:  # labels would crowd
                majors.pop()
            majors.append(hi)
        if len(majors) <= n_max:
            break
    majors = [float(round(v, 12)) for v in majors]
    minors = [(a + b) / 2 for a, b in zip(majors, majors[1:]) if b - a > 0.75 * step]
    values = sorted({*majors, *(float(round(v, 12)) for v in minors)})
    return (start, float(hi)), values, majors


def linear_axis(
    lo: float, hi: float, width: float, fmt: Literal["si", "percent", "number"] = "si"
) -> tuple[alt.Scale, alt.Axis]:
    """Scale + axis for a linear x (or y) per nice_ticks: domain from the start tick to
    exactly the data max, labelled ticks (the end always labelled), shorter unlabelled
    ticks in between. Used by default for x in curves()/points()."""
    (start, end), values, majors = nice_ticks(lo, hi, width)
    major = f"indexof({json.dumps(majors)}, datum.value) >= 0"
    label = {
        "si": SI_LABEL_EXPR,
        "percent": "format(datum.value, '.0%')",
        "number": "format(datum.value, '.3~f')",
    }[fmt]
    axis = alt.Axis(
        values=values,
        tickCount=len(
            values
        ),  # else Vega thins explicit values down to the theme's count
        labelExpr=f"{major} ? ({label}) : ''",
        tickSize={"condition": {"test": major, "value": 5}, "value": 3},
        gridOpacity={"condition": {"test": major, "value": 1}, "value": 0.45},
        description=f"{_TICK_TAG}:{fmt}",
    )
    return alt.Scale(domain=[start, end], nice=False, zero=False), axis


def log_axis(
    lo: float, hi: float, width: float = SIZES["default"][0]
) -> tuple[alt.Scale, alt.Axis]:
    """Scale + axis for a log x: domain exactly [data min, data max], both ends labelled,
    1-2-5 ticks in between (powers of ten only if that's over 8 labels). Interior ticks
    closer than ~70 px to an end are dropped so labels don't collide."""
    inner = log_ticks(lo, hi)
    if len(inner) > 8:
        inner = log_ticks(lo, hi, mantissas=(1,))
    px_per_decade = width / max(np.log10(hi / lo), 1e-9)
    gap = 70 / px_per_decade
    inner = [t for t in inner if np.log10(t / lo) > gap and np.log10(hi / t) > gap]
    values = [float(lo), *inner, float(hi)]
    return alt.Scale(type="log", domain=[lo, hi], nice=False), si_axis(
        values=values, tickCount=len(values)
    )


# ---------------------------------------------------------------------------
# Data shaping and statistics
# ---------------------------------------------------------------------------


def _as_list(by) -> list[str]:
    if by is None:
        return []
    return [by] if isinstance(by, str) else list(by)


def is_aligned(
    df: pl.DataFrame, *, x: str, seed: str, by=None, tol: float = 0.9
) -> bool:
    """True if, within each group, (nearly) every x value is logged by every seed."""
    keys = _as_list(by)
    g = keys or [pl.lit(0).alias("_g")]
    per_x = df.group_by([*g, x]).agg(pl.col(seed).n_unique().alias("k"))
    n = df.group_by(g).agg(pl.col(seed).n_unique().alias("n"))
    j = (
        per_x.join(n, on=keys or "_g")
        if keys
        else per_x.with_columns(n=pl.lit(n["n"][0]))
    )
    return (j["k"] == j["n"]).mean() >= tol


def align(
    df: pl.DataFrame, *, x: str, y: str, seed: str, by=None, n_points: int | None = None
) -> pl.DataFrame:
    """Linearly interpolate each seed's curve onto a shared x grid per group.

    Per-x aggregation needs every seed to have a value at the same x. wandb's
    history(samples=N) subsamples each run independently, so seeds rarely share
    steps; aggregate() detects this and calls align() automatically. The grid spans
    the x range covered by every seed in the group (no extrapolation), with
    n_points (default: median points per seed) evenly spaced values.
    """
    groups = _as_list(by)
    parts = []
    for gkey, g in df.group_by(groups, maintain_order=True) if groups else [((), df)]:
        curves = [(s, c.sort(x)) for (s,), c in g.group_by([seed], maintain_order=True)]
        lo = max(c[x].min() for _, c in curves)
        hi = min(c[x].max() for _, c in curves)
        n = n_points or int(np.median([c.height for _, c in curves]))
        grid = np.linspace(lo, hi, max(n, 2))
        for s, c in curves:
            vals = np.interp(grid, c[x].to_numpy(), c[y].to_numpy())
            part = pl.DataFrame({seed: [s] * len(grid), x: grid, y: vals})
            for k, v in zip(groups, gkey):
                part = part.with_columns(pl.lit(v).alias(k))
            parts.append(part)
    return pl.concat(parts, how="diagonal").select([*groups, seed, x, y])


def smoothing_span(n_points: int) -> int | None:
    """EMA span for a curve with n_points values, or None if it should not be smoothed."""
    if n_points < SMOOTH_MIN_POINTS:
        return None
    return max(5, round(n_points * SMOOTH_SPAN_FRAC))


def ema(
    df: pl.DataFrame,
    *,
    x: str,
    y: str,
    seed: str,
    by=None,
    span: int | Literal["auto"] | None = "auto",
) -> tuple[pl.DataFrame, int | None]:
    """Debiased EMA per (group, seed) curve, applied BEFORE aggregating over seeds.

    Returns (df, span_used). span="auto" applies the threshold rule; None disables.
    """
    keys = _as_list(by) + [seed]
    if span == "auto":
        span = smoothing_span(int(df.group_by(keys).len()["len"].median()))
    if span is None:
        return df, None
    out = df.sort(x, maintain_order=True).with_columns(
        pl.col(y).ewm_mean(span=span, adjust=True).over(keys).alias(y)
    )
    return out, span


Stat = Literal["auto", "mean", "iqm"]


def _summ(values: np.ndarray, stat: str) -> tuple[float, float, float]:
    v = values[~np.isnan(values)]
    n = len(v)
    if n == 0:
        return (np.nan, np.nan, np.nan)
    if stat == "iqm":
        c = float(scipy.stats.trim_mean(v, 0.25)) if n >= 4 else float(np.mean(v))
        lo, hi = np.quantile(v, [0.25, 0.75])
        return c, float(lo), float(hi)
    m = float(np.mean(v))
    if n < 2:
        return m, m, m
    h = float(scipy.stats.sem(v) * scipy.stats.t.ppf(0.975, n - 1))
    return m, m - h, m + h


def aggregate(
    df: pl.DataFrame,
    *,
    y: str,
    seed: str,
    x: str | None = None,
    by=None,
    stat: Stat = "auto",
) -> pl.DataFrame:
    """Aggregate over seeds -> columns [*by, x?, center, lo, hi, n_seeds, stat].

    stat="auto" picks ONE statistic for the whole figure from the smallest seed count:
    >= IQM_MIN_SEEDS -> IQM with IQR band, else mean with 95% t-interval band.
    With one seed, lo == hi == center (no band). x=None for one-value-per-seed summaries.
    If seeds don't share x values, they are aligned onto a common grid first.
    """
    if x is not None and not is_aligned(df, x=x, seed=seed, by=by):
        df = align(df, x=x, y=y, seed=seed, by=by)
    keys = _as_list(by) + ([x] if x else [])
    counts = df.group_by(_as_list(by) or [pl.lit(0)]).agg(pl.col(seed).n_unique())[seed]
    if counts.min() != counts.max():
        warnings.warn(
            f"unequal seed counts across groups ({counts.min()}..{counts.max()})"
        )
    if stat == "auto":
        stat = "iqm" if counts.min() >= IQM_MIN_SEEDS else "mean"

    grouped = df.group_by(keys, maintain_order=True).agg(
        pl.col(y).alias("_v"), pl.col(seed).n_unique().alias("n_seeds")
    )
    rows = [_summ(np.asarray(v, dtype=float), stat) for v in grouped["_v"].to_list()]
    c, lo, hi = (list(t) for t in zip(*rows)) if rows else ([], [], [])
    out = grouped.drop("_v").with_columns(
        center=pl.Series(c, dtype=pl.Float64),
        lo=pl.Series(lo, dtype=pl.Float64),
        hi=pl.Series(hi, dtype=pl.Float64),
        stat=pl.lit(stat),
    )
    return out.sort(x, maintain_order=True) if x else out


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------


def _domain(agg: pl.DataFrame, group: str, order, colors) -> list:
    """Legend/colour order: order > colors dict order > first appearance in data."""
    if order is not None:
        return list(order)
    if colors:
        return list(colors)
    return agg[group].unique(maintain_order=True).to_list()


def _with_title(chart, text: str | None, kind: Literal["plot", "figure"] = "plot"):
    return chart.properties(title=_title(text, kind)) if text else chart


def _title(text: str, kind: Literal["plot", "figure"] = "plot") -> alt.TitleParams:
    if kind == "figure":
        return alt.TitleParams(
            text=text, anchor="middle", fontSize=TEXT["figure_title"], offset=12
        )
    return alt.TitleParams(text=text, anchor="start", fontSize=TEXT["title"], offset=10)


_ids = itertools.count()


def _hover(
    agg: pl.DataFrame,
    *,
    x: str,
    group: str | None,
    domain: list,
    x_title: str,
    y_title: str,
    enc_x: alt.X,
    ys: alt.Scale,
    base: alt.Chart,
) -> list:
    """Hover layers for HTML: vertical rule + dots at the nearest x, tooltip with every
    group's value. Invisible in static exports."""
    sel = alt.selection_point(
        name=f"hover_{next(_ids)}",
        fields=[x],
        nearest=True,
        on="pointerover",
        empty=False,
        clear="pointerout",
    )
    xt = alt.Tooltip(field=x, type="quantitative", title=x_title, format=".3~s")
    if group is not None:
        src = alt.Chart(agg).transform_pivot(group, value="center", groupby=[x])
        tips = [xt] + [
            alt.Tooltip(field=str(d), type="quantitative", format=".3~f")
            for d in domain
        ]
    else:
        src = alt.Chart(agg)
        tips = [
            xt,
            alt.Tooltip(
                field="center", type="quantitative", title=y_title, format=".3~f"
            ),
        ]
    rule = (
        src.mark_rule(color=REFERENCE, strokeWidth=1)
        .encode(
            x=enc_x,
            opacity=alt.condition(sel, alt.value(0.6), alt.value(0)),
            tooltip=tips,
        )
        .add_params(sel)
    )
    dots = base.mark_point(size=60, filled=True, clip=True).encode(
        y=alt.Y("center:Q", scale=ys),
        opacity=alt.condition(sel, alt.value(1), alt.value(0)),
    )
    return [rule, dots]


def _default_x(col: pl.Series, x_scale, x_axis, width: float, log: bool):
    """Explicit x_scale/x_axis win; otherwise nice ticks fitted to the data range."""
    if x_scale is not None or x_axis is not None:
        xs = x_scale if x_scale is not None else alt.Scale(zero=False, nice=False)
        return xs, (x_axis if x_axis is not None else si_axis())
    lo, hi = float(col.min()), float(col.max())
    return log_axis(lo, hi, width) if log else linear_axis(lo, hi, width)


def curves(
    agg: pl.DataFrame,
    *,
    x: str,
    group: str | None,
    x_title: str,
    y_title: str,
    title: str | None = None,
    order: Sequence[str] | None = None,
    colors: dict[str, str] | None = None,
    legend_title: str | None = None,
    legend_orient: str = "bottom-right",
    x_scale: alt.Scale | None = None,
    y_scale: alt.Scale | None = None,
    x_axis: alt.Axis | None = None,
    y_axis: alt.Axis | None = None,
    dashes: bool = False,
    markers: bool | None = None,
    hover: bool = True,
    size: str = "default",
) -> alt.LayerChart:
    """Line (center) + band (lo..hi) per group.

    markers: a dot on each data point. None (default) adds them to sparse curves, with
    at most SPARSE_MAX_POINTS points (e.g. periodic evals); True/False forces it.
    hover=True adds a nearest-x rule and tooltip, active only in HTML.
    """
    xs, x_axis = _default_x(agg[x], x_scale, x_axis, SIZES[size][0], log=False)
    y_axis = y_axis if y_axis is not None else alt.Axis()
    ys = y_scale if y_scale is not None else alt.Scale(zero=False)
    enc_x = alt.X(f"{x}:Q", title=x_title, scale=xs, axis=x_axis)
    enc = {"x": enc_x}
    domain = []
    if group is not None:
        domain = _domain(agg, group, order, colors)
        t = legend_title or group
        enc["color"] = alt.Color(
            f"{group}:N",
            title=t,
            sort=domain,
            scale=color_scale(domain, [colors[d] for d in domain] if colors else None),
            legend=alt.Legend(orient=legend_orient),
        )
        if dashes:
            enc["strokeDash"] = alt.StrokeDash(
                f"{group}:N",
                title=t,
                sort=domain,
                scale=alt.Scale(domain=domain, range=DASHES[: len(domain)]),
                legend=alt.Legend(orient=legend_orient),
            )
    else:
        enc["color"] = alt.value(OURS)
    base = alt.Chart(agg).encode(**enc)
    band = base.mark_area(clip=True).encode(y=alt.Y("lo:Q", scale=ys), y2="hi:Q")
    line = base.mark_line(clip=True).encode(
        y=alt.Y("center:Q", title=y_title, scale=ys, axis=y_axis)
    )
    layers = [band, line]
    if markers is None:
        per_curve = agg.group_by(group).len()["len"].max() if group else agg.height
        markers = per_curve <= SPARSE_MAX_POINTS
    if markers:
        # Not clipped: the axis ends at the data, so the last marker sits on the edge.
        layers.append(base.mark_point(opacity=1).encode(y=alt.Y("center:Q", scale=ys)))
    if hover:
        layers += _hover(
            agg,
            x=x,
            group=group,
            domain=domain,
            x_title=x_title,
            y_title=y_title,
            enc_x=enc_x,
            ys=ys,
            base=base,
        )
    w, h = SIZES[size]
    return _with_title(alt.layer(*layers).properties(width=w, height=h), title)


def points(
    agg: pl.DataFrame,
    *,
    x: str,
    group: str | None,
    x_title: str,
    y_title: str,
    title: str | None = None,
    order: Sequence[str] | None = None,
    colors: dict[str, str] | None = None,
    legend_title: str | None = None,
    legend_orient: str = "top-left",
    x_scale: alt.Scale | None = None,
    y_scale: alt.Scale | None = None,
    x_axis: alt.Axis | None = None,
    y_axis: alt.Axis | None = None,
    connect: bool = True,
    shapes: bool = False,
    x_log: bool = False,
    size: str = "default",
) -> alt.LayerChart:
    """Point + error bar per (group, x), optionally connected. For more sparse data.

    shapes=True adds marker shape as a second encoding of group; only when asked.
    x_log=True for parameters, FLOPs, compute, learning rate.
    Points carry tooltips (active in HTML).
    """
    xs, x_axis = _default_x(agg[x], x_scale, x_axis, SIZES[size][0], log=x_log)
    y_axis = y_axis if y_axis is not None else alt.Axis()
    ys = y_scale if y_scale is not None else alt.Scale(zero=False)
    enc = {"x": alt.X(f"{x}:Q", title=x_title, scale=xs, axis=x_axis)}
    tips = [
        alt.Tooltip(field=x, type="quantitative", title=x_title, format=".3~s"),
        alt.Tooltip(field="center", type="quantitative", title=y_title, format=".3~f"),
    ]
    if group is not None:
        domain = _domain(agg, group, order, colors)
        t = legend_title or group
        tips.insert(0, alt.Tooltip(field=group, type="nominal", title=t))
        enc["color"] = alt.Color(
            f"{group}:N",
            title=t,
            sort=domain,
            scale=color_scale(domain, [colors[d] for d in domain] if colors else None),
            legend=alt.Legend(orient=legend_orient),
        )
        if shapes:
            enc["shape"] = alt.Shape(
                f"{group}:N",
                title=t,
                sort=domain,
                scale=alt.Scale(domain=domain, range=SHAPES[: len(domain)]),
                legend=alt.Legend(orient=legend_orient),
            )
    else:
        enc["color"] = alt.value(OURS)
    base = alt.Chart(agg).encode(**enc)
    err = base.mark_errorbar(ticks=True).encode(
        y=alt.Y("lo:Q", scale=ys, title=y_title), y2="hi:Q"
    )
    pts = base.mark_point(opacity=1).encode(
        y=alt.Y("center:Q", title=y_title, scale=ys, axis=y_axis), tooltip=tips
    )
    layers = [err]
    if connect:
        layers.append(
            base.mark_line(clip=True, strokeWidth=1.5).encode(
                y=alt.Y("center:Q", scale=ys)
            )
        )
    layers.append(pts)
    w, h = SIZES[size]
    return _with_title(alt.layer(*layers).properties(width=w, height=h), title)


def reference(
    value: float,
    label: str | None = None,
    axis: Literal["x", "y"] = "y",
    label_align: Literal["left", "right"] = "left",
    size: str = "default",
):
    """Dashed grey reference line (e.g. a published baseline), optionally labelled."""
    df = pl.DataFrame({"v": [value], "label": [label or ""]})
    enc = {"y": "v:Q"} if axis == "y" else {"x": "v:Q"}
    rule = alt.Chart(df).mark_rule(strokeDash=[6, 4], color=REFERENCE).encode(**enc)
    if not label:
        return rule
    w = SIZES[size][0]
    pos = (
        {"y": alt.Y("v:Q"), "x": alt.value(w if label_align == "right" else 0)}
        if axis == "y"
        else {"x": alt.X("v:Q"), "y": alt.value(0)}
    )
    text = (
        alt.Chart(df)
        .mark_text(
            align=label_align,
            baseline="bottom",
            dy=-3,
            dx=-4 if label_align == "right" else 4,
            color=REFERENCE,
        )
        .encode(text="label:N", **pos)
    )
    return rule + text


def titled(chart: alt.TopLevelMixin, title: str) -> alt.TopLevelMixin:
    """Add a plot title to any chart (e.g. one built with plain Altair or with a reference layer)."""
    return _with_title(chart, title)


# ---------------------------------------------------------------------------
# Multi-panel figures
# ---------------------------------------------------------------------------

MAX_COLUMNS, MAX_ROWS = 3, 2
SLIDE = (1280, 720)  # 16:9 canvas in px; PNG at 3x is 3840x2160
_SPACING = 32


def _walk_layers(chart):
    if isinstance(chart, alt.LayerChart):
        for layer in chart.layer:
            yield from _walk_layers(layer)
    else:
        yield chart


def _set_legend(chart, legend) -> None:
    for c in _walk_layers(chart):
        enc = getattr(c, "encoding", alt.Undefined)
        if enc is alt.Undefined:
            continue
        for ch in ("color", "shape", "strokeDash"):
            e = getattr(enc, ch, alt.Undefined)
            if (
                e is not alt.Undefined
                and hasattr(e, "legend")
                and getattr(e, "field", alt.Undefined) is not alt.Undefined
            ):
                e.legend = legend


def _axis_title(chart, ch: str):
    for c in _walk_layers(chart):
        e = getattr(getattr(c, "encoding", alt.Undefined), ch, alt.Undefined)
        t = e._get("title") if e is not alt.Undefined else alt.Undefined
        if isinstance(t, str):
            return t
    return None


def _drop_axis_title(chart, ch: str) -> None:
    for c in _walk_layers(chart):
        enc = getattr(c, "encoding", alt.Undefined)
        e = (
            getattr(enc, ch, alt.Undefined)
            if enc is not alt.Undefined
            else alt.Undefined
        )
        if e is not alt.Undefined and hasattr(e, "title"):
            e.title = None


def _tagged_x(chart):
    """Yield (encoding.x, fmt) for layers whose x axis came from linear_axis()."""
    for c in _walk_layers(chart):
        enc = getattr(c, "encoding", alt.Undefined)
        e = (
            getattr(enc, "x", alt.Undefined)
            if enc is not alt.Undefined
            else alt.Undefined
        )
        if e is alt.Undefined:
            continue
        axis = e._get("axis")
        desc = axis._get("description") if hasattr(axis, "_get") else alt.Undefined
        if isinstance(desc, str) and desc.startswith(_TICK_TAG):
            yield e, desc.split(":", 1)[1]


def _shared_x_range(panels) -> tuple[float, float] | None:
    ranges = []
    for p in panels:
        tagged = list(_tagged_x(p))
        if not tagged:
            return None
        ranges.append(tagged[0][0]._get("scale")._get("domain"))
    return min(r[0] for r in ranges), max(r[1] for r in ranges)


def _retick_x(chart, lo: float, hi: float, width: float):
    for e, fmt in _tagged_x(chart):
        e.scale, e.axis = linear_axis(lo, hi, width, fmt)
    return chart


def _rendered_size(chart) -> tuple[float, float]:
    svg = vlc.vegalite_to_svg(chart.to_dict())
    m = re.search(r'<svg[^>]*width="([\d.]+)"[^>]*height="([\d.]+)"', svg)
    return float(m.group(1)), float(m.group(2))


def figure(
    panels: Sequence[alt.TopLevelMixin],
    *,
    title: str | None = None,
    panel_titles: Sequence[str] | None = None,
    columns: int | None = None,
    shared_legend: bool = True,
    legend_orient: Literal["bottom", "top", "right"] = "bottom",
    share_y: bool = False,
    share_x: bool = True,
    canvas: tuple[int, int] | None = SLIDE,
) -> alt.ConcatChart:
    """Grid of panels (up to 3 per row, 2 rows) with one shared legend and optional titles.

    panels: charts from curves()/points()/plain Altair, each with the same colour domain.
    title: figure-wide title. panel_titles: one per panel, only when asked for or needed to
    tell panels apart. canvas: size a full 2x3 grid is fitted to (default 16:9 slide,
    1280x720 px); smaller grids keep that panel size. None keeps each panel's own size.
    """
    n = len(panels)
    columns = columns or min(MAX_COLUMNS, n)
    rows = -(-n // columns)
    if columns > MAX_COLUMNS or rows > MAX_ROWS:
        warnings.warn(
            f"{n} panels in {rows}x{columns} exceeds {MAX_ROWS}x{MAX_COLUMNS}; split the figure"
        )
    if panel_titles is not None and len(panel_titles) != n:
        raise ValueError("panel_titles must have one entry per panel")

    legend = (
        alt.Legend(
            orient=legend_orient,
            direction="horizontal" if legend_orient != "right" else "vertical",
            fillColor="transparent",
            strokeColor="transparent",
            titleOrient="left" if legend_orient != "right" else "top",
            offset=16,
        )
        if shared_legend
        else None
    )

    def prepare(ps: Sequence, titles: Sequence[str] | None, cols: int) -> list:
        # Identical axis titles are shown once: y on the first column, x on the bottom row.
        k, nrows = len(ps), -(-len(ps) // cols)
        same_x = len({_axis_title(p, "x") for p in ps}) == 1
        same_y = len({_axis_title(p, "y") for p in ps}) == 1
        out = []
        for i, p in enumerate(ps):
            c = p.copy(deep=True)
            row, col = divmod(i, cols)
            if same_x and not (row == nrows - 1 or i + cols >= k):
                _drop_axis_title(c, "x")
            if same_y and col != 0:
                _drop_axis_title(c, "y")
            if shared_legend:
                _set_legend(c, legend)
            if titles is not None:
                c = _with_title(c, titles[i])
            out.append(c)
        return out

    # Panels with plotkit's default x ticks all end on the same labelled tick: the
    # largest end across panels (re-ticked for the final panel width).
    x_range = _shared_x_range(panels) if share_x else None

    def build(ps: list, cols: int, w: float, h: float) -> alt.ConcatChart:
        # Re-tick x for the final panel width: shared range, or each panel's own.
        ps = [
            _retick_x(
                c.copy(deep=True), *(x_range or _shared_x_range([c]) or (0, 0)), w
            )
            if (x_range or _shared_x_range([c]))
            else c
            for c in ps
        ]
        ps = [c.properties(width=round(w), height=round(h)) for c in ps]
        fig = alt.concat(*ps, columns=cols, spacing=_SPACING)
        res = (
            {"color": "shared", "shape": "shared", "strokeDash": "shared"}
            if shared_legend
            else {}
        )
        if share_y:
            res["y"] = "shared"
        if res:
            fig = fig.resolve_scale(**res)
        return _with_title(fig, title, "figure")

    prepared = prepare(panels, panel_titles, columns)
    if canvas is None:
        return build(prepared, columns, *SIZES["panel"])
    # Panel size is fitted for a full grid so smaller figures don't stretch to fill the canvas.
    fcols, frows = max(MAX_COLUMNS, columns), max(MAX_ROWS, rows)
    fit = prepare(
        [panels[i % n] for i in range(fcols * frows)],
        None
        if panel_titles is None
        else [panel_titles[i % n] for i in range(fcols * frows)],
        fcols,
    )
    W, H = canvas
    w, h = SIZES["panel"]
    for _ in range(3):  # fit the rendered size of the full grid to the canvas
        with (
            warnings.catch_warnings()
        ):  # repeated panels share hover names; harmless here
            warnings.simplefilter("ignore")
            fw, fh = _rendered_size(build(fit, fcols, w, h))
        w = max(120, w + (W - fw) / fcols)
        h = max(100, h + (H - fh) / frows)
    return build(prepared, columns, w, h)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

Format = Literal["svg", "png", "pdf", "html", "json"]


def _interactive(chart, _name: str = "zoom"):
    """Zoom/pan (drag, scroll; double-click resets) on each panel independently, for HTML.

    Each panel keeps its own hover and zoom."""
    c = chart.copy(deep=True)
    for attr in ("concat", "hconcat", "vconcat"):
        sub = getattr(c, attr, alt.Undefined)
        if sub is not alt.Undefined:
            setattr(
                c, attr, [_interactive(p, f"{_name}_{i}") for i, p in enumerate(sub)]
            )
            return c
    zoom = alt.selection_interval(bind="scales", encodings=["x", "y"], name=_name)
    if isinstance(c, alt.LayerChart):
        return _add_to_param_layer(c, zoom)
    if isinstance(c, alt.Chart):
        return c.add_params(zoom)
    return c


def _add_to_param_layer(layer: alt.LayerChart, param) -> alt.LayerChart:
    """Attach param to the first layer (the band, which encodes both x and y, so zoom binds
    both scales; the hover rule only encodes x)."""
    idx = 0
    target = layer.layer[idx]
    layer.layer[idx] = (
        _add_to_param_layer(target, param)
        if isinstance(target, alt.LayerChart)
        else target.add_params(param)
    )
    return layer


def _dedupe_zoom_views(spec: dict) -> dict:
    """Altair can attach a panel's zoom to two of its layers, which Vega rejects
    ("Duplicate signal name"). Keep one view per zoom: the one that isn't the hover rule
    (the rule only encodes x, so zooming through it would leave y fixed).
    Also un-share y across panels: a shared scale can't be zoomed from one panel, so
    pinch/scroll would only zoom x."""
    scale_res = spec.get("resolve", {}).get("scale", {})
    if scale_res.get("y") == "shared":
        scale_res["y"] = "independent"
    params = spec.get("params", [])
    hover_views = {v for p in params if not p.get("bind") for v in p.get("views", [])}
    for p in params:
        views = p.get("views")
        if p.get("bind") == "scales" and views and len(views) > 1:
            keep = [v for v in views if v not in hover_views] or views[:1]
            p["views"] = keep[:1]
    return spec


def _to_vega(chart) -> dict:
    """Compile to Vega and centre outside (top/bottom) legends, which Vega-Lite can't express."""
    spec = chart if isinstance(chart, dict) else chart.to_dict()
    vg = vlc.vegalite_to_vega(spec)
    vg = json.loads(vg) if isinstance(vg, str) else vg
    legend = vg.setdefault("config", {}).setdefault("legend", {})
    legend["layout"] = {"top": {"anchor": "middle"}, "bottom": {"anchor": "middle"}}
    return vg


def save(
    chart: alt.TopLevelMixin,
    path: str | Path,
    formats: Sequence[Format] = ("png",),
    png_scale: float = 3.0,
) -> list[Path]:
    """Write path.<fmt> for each format and return the paths. Default: PNG only.

    PNG is what gets shown in chat. SVG and HTML embed a fetched font so they render
    identically anywhere. HTML is self-contained (Vega bundled, works offline) and
    interactive: hover tooltips, plus zoom/pan on every panel.
    """
    path = Path(path)
    # Keep dots in names ("run_18.7M"); only strip a real format suffix.
    stem = (
        path.stem
        if path.suffix.lstrip(".") in {"png", "svg", "pdf", "html", "json"}
        else path.name
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    vg = _to_vega(chart)
    css = _font_face_css()
    out = []
    for fmt in formats:
        p = path.parent / f"{stem}.{fmt}"
        if fmt == "svg":
            svg = vlc.vega_to_svg(vg)
            if css:
                svg = re.sub(
                    r"(<svg[^>]*>)",
                    rf"\1<defs><style>{css}</style></defs>",
                    svg,
                    count=1,
                )
            p.write_text(svg)
        elif fmt == "png":
            p.write_bytes(vlc.vega_to_png(vg, scale=png_scale))
        elif fmt == "pdf":
            p.write_bytes(vlc.vega_to_pdf(vg))
        elif fmt == "html":
            html = vlc.vega_to_html(
                _to_vega(_dedupe_zoom_views(_interactive(chart).to_dict())), bundle=True
            )
            if css:
                html = html.replace("</head>", f"<style>{css}</style></head>", 1)
            p.write_text(html)
        elif fmt == "json":
            p.write_text(chart.to_json())
        else:
            raise ValueError(f"unknown format {fmt}")
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# Runner: uv run plotkit.py fig.py [args...]
# ---------------------------------------------------------------------------


def _main() -> None:
    import runpy

    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(__doc__)
        sys.exit(0)
    script = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # import plotkit
    sys.path.insert(0, str(script.parent))  # script's own helpers
    sys.argv = [str(script), *sys.argv[2:]]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    _main()
