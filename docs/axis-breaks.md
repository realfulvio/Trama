# Axis Breaks for XY Graphs

An axis break cuts a numeric axis into two or three segments with exact limits and exact shares of the plot, so a graph can show clusters of data without drawing the empty stretch between them. It is available for **XY series** and **XY error bars**, on the X axis or the left Y axis.

The graph is drawn as real Matplotlib panels. Each panel shows one segment, the other axis stays in sync, and the legend appears once. Break marks sit on the cut edges of the axis. Edge tick labels point into their panels so the labels across a gap remain distinct. SVG and PDF exports stay vector, and the worksheets are never touched: a point between two segments is not drawn, but it stays in the data and in every calculation.

## Where to find it

- **Format Graph → Axes → Axis breaks…** (`Interruzioni asse…`)
- **Graph Inspector → Axes → Axis breaks…**, inside the current Inspector draft. Cancel in the editor returns to the draft, Cancel in the Inspector returns to the confirmed graph. **Reset section** of the Axes section removes the breaks.

In the editor choose the axis, the number of segments, the gap and, for each segment, the low and high limit, the share of the plot in percent and an optional major interval. **Suggest from the data** cuts the axis at the widest empty stretches. Both limits belong to their segment. Typing a decimal comma works in both languages.

**Preview** draws the candidate on the graph without confirming it. An invalid draft keeps the last valid preview, names the problem and puts the focus on the field. **Cancel** or **Esc** undoes any preview.

> Panels can have a different physical scale even when they show the same unit: the share of a segment is the space you give it, not its length in data units. The note is repeated in the editor.

## Saved style

The breaks are one section of the graph style, stored in the project like the other style sections:

```json
{
  "axis_breaks": {
    "axis": "x",
    "gap": 0.04,
    "segments": [
      {"low": 0, "high": 4,   "share": 35, "major_step": 2},
      {"low": 10, "high": 12, "share": 30, "major_step": 1},
      {"low": 18, "high": 22, "share": 35, "major_step": 2}
    ]
  }
}
```

- `axis` is `"x"` or `"y"` (the left Y axis). `gap` is the fraction of the band between two panels, from `0.01` to `0.10`.
- Two or three segments in increasing order. `low < high`, and each `low` is larger than the previous `high`. The shares are positive and add up to `100`.
- `major_step` is a positive number, or `null` for automatic ticks. A step that would place more than 200 ticks is refused.
- The panel lengths follow `(1 - (N - 1) * gap) * share / 100` of the band reserved for the plot, so shares and gaps stay exact at any window, export or layout size.
- An invalid record is refused before anything on the graph changes, and the message names the segment and the field.

## What is drawn

- Lines, points, error bars (including asymmetric ones) and the legend are repeated per panel and clipped to it. A point exactly on a limit is drawn.
- Reference lines, shapes, annotations, additional ticks and shaded ranges are drawn on the panels where they have content. A guide on the other axis crosses every panel, with its tick or label on one edge only.
- Drawings and annotations placed in plot fractions cannot be combined with axis breaks; the editor says so.
- The limits and the scale of the broken axis come from the segments. Their fields rest in Format Graph and in the Inspector while the breaks are on, and the previous limits return when the breaks are removed.
- Break marks are SVG elements whose ids contain `axis-break-marker-`. Every other repeated element has an id that starts with `trama-axis-break:`, so ids stay unique in single figures and in layouts, where each graph adds its own panel prefix.

## When breaks cannot be shown

Axis breaks need a native XY series or XY error bars graph with a linear numeric broken axis that increases, the standard graph layout, and no right Y axis. A saved setting that a later change makes impossible, for example moving a series to the right axis, is **kept and ignored**: the graph is drawn whole, the status bar and the Inspector say why, and the setting comes back as soon as the graph allows it. Breaks chosen in Format Graph that cannot be drawn stop **Apply** and name the reason instead.

An old project without the section opens as before. On a graph that cannot show the breaks (a log or categorical broken axis, extra drawing elements, an imported picture) the figure stays as it was.

While breaks are on, drawing shapes with the mouse is off; **Graph shapes…** still edits them.

## API

`analisi.axis_breaks.segment_axes(figure)` returns the segment Axes of a figure in increasing data order, or an empty list. `analisi.presentation.apply_style(figure, style)` draws, replaces or removes the breaks on the same Figure, and `analisi.axis_breaks.axis_breaks_reason(figure)` gives the reason when a saved record is not drawn.

## Example

The [example project](examples/Assi-interrotti.alab) holds the synthetic series and error-bar data of this page with the two saved styles: three X segments on the series graph and two Y segments on the asymmetric error bars. Every value is invented for the example.

## Verification

```bash
python -m unittest tests.test_axis_breaks tests.test_axis_breaks_gui -v
TRAMASTAT_SMOKE_ONLY=axis-breaks TRAMASTAT_SMOKE_SCREENSHOTS=1 python tramastat.py --smoke /tmp/trama-axis-breaks
```

The smoke drives Format Graph and the Inspector in both languages and both themes, saves and reopens a project, edits a point in the gap and on a limit, exports PNG, SVG and PDF of a figure and of a two-panel layout, and measures 10,000 points with three segments. Windows and native DPI checks are separate and were not run for this page.

Run the GUI smoke separately in Standard and Modern with isolated preferences. The Modern workspace checks run when the app starts in Modern.
