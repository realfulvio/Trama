# Data labels of the observations

Any observation of an **XY series** (drawn with symbols) or of a **Scatter plot** (with or without groups) can carry a label: the title of its worksheet row, or the value of any column, numeric or text. It is a presentation setting. No worksheet, series, calculation, fit, table, legend entry or axis limit changes, and the line of an XY series keeps its stroke.

## Where to find it

**Graph Inspector → Data labels** (`Etichette dati`), in Classica Qt.

1. Choose the series in **Element**. **Label from** (`Etichetta da`) lists *No labels*, *Row titles* (the column named *Row title*) and every column of the worksheet. Choosing one writes the text of that source next to the points of the series.
2. Optionally set **Show the labels of this series**, **Label color**, **Position** (above, below, left, right of the point), **Size (pt)** and **Maximum labels**. A blank color, size or limit keeps the default.
3. To show or hide the label of **one** observation, select it in **Single point** (click it on the graph or pick it from its list) and use **Selected point** in Data labels: *As series*, *Always show* or *Hide*. The panel shows the label text the point would carry. **Labels set on observations** lists every such setting, also the ones that wait or are suspended, and **Reset label in list** removes the chosen one. Double-clicking an entry selects its point.
4. **Apply** stores the Inspector draft once, **Cancel** (or Esc) puts the confirmed graph back, **Reset section** removes every label, exactly like the other sections. Every valid change previews on the live graph.

The ring that marks the selected point is drawn on screen only. It is never part of a figure, an export, a layout or a thumbnail.

## The text

The text of a label is **literal**: `$`, symbols, accents and backslashes are drawn as they are and never read as math. A number is written with up to twelve significant digits (`0.3`, not `0.30000000000000004`). A cell that is empty or blank, missing or **excluded**, a number that is not finite, and an observation that the graph does not draw (a missing or excluded Y) make **no label**. A text longer than 200 characters is cut with `…`.

## Source of the text: the identity of a column

A worksheet column has an identity of its own, kept in the project like the identity of a row. The label finds its source by that identity, not by the name:

| Situation | What happens |
| --- | --- |
| The column is renamed | The label follows it and shows the new name. |
| The column is deleted | The source is **missing**: the label is suspended, the graph says why, nothing is drawn. |
| Another column is created with the name of the deleted one | It is a new column. The labels do **not** reconnect by themselves. Open the section and choose it (the entry *Name (column no longer in the worksheet)* shows what was lost). |
| Undo brings the column back | The identity comes back with it, and so do the labels. |
| A calculated column or a result column | A calculated column is identified by its name (`formula:`); a result sheet by name. Neither can be edited as a source column. |

A project saved before this feature has no stored identities: its columns are identified by position until the first insertion, rename or deletion writes them down.

## The observation: the source row

An override of one observation reuses the identity of *Formatting single points* ([point-style.md](point-style.md)): the source row, its stable token, the coordinates and the position among identical points. So two points with the same X and Y are never confused, and the label setting follows its row when the rows are reordered. When the identity becomes uncertain (the row was deleted, or a replacement is identical to it) the setting is **suspended**: it stays in the list with its reason, is never given to another row, and can always be reset. A new row identical to a deleted one does not inherit its setting. A point that is excluded or has no value *waits* and comes back when it can be drawn.

## Which graphs, and when it says no

The same as single points: Scatter plots and XY series drawn as *Points* or *Line and points*. The reason is written at the section when a series cannot have labels (drawn without symbols, with an axis break, histograms, bars, fits, survival and every other graph). The first delivery has no labels for graphs that do not support selecting a single point.

## The limit and the priority

A series draws at most **250** labels (**Maximum labels**, up to 1000). When more observations have a label:

1. the observations you chose to **show** come first, in worksheet order;
2. then the other observations, in worksheet order;
3. the rest is **omitted**, and the section says how many (*100 of 4942 labels shown: 4842 omitted…*).

An observation that you chose to hide is never counted. Labels outside the visible part of the axes are not drawn: zoom and the limits of the axes never leave a label floating.

## Saved style

One section of the graph style (`observation_labels`), stored in the project with the other style sections and validated by the shared presentation model. A project saved before the feature has no such section and opens exactly as it did.

```json
{
  "observation_labels": [
    {"series": "scatter:1:Controllo",
     "from": {"kind": "column", "name": "Etichetta", "id": "base:5"},
     "show": true, "color": "#aa2288", "position": "above", "size": 8, "limit": 250,
     "observations": [
       {"source": {"row": 2, "rows": 6, "x": 1.0, "y": 2.0, "copy": 2, "copies": 2, "recipe": ["X", "Y", "Gruppo"], "row_token": "base:2"},
        "show": false}]}
  ]
}
```

- `from` is `{"kind": "row_title"}` or `{"kind": "column", "name", "id"}`. Up to 64 labelled series and 256 observation settings per graph. A malformed record, an unknown key or a series that is not an XY or scatter series is refused with a message before anything changes.
- The identities of the columns are saved in the table of the project (`column_ids`).
- Analysis templates and the figure style presets leave the labels out. *Repeat analysis on other sheets* keeps the source columns and the series, finds the columns by name in the other sheet, and leaves behind the settings of single rows. A family copy keeps everything.
- The Tk classic window has no editor for it and keeps the records of a project when it formats a graph.

## How it is drawn

The labels of a series are the texts of **one** artist in the axes, outside the series list, the limits, the legend and the layout of the figure. It is built from a clean state every time a style is applied, so applying one again never duplicates anything. A series without labels is not read at all: there is no pass over its data, and redrawing costs nothing for it. A labelled series is read once, when the style is applied, with one vectorized test of which cells have a text; one text is built for each label that is drawn.

Each label is an ordinary text of the renderer: text in a PDF, `<text>` in an SVG that keeps text, outlines otherwise, pixels in a PNG, and the same in a layout that embeds the graph.

## Cost

Redrawing is the cost to know: Matplotlib draws every text on every redraw. `tests/bench_observation_labels.py` measures a scatter plot and an XY series of 10,000 points on the same canvas, first without labels and then with 100. On the machine of the delivery (4 cores, Linux, Qt `offscreen`, a 1000×700 viewport), a redraw of 10,000 points took 83–96 ms without labels, 173–199 ms with 100 labels (about 0.9 ms for each label) and 311–348 ms with the default limit of 250. The Inspector steps are cheap (choosing the source or the limit takes 9–20 ms, Apply 8–10 ms). Removing the labels brings the redraw back to its original time, and the other group of a scatter plot, which has no labels, is never read. The limit is there for that reason. The numbers of one machine say nothing about another one: run the benchmark on the machine that matters.

## Tests

- `tests/test_observation_labels.py`: the engine, text rules, limit and priority, identity of columns and observations, validation and Italian messages, exports (PNG, SVG, PDF), layout, ring.
- `tests/test_qt_observation_labels.py`: the Inspector (sources, fields, observation, list, Apply once, Cancel, reset), reordered, deleted and added rows, columns renamed, deleted and created again, Undo, save and reopen, family copy, repetition and templates, exports.
- `python -m trama_qt --smoke FOLDER --only qt-observation-labels`: the real window with screenshots, in English and Italian, light and dark, at 1024×768 and at an emulated 150 %.
- `tests/bench_observation_labels.py`: ten thousand points without labels and with a hundred.
- Data: `tests/data/observation_labels/` (`etichette-osservazioni.alab` and `casi.json`).
