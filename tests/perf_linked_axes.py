"""Cost of the linked secondary axes on a graph of 10,000 points: ``python tests/perf_linked_axes.py [FILE]``.

Times, as the median of several rounds on synthetic data:

- the first draw of the graph as calculated (the base);
- ``apply_style`` + draw without linked axes, and with a top X and a right Y axis (the style is applied the way the
  window applies it on formatting);
- the steady redraw of the formatted graph (what a pan or a zoom costs), without and with both axes;
- 20 successive formats with the linked axes (never more than two secondary axes), and the SVG export.

The 10,000 points are drawn as markers only, then as a line with markers, which is the slower case. Nothing here
changes the data; the numbers are only meaningful when both rows are measured on the same machine in one run.
"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import statistics
import sys
import time

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analisi.presentation import apply_style  # noqa: E402
from analisi.xy_series import xy_series  # noqa: E402

POINTS, ROUNDS = 10_000, 7
BOTH = {"x": {"multiplier": 1.8, "offset": 32.0, "label": "Temperature (°F)"},
        "y": {"multiplier": 1 / 60, "offset": 0.0, "label": "Time (min)"}}


def frame():
    rng = np.random.default_rng(11)
    x = np.sort(rng.uniform(0, 40, POINTS))
    return pd.DataFrame({"x": x, "y": 120 + 3.2 * x - 0.025 * x ** 2 + rng.normal(0, 4, POINTS)})


def figure(data, style):
    return xy_series(data, {"X": "x", "Y columns": ["y"], "Series style": {"y": style}}).figure


def timed(function):
    start = time.perf_counter()
    function()
    return time.perf_counter() - start


def median(function, rounds=ROUNDS):
    return statistics.median(timed(function) for _ in range(rounds))


def draw(fig):
    FigureCanvasAgg(fig).draw()


def measure(data, style):
    rows = {}
    rows["first draw as calculated"] = median(lambda: draw(figure(data, style)))

    def formatted(record):
        fig = figure(data, style)
        apply_style(fig, {"linked_axes": deepcopy(record)} if record else {"title": "Same style"})
        draw(fig)

    rows["apply_style + draw, no linked axes"] = median(lambda: formatted(None))
    rows["apply_style + draw, top X and right Y"] = median(lambda: formatted(BOTH))
    plain, linked = figure(data, style), figure(data, style)
    apply_style(plain, {"title": "Same style"})
    apply_style(linked, {"linked_axes": deepcopy(BOTH)})
    draw(plain)
    draw(linked)
    rows["redraw (pan or zoom), no linked axes"] = median(lambda: (plain.axes[0].set_xlim(2, 30), draw(plain)))
    rows["redraw (pan or zoom), top X and right Y"] = median(lambda: (linked.axes[0].set_xlim(2, 30), draw(linked)))

    def twenty():
        fig = figure(data, style)
        for index in range(20):
            record = deepcopy(BOTH)
            record["x"]["label"] = f"round {index}"
            apply_style(fig, {"linked_axes": record})
        draw(fig)
        assert len(fig.axes[0].child_axes) == 2, len(fig.axes[0].child_axes)

    rows["20 formats with both axes, then draw"] = median(twenty, 3)
    rows["SVG export, top X and right Y"] = median(lambda: linked.savefig(BytesIO(), format="svg"), 3)
    return rows


def main():
    data = frame()
    lines = [f"Linked secondary axes · {POINTS:,} points · median of {ROUNDS} rounds (3 for the last two rows) · "
             f"matplotlib {matplotlib.__version__}"]
    for name, style in (("Points", "Points"), ("Line and points", "Line and points")):
        lines += ["", f"Series style: {name}"]
        rows = measure(data, style)
        width = max(len(label) for label in rows)
        lines += [f"  {label.ljust(width)}  {seconds * 1000:9.1f} ms" for label, seconds in rows.items()]
        base = rows["redraw (pan or zoom), no linked axes"]
        extra = rows["redraw (pan or zoom), top X and right Y"] - base
        lines.append(f"  → a redraw costs {extra * 1000:+.1f} ms ({extra / base:+.0%}) with both secondary axes")
    text = "\n".join(lines) + "\n"
    print(text)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
