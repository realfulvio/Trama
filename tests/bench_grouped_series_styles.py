"""Redraw benchmark on 50 categories × 12 series × 8 replicates for grouped series styles."""
import statistics
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analisi.category_graphs import INTERLEAVED, LINE_SYMBOLS, SERIES_STYLE, SYMBOLS, category_graph
from analisi.figure_export import export_figure
from analisi.presentation import apply_style


def make_dataset(categories=50, series_count=12, replicates=8, seed=42):
    rng = np.random.default_rng(seed)
    data = {"Categoria": [f"Cat_{i + 1:02d}" for i in range(categories)]}
    for s in range(series_count):
        for r in range(replicates):
            values = rng.normal(loc=5.0 + s * 0.6, scale=0.8, size=categories)
            data[f"Serie_{s + 1:02d} [{r + 1}]"] = values
    frame = pd.DataFrame(data)
    frame.attrs["worksheet_roles"] = {
        "x": ["Categoria"],
        "y": [[f"Serie_{s + 1:02d} [{r + 1}]" for r in range(replicates)] for s in range(series_count)],
    }
    return frame


def run_benchmark(repeats=3):
    frame = make_dataset()
    variables = [col for col in frame.columns if col != "Categoria"]
    base_opts = {
        "Variables": variables,
        "Row titles": "Categoria",
        "Interval": "SEM",
        "Placement of groups": INTERLEAVED,
    }
    mixed_opts = {
        **base_opts,
        SERIES_STYLE: {
            f"Serie_{s + 1:02d}": LINE_SYMBOLS if s % 2 == 0 else SYMBOLS
            for s in range(0, 12, 2)
        },
    }

    def measure(label, fn):
        samples = []
        last = None
        for _ in range(repeats):
            start = time.perf_counter()
            last = fn()
            samples.append((time.perf_counter() - start) * 1000.0)
        print(f"{label:<52} median={statistics.median(samples):7.1f} ms  min={min(samples):7.1f} ms")
        return last

    base_res = measure("50x12x8 global Bars (build)", lambda: category_graph(frame, base_opts, grouped=True))
    mix_res = measure("50x12x8 per-series mixed (build)", lambda: category_graph(frame, mixed_opts, grouped=True))
    measure(
        "50x12x8 mixed apply_style recolor + legend",
        lambda: apply_style(mix_res.figure, {"series": {"grouped:1:Serie_01": {"color": "#cc3311"}}}),
    )
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "mix_50x12.pdf"
        svg_path = Path(tmp) / "mix_50x12.svg"
        measure("50x12x8 mixed vector PDF export", lambda: export_figure(mix_res.figure, pdf_path, {"format": "pdf"}))
        measure("50x12x8 mixed vector SVG export",
                lambda: export_figure(mix_res.figure, svg_path, {"format": "svg", "svg_text": "text"}))
    return base_res, mix_res


if __name__ == "__main__":
    run_benchmark()
