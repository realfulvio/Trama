# Formatting single points

Any observation of an **XY series** (drawn with symbols) or of a **Scatter plot** (with or without groups) can have its own color, symbol and size, so one point can be highlighted, marked as an outlier or told apart from an identical neighbour. It is a presentation setting: no worksheet, series, calculation, fit, table, legend entry or axis limit changes, and the line of an XY series keeps its stroke.

## Where to find it

**Graph Inspector → Single point** (`Punto singolo`), in Classica Qt.

1. Choose the point. Click it on the graph, or pick it from **Observations** (`Osservazioni`), the list of the drawn observations of the selected series (it reads on demand, so ten thousand rows open at once). The panel shows the series, the **source row** of the worksheet and the coordinates, and a red ring marks the point on the screen. When several observations are within reach of the click (identical rows, or points drawn on top of each other) every one of them is offered in a list, and the series chooser follows the one you pick.
2. Set **Color**, **Symbol** and **Size (pt)**. A blank color or size and the symbol *As series* (`Come la serie`) keep what the series gives its points: they follow later changes of the series. Every valid change previews on the live graph.
3. **Apply** stores the Inspector draft once, **Cancel** (or Esc) puts the confirmed graph back, exactly like the other sections.
4. **Reset this point** returns the selected observation to the series look. **Formatted points** (`Punti formattati`) lists every formatted point of the graph, also the ones that wait or are suspended, and **Reset point in list** removes the chosen one. **Reset section** removes all of them. A reset is always possible, whatever the state of the graph.

A point that is marked in the list with ● is formatted. The ring is never part of a figure, an export, a layout or a thumbnail.

## Identity of a point: the source row

A style belongs to a worksheet row, not to a position on the screen and not to a pair of coordinates. The graph builders record, for every point, the **worksheet row** it comes from (1-based, counted before missing cells and exclusions remove points). A saved style stores that row, the length of the worksheet, the coordinates, which copy it is among the points of the series with exactly those coordinates (`copy` of `copies`) and the columns the graph reads. After a recalculation the point is found again like this:

| Situation | What happens |
| --- | --- |
| The graph reads other columns than when the point was formatted | **Suspended**: the message says the columns changed. |
| The worksheet keeps its length | The row position is trusted. A row that is excluded or has a missing value is simply not drawn: the style **waits** and comes back with the value. A row whose values were edited keeps its style. If the old values now sit in another row, the style follows them only when they are unique; otherwise it is **suspended**. |
| Rows were inserted or deleted | Positions cannot be trusted, so the values decide. They must be found as many times as when the point was formatted, and the same copy is taken. A duplicate row that was added or removed makes the association uncertain and the style is **suspended**. |
| The series is gone | **Suspended**: *the series is no longer in this graph*. |

A waiting or suspended style is **never given to another row**. The record stays in the project, the graph shows a message (also in the page notice) and the Inspector lists it with the reason, so it can be reset. Example: rows 1 and 2 are identical and row 2 is formatted. Insert a third identical row above them and nothing can say which copy was meant, so no point takes the style.

## Which graphs, and when it says no

| Graph | Single points |
| --- | --- |
| Scatter plot, with or without groups | yes |
| XY series drawn as *Points* or *Line and points* | yes (rows without a value have a vertex but no point) |
| XY series drawn as *Line*, *Step* or *Bars* | no: *this XY series is drawn without symbols* |
| XY series with an axis break | no, while the break is on: *not drawn while axis breaks are active* |
| Bubble plot, box and violin plots, histograms, bar and column graphs, fits, survival and every other graph | no: *points can be formatted in XY series and scatter plots only* |

The reason is written at the section itself and the fields stay disabled.

## Saved style

The formatted points are one section of the graph style (`points`), stored in the project with the other style sections and validated by the shared presentation model. A project saved before the feature has no such section and opens exactly as it did.

```json
{
  "points": [
    {"series": "scatter:1:C",
     "source": {"row": 2, "rows": 5, "x": 1.0, "y": 2.0, "copy": 2, "copies": 2, "recipe": ["X", "Y", "Group"]},
     "color": "#ac4320", "marker": "s", "marker_size": 9}
  ]
}
```

- Up to 256 formatted points per graph. A record has `series`, `source` and at least one of `color`, `marker` (`o s D ^ v + x *`) and `marker_size` (0.1 to 72 points). The same point twice, a malformed reference, an unknown key or a series that is not an XY or scatter series is refused with a message before anything changes.
- Analysis templates, *Repeat analysis on other sheets* and the figure style presets leave the points out: they belong to the rows of one table. A family copy keeps them with the rest of the style, and they follow the rules above if the copy holds other values.
- The Tk classic window has no editor for it and keeps the records of a project when it formats a graph.

## How it is drawn

The series keeps its artist, its data, its limits and its legend. The formatted points are taken out of the series artist (a scatter collection holds NaN at those vertices, an XY line hides their markers) and drawn again by one extra marker line per distinct look, which sits in the axes but outside the series list, the limits and the legend. So the series keeps Matplotlib's fast uniform drawing: a scatter plot of ten thousand points redraws as quickly with a hundred formatted points as without any. The legend is built from the series look, so an entry never shows the one point that was formatted. Recalculation, layouts and PNG, SVG and PDF exports draw the extra markers like any other artist.

## Tests

- `tests/test_point_style.py`: the engine, the identity cases above, validation, legend and limits, exports (PNG, SVG, PDF), layout, ring.
- `tests/test_qt_point_style.py`: the Inspector (list, click, overlap, preview, Apply once, Cancel, reset), recalculation after edit, insertion, deletion and exclusion, save and reopen, family copy, exports.
- `tests/smoke_qt_point_style.py`: the real window with screenshots, in English and Italian, light and dark, at 1024×768 and at an emulated 150 %.
- `tests/bench_point_style.py`: ten thousand points, one hundred edits.
- Data: `tests/data/point_style/casi.json` and `casi.csv` (rows 1 and 2 identical).
