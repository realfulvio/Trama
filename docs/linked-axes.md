# Linked Secondary Axes

A linked secondary axis shows the **same coordinate in a second unit**, on the top edge of the graph (a second X axis) or on the right edge (a second Y axis): degrees Celsius below and Fahrenheit above, seconds on the left and minutes on the right, micromolar below and millimolar above. It is a presentation setting. No series, worksheet, calculation, fit or table changes, and the secondary axis never plots data of its own.

The value on the secondary axis is always

```
secondary = multiplier × primary + offset
```

The multiplier is finite and strictly greater than 0, so the conversion is increasing and invertible. Only unit changes of this kind are covered: a conversion that is not a straight line (a reciprocal, a logarithm, dB) is not offered.

## Where to find it

- **Format Graph → Axes → Secondary axes…** (`Assi secondari…`) in the group *Linked secondary axes* (`Assi secondari sincronizzati`). The line beside the button summarises what is on (*top X, right Y* or *None*), and says why an axis is unavailable when it is.
- **Graph Inspector → Axes → Secondary axes…**, inside the current Inspector draft. The editor previews the axes on the live graph; **Apply** in the Inspector confirms them, **Cancel** closes the panel and restores the confirmed graph. **Reset section** of the Axes section removes the secondary axes with the other axis settings.

The editor has one group per axis, switched on with its check box:

| Field | Meaning |
| --- | --- |
| Label (`Etichetta`) | Name of the secondary axis, up to 160 characters, no line breaks or control characters. Unicode, µ and `$math$` are accepted. It takes the font, size and colour of the primary axis title. |
| Multiplier (`Moltiplicatore`) | A finite number greater than 0. |
| Offset (`Scostamento`) | A finite number. |

Under the fields, **Reference values** shows two primary values (the first and the last visible major tick) and what the secondary axis will show for them, so an error in the factor is visible before Apply. A decimal comma works in both languages. A wrong value keeps the editor open, names the problem in the active language and puts the focus on the field.

## Which graphs

| Graph | Top X | Right Y |
| --- | --- | --- |
| XY series, XY error bars, global fits drawn as XY series | yes | yes |
| Linear, Deming, Nonlinear, Robust, Spline/LOWESS, custom-equation and global custom-equation fits, Compare regression lines | yes | yes |
| Kaplan–Meier survival (also with the risk table below) | yes | yes |
| Column graph and Grouped graph | no (categories) | yes (value axis) |
| Any other graph, an imported picture | no | no |

The axis must be numeric, linear or logarithmic.

## Saved style

The secondary axes are one section of the graph style, stored in the project like the other style sections. An axis that is absent is off.

```json
{
  "linked_axes": {
    "x": {"multiplier": 1.8, "offset": 32.0, "label": "Temperature (°F)"},
    "y": {"multiplier": 0.016666666666666666, "offset": 0.0, "label": "Time (min)"}
  }
}
```

- Only the keys `x` and `y` are accepted; each record has exactly `multiplier`, `offset` and `label`. A record that does not fit is refused before anything on the graph changes, and the message names the axis and the field.
- A project without the section opens exactly as before.
- The Tk classic window has no editor for it. It keeps the record of a project when it formats a graph, so nothing is lost by opening the project there.

## How it behaves

- **Real axes.** The secondary axes are Matplotlib secondary axes attached to the graph's own Axes, with the stable ids `trama-linked-x` and `trama-linked-y` in SVG. Their limits are recomputed at every draw from the primary axis, so **pan, zoom, inversion, dialog edits, recalculation and reset** always agree with the primary axis, without a callback. Zooming far outside the validated range never raises an error.
- **No stacking.** Formatting again replaces the old axes: twenty formats never leave more than one secondary axis per side.
- **Layout.** The labels sit outside the plot like the primary ones and the graph keeps the layout of the application (the title stays above the top axis). The grid, reference lines, guides, shaded ranges, notes and shapes belong to the primary axes and are not repeated.
- **Logarithmic primary axis.** Only a change of unit makes sense there, so the offset must be 0 (the editor fixes it at 0 and says so). A style that chooses the logarithmic scale and an offset together is refused with that message.
- **Exports.** PNG, SVG, PDF and layout pages carry the secondary axes; SVG and PDF stay vector.
- **Survival curves.** When the Kaplan–Meier *Curve* or *Display units* changes, the right Y record is dropped, because the unit chosen for the old quantity no longer holds; the top X record stays.

## When an axis cannot be shown

An axis the graph cannot show right now is **kept in the style and left out**: the graph is drawn without it, the status bar and the Inspector say why, and it comes back as soon as the graph allows it. In Format Graph the same cases disable the controls of that axis with the reason beside them, and an axis that is already saved on a graph that cannot show it can only be switched off. The reasons are:

- the graph type has no linked axes, or it is an imported picture;
- the axis is categorical or uses units (dates), or its scale is neither linear nor logarithmic;
- **axis breaks** are on: breaks win, remove them first;
- the graph has an **independent right Y axis** (a series on the right): the linked right Y is refused, the top X stays available;
- the graph has more than one plot panel;
- a logarithmic axis with an offset in the saved record;
- the converted limits overflow or collapse (for example a multiplier of 10¹⁰ on an axis that reaches 10³⁰⁰).

## Performance

Measured with `python tests/perf_linked_axes.py` on 10,000 synthetic points (Agg, the graph's constrained layout, median of 7 rounds, one machine, no other load):

| | no linked axes | top X and right Y |
| --- | --- | --- |
| Redraw of the formatted graph, points (what a pan or a zoom costs) | 50 ms | 121 ms |
| Redraw of the formatted graph, line and points | 82 ms | 132 ms |
| Apply the style and draw once, points | 95 ms | 186 ms |
| 20 successive formats with both axes, then one draw | | 349 ms (never more than two secondary axes) |
| SVG export | | 278 ms |

The extra time comes from the two extra axes (their ticks and the layout), not from the points: with 100 points the added cost is of the same order. A top X axis alone adds about 40 ms to a redraw at 10,000 points, the right Y axis about the same.

## Tests and acceptance

- `tests/test_linked_axes.py`: record rules, conversion, drawing on every supported graph, the cases that must not draw, extreme limits, pickling, exports and layouts, IT/EN catalog.
- `tests/test_qt_linked_axes.py`: Format Graph, Inspector and editor, offscreen.
- `python -m trama_qt.linked_axes_smoke FOLDER [--dark] [--size WIDTHxHEIGHT]`: the real window in English and Italian, with screenshots of the top axis, the right axis, the offset constraint on a logarithmic axis and a graph that cannot take the axis. Windows and system DPI scaling are not covered by the offscreen run and stay to be tried on the desktop.
