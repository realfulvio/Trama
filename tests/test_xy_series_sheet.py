"""The XY points sheet is built column-wise with the same content and dtypes as one dict per point (0.111.x)."""
import time
import unittest

import numpy as np
import pandas as pd

from analisi.xy_series import SHEET, SOURCE_ROW, Y_COLUMN, _drawn, _numbers, _source_label, xy_series


def reference_sheet(frame, options, log=False):
    rows = []
    x = _numbers(frame, options["X"])
    for column in options["Y columns"]:
        y = _numbers(frame, column)
        for position, keep in enumerate(_drawn(x, y, log)):
            if keep:
                rows.append({SOURCE_ROW: _source_label(frame.index[position]), "X": float(x[position]),
                             Y_COLUMN: column, "Y": float(y[position])})
    return pd.DataFrame(rows, columns=[SOURCE_ROW, "X", Y_COLUMN, "Y"])


class XYSheetTest(unittest.TestCase):
    def frames(self):
        rng = np.random.default_rng(3)
        base = pd.DataFrame({"X": rng.normal(size=40), "A": rng.normal(size=40), "B": np.abs(rng.normal(size=40))})
        base.loc[3, "A"] = np.nan
        base.loc[5, "X"] = np.nan
        yield base, False
        yield base.set_axis([f"r{i}" for i in range(40)]), False
        yield base.set_axis([i // 2 for i in range(40)]), False
        yield base.set_axis(pd.Index([1, "a", 2.5, *range(3, 40)], dtype=object)), False
        yield base.assign(B=base["B"].where(base.index % 4 > 0, -1.0)), True

    def test_same_sheet_as_one_dict_per_point(self):
        for frame, log in self.frames():
            options = {"X": "X", "Y columns": ["A", "B"]}
            sheet = xy_series(frame, dict(options), "log" if log else "linear").tables[SHEET]
            pd.testing.assert_frame_equal(sheet, reference_sheet(frame, options, log), check_exact=True)

    def test_many_points_are_quick(self):
        rng = np.random.default_rng(4)
        frame = pd.DataFrame({"X": rng.uniform(size=300_000), "Y": rng.normal(size=300_000)})
        started = time.perf_counter()
        sheet = xy_series(frame, {"X": "X", "Y columns": ["Y"]}).tables[SHEET]
        self.assertLess(time.perf_counter() - started, 3)
        self.assertEqual(len(sheet), 300_000)


if __name__ == "__main__":
    unittest.main()
