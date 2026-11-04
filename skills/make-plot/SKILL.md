---
name: make-plot
description: Style and workflow for figures. Use whenever plotting results from running experiments, fetching wandb results, making a figure for a paper, presentation, report or Notion page, or restyling an existing plot. It takes precedence over any generic dataviz skills.
---

# make-plot

Use [`plotkit.py`](scripts/plotkit.py) in this skill's folder. It's a `uv` script. Figure scripts are run through it, and it is by default not copied into projects.

Usage:

```sh
    uv run <skill_dir>/scripts/plotkit.py fig.py [args...]
    uv run --with wandb <skill_dir>/scripts/plotkit.py fig.py      # extra deps via --with
```

Inside the figure script:

```py
    import plotkit as pk
    pk.enable()                      # or pk.enable(theme="dark", transparent=True)
    df, _ = pk.ema(df, x="step", y="return", seed="seed", by="algo")
    agg = pk.aggregate(df, x="step", y="return", seed="seed", by="algo")
    chart = pk.curves(agg, x="step", group="algo", order=["Ours", "PPO"],
                      x_title="Number of environment steps", y_title="Episode return")
    pk.save(chart, "out/learning_curves")        # -> out/learning_curves.png
```

If a figure seems to need something new, say so and propose a change to the system instead of
one-off styling.

## Workflow

1. Write the figure script in the scratchpad (or a temp dir), or wherever the user says, e.g. a repo's `plots/` if they ask for it to be kept. Start from [`templates/figure.py`](templates/figure.py). The docstring says what's on x, y and colour.
2. Fetch and cache raw data. Every wandb fetch is written to a parquet cache next to the figure script before anything else happens. Then a request to regenerate, restyle or tweak the figure only reruns the script and finishes in seconds.
   - Cache the raw rows: per-seed values, plus the run name, id and group needed to rebuild any grouping. Never cache pre-aggregated means.
   - Name the cache after the figure script (`fig_name.parquet`). Include every metric the figure might need, so changing the y metric or adding a panel usually doesn't need a refetch.
   - When to refetch: only when the user asks, when runs were still running at fetch time, or when the requested runs or metrics aren't in the cache. The template's `--refresh` flag does this.
   - Remember the script path for the rest of the session, so "regenerate that plot" means rerunning it.
   - For wandb: use `run.history(keys=[...], samples=N)`, not `scan_history`, and filter to finished runs.
3. Shape the data: `pk.ema` (curves only), then `pk.aggregate`. Alignment of seeds that log at different steps happens inside `aggregate`. Use these instead of hand-rolled statistics or Vega-Lite's `extent="ci"` bands.
4. Build the chart: `pk.enable()`, then `pk.curves(...)`, `pk.points(...)`, or plain Altair with the `pk` tokens.
5. Run it.
6. Look at the PNG yourself first and fix anything that fails the checklist below. Don't show the user a figure you haven't checked.
7. Send the PNG into the chat with the file-sharing tool (e.g. `SendUserFile`), unless the user said to put it somewhere else.

## Formats

`pk.save(chart, path)` writes a PNG by default. Pass `formats=` for others:

| Format | Use |
|---|---|
| `png` | Default. 3× scale, with the background of the current theme. Previews best in chat. A slide figure comes out at 3840×2160. |
| `svg` | Fonts are embedded, so it renders the same anywhere. |
| `pdf` | For a paper, add it alongside the PNG. Fonts are embedded, so it drops straight into LaTeX. |
| `html` | Interactive by default. Self-contained and works offline (Vega bundled, about 1 MB). |
| `json` | Vega-Lite spec, for diffing figure changes. |

## Themes

`pk.enable(theme, transparent)` usage:
- `theme="light"` (default): white background, black text, light grey grid.
- `theme="dark"`: Light text, dark grid and a near-black background.
- `transparent=True`: no background fill.

## Design system

### Text

Sizes are LaTeX-named tokens in px:

| Element | Size |
|---|---|
| axis titles, legend title | `Large` = 20 |
| tick labels, legend labels | `large` = 16 |
| annotations | `normalsize` = 14 |

Never change font sizes per chart. Pick a size preset instead.

### Sizes

- `default`: 600×400 plot area.
- `panel`: 400×300 for facets and concatenation.
- `wide`: 900×360 for a full-width single panel.
- `square`: 400×400.

### Colour

The hue representing the main result is always `pk.OURS`, first in the legend.
A single baseline or control is `pk.BASELINE`. `pk.categorical(2)` retrieves `pk.OURS` and `pk.BASELINE`. Three or more conditions use `pk.categorical(n)` in its fixed order.
Ordered sweeps use `pk.sequential(n)`: up to 6 shades.
Reference lines use `pk.reference(value, label)`, and are not in the legend.
Pin colours to names: always pass `order=` (primary first) or `colors={name: hex}`, so a condition keeps its colour across every figure in a set.

### Marks

Colour alone distinguishes groups.
Curves with few data points (30 or fewer, e.g. sparse eval metrics) get a marker on each point automatically; `curves(markers=True/False)` overrides this. Use `curves` for metrics over time and `points` when each x is a separate condition that needs error bars.
Add marker shapes (`points(shapes=True)`) or dashes (`curves(dashes=True)`) only when the user asks, e.g. for greyscale print.

## Presentation rules

### Titles

No title by default. Never add one to a paper figure; the LaTeX caption does that job.
Add a title when the user asks for one, or when the figure stands alone without a caption (a slide, Slack or Notion). Pass `title=` to `curves`/`points`, or use `pk.titled(chart, ...)` for anything else.
Titles are sentence case with no full stop, and name what is shown, not the conclusion. For example "Success rate on MT10", not "Ours beats MOORE".

### Axis titles

Sentence case, the plain-language name of the quantity, with units in parentheses.
E.g. "Number of environment steps", "Success rate", "Dormant neuron ratio (%)", "Wall-clock time (h)".
Never a raw metric key or a bare symbol.

### Domains and ticks

Use 5–10 labelled ticks, depending on figure width (about one per 100 px). Unlabelled ticks between them are fine and help reading values. X axis ends on the last tick, which is always labelled.
In `pk.figure`, panels share an x range by default, `share_x=False` lets each panel end at its own data.
Large counts use SI labels (500K, 2M, 1.5B); the default x axis does this. Use `pk.si_axis()` for other axes.
Ratios stored as 0–1 use `pk.percent_axis()`.
Log axes are for exponentially growing quantities (parameters, FLOPs, compute, learning rate): `points(..., x_log=True)` (`pk.log_axis`).

Set the y domain explicitly when it sharpens the comparison: `[0, 1]` for rates, or zoomed to where methods differ. Keep it the same for the same metric across a figure set.

### Legend

Inside the plot, in the corner with the least data: `bottom-right` for rising curves, `top-left` for scaling plots, `top-right` for decaying metrics.
The legend title is the variable name.
With 3 or more facets, use one shared legend at the top, outside the plot: `alt.Legend(orient="top")`.

### Multi-panel figures for slides, or when panels are compared side by side

```python
panels = [pk.curves(agg_t, ...) for agg_t in per_task]
fig = pk.figure(panels, title="Per-task success rate",
                panel_titles=tasks, share_y=True)
pk.save(fig, "out/per_task")
```

- Layout: up to 3 panels per row and 2 rows (`columns=` overrides). With more than 6 panels, split the figure as it's unlikely to fit into a slide.
- Size: panel size is fitted so a full 2×3 grid fills `canvas=`, a 16:9 slide by default. Smaller grids shorter rather than stretched. `canvas=None` keeps each panel's own size, e.g. for a paper.
- Legend: one shared, centred legend below the grid (`legend_orient=`), as long as panels use the same colour domain. Pass the same `order=` to every panel.
- Figure title: `title=` gives one centred above the grid.
- Panel titles: `panel_titles=` only when asked for, or when panels would otherwise be indistinguishable (same metric, different task or setting). Panels that differ in y metric are already told apart by their y titles.
- Axis titles shown once: when every panel has the same axis title, the y title appears only on the first column and the x title only on the bottom row.
- Shared y: `share_y=True` when panels show the same metric, so heights compare directly.

## Checklist before sending a figure

- [ ] It shows what was asked
- [ ] No raw metric keys; units present; sentence case
- [ ] Main result is primary and first in the legend; colours are consistent with earlier figures in session or document
- [ ] The legend doesn't cover data; nothing important is clipped (check the endpoints)
- [ ] No text in or around the figure beyond axes, legend and reference labels

## Gotchas

- `alt.Y(..., axis=None)` hides the axis. Pass `alt.Axis()` for the default.
- Legend and colour order follow `order=` or `colors=`, else the order groups first appear in the data. `ema` and `aggregate` keep that order; a `.sort(group)` before plotting makes it alphabetical.
- Don't use `interpolate="basis"` to smooth. It's purely visual, moves lines away from the data and clips endpoints. Use `pk.ema`.
- Font fetch fails (offline, on a machine without Times): `enable()` warns and falls back to the system serif. Run it once online to fill the cache.
- SVG text references the font by name: Times is used from the system and isn't embedded, so an SVG opened where Times isn't installed falls back to a serif. PNG and PDF always have the font baked in.
