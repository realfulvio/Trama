# Q–Q Panels Per-Panel Formatting

When the **Normality and lognormality** analysis renders Q–Q plots in **Normal**, **Lognormal**, or **Both** distribution mode, each Q–Q panel (`normal` and `lognormal`) can be formatted independently without altering the underlying quantile coordinates, reference line equation, or hypothesis-test tables.

## Where to Open the Editor

- **Graph action bar:** click **Q–Q panels…** (Italian: **Pannelli Q–Q…**).
- **Graph Inspector:** inside the **Axes and limits** section, click **Q–Q panels…**.

Both controls are shown only on Q–Q figures (`panel_axes(figure)` non-empty) and remain hidden on standard single-panel or non-Q–Q graphs. If the Inspector holds an unapplied draft, opening the dialog asks whether to apply, discard, or cancel that draft first (`settle_graph_draft`).

## What Can Be Formatted per Panel

Choose the target panel (`Normal Q–Q (normal)` or `Lognormal Q–Q (lognormal)`), then format across three tabs:

### 1. Axes & title (`Assi e titolo`)
- **Title**, **X label**, **Y label**: plain literal strings (max 160 characters; mathtext parsing disabled so `$x$`, `{A}`, `%` render verbatim). Leave blank for automatic defaults.
- **X range** and **Y range** (**Min** / **Max**): accepts `.` or `,` decimal separators (`linear` scale only). Leave both bounds blank for automatic limits; specifying only one bound or `min >= max` shows an inline error and moves focus to the offending field while keeping the last valid live preview intact.
- **Show legend**: controls legend visibility on the selected panel without inventing a legend on plots where no reference line was drawn unless explicitly requested.

### 2. Points (`Punti`)
- **Show points** (`points.visible`): toggles visibility of the Q–Q scatter series (`_trama_qq_points`) and its legend entry. When unchecked, dependent controls are disabled without clearing their values.
- **Symbol** (`points.marker`): `Auto` or one of `o` (Circle), `s` (Square), `D` (Diamond), `^` (Triangle up), `v` (Triangle down), `+` (Plus), `x` (Cross).
- **Size** (`points.size`): finite point diameter between `0.5` and `36` points (`scatter` area = `size²` pt²; default area `26` when omitted).
- **Color** (`points.color`): `#RRGGBB` hex string (case-preserving) with live swatch and color chooser (`Choose…` / `Scegli…`).
- **Opacity** (`points.alpha`): finite value in `[0, 1]`. Setting `0` makes points transparent while keeping the artist visible and present in the legend (distinct from `visible=false`).

### 3. Reference line (`Retta di riferimento`)
- **Show reference line** (`reference_line.visible`): toggles visibility of the fitted line (`_trama_qq_reference`) and its legend entry. If the analysis produced no reference line (option disabled or zero variance), controls are disabled with an explanatory message; saved preferences are preserved without inventing a line.
- **Color** (`reference_line.color`), **Line width** (`reference_line.width`, finite `0.1–10` pt), **Line style** (`reference_line.style`: `-`, `--`, `-.`, `:`), and **Opacity** (`reference_line.alpha`, finite `0–1`).

Leave any control set to **Auto (default)** or blank to inherit the analysis default—inheriting defaults never creates artificial overrides on save.

## Drafts, Persistence & Precedence (`style["qq_panels"]`)

- Drafts are retained per panel while switching between panels.
- **Preview** updates live artists in place without recreating the figure; **Reset selected** clears overrides only for the active panel; **Cancel** / `Esc` restores the last confirmed style (including legends); **Apply** validates atomically across all panels before committing.
- `Format Graph` (including **Reset**) and `GraphInspector` (**Apply** / **Cancel**) preserve `run.style["qq_panels"]`.
- Unrelated artists (such as native shapes, annotations, or overlaid plots) are untouched; vector SVG/PDF exports and multi-panel layouts preserve per-panel formatting.

## Verification

```bash
TRAMASTAT_SMOKE_ONLY=qq-artist-styles TRAMASTAT_SMOKE_SCREENSHOTS=1 python tramastat.py --smoke /tmp/trama-smoke
TRAMASTAT_SMOKE_ONLY=qq-panels TRAMASTAT_SMOKE_SCREENSHOTS=1 python tramastat.py --smoke /tmp/trama-smoke
python -m unittest tests.test_qq_panels tests.test_qq_panel_dialog -v
```

