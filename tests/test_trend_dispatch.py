"""One-way ANOVA exposes the ordinal trend without changing a recipe that leaves it off."""
import unittest

import numpy as np
import pandas as pd

from analisi.processing import FieldError
from analisi.trend_anova import ORDER, TREND
from analisi.workbench import METHODS, analyse


def _order(*labels):
    return [{"kind": "text", "value": label} for label in labels]


def _frame():
    groups = ("10", "10", "10", "1", "1", "1", "100", "100", "100", "3", "3", "3")
    values = [1, 2, 3, 3, 4, 5, 4, 5, 6, 8, 9, 10]
    return pd.DataFrame({"group": list(groups), "y": values})


def _base():
    return {"Response": "y", "Group": "group", "Method": "Ordinary", "Post-hoc": "Tukey"}


class TrendDispatchTests(unittest.TestCase):
    def test_the_option_defaults_off_and_a_stale_order_is_ignored(self):
        self.assertIs(METHODS["One-way ANOVA"][TREND], False)
        self.assertEqual(METHODS["One-way ANOVA"][ORDER], "Trend order")
        frame = _frame()
        before = frame.copy(deep=True)
        missing = analyse("One-way ANOVA", frame, _base())
        stale = analyse("One-way ANOVA", frame, {**_base(), TREND: False, ORDER: [{"kind": "text", "value": "stale"}]})
        self.assertEqual(list(missing.tables), list(stale.tables))
        self.assertNotIn("Linear trend", missing.tables)
        for name in missing.tables:
            pd.testing.assert_frame_equal(missing.tables[name], stale.tables[name])
        pd.testing.assert_frame_equal(frame, before)

    def test_trend_appends_sheets_and_keeps_tukey(self):
        frame = _frame()
        order = _order("10", "1", "100", "3")
        off = analyse("One-way ANOVA", frame, _base())
        on = analyse("One-way ANOVA", frame, {**_base(), TREND: True, ORDER: order})
        self.assertEqual(list(on.tables)[:len(off.tables)], list(off.tables))
        for name in off.tables:
            pd.testing.assert_frame_equal(off.tables[name], on.tables[name])
        metrics = on.tables["Linear trend"]["Value"].to_dict()
        self.assertAlmostEqual(metrics["Slope"], 2.2)
        self.assertIn("ordinal", metrics["Convention"])
        means = on.tables["Trend group means"]
        self.assertEqual(means["Score"].tolist(), [1, 2, 3, 4])
        self.assertEqual(means["Group value"].tolist(), ["10", "1", "100", "3"])
        reversed_order = analyse("One-way ANOVA", frame, {**_base(), TREND: True, ORDER: list(reversed(order))})
        flipped = reversed_order.tables["Linear trend"]["Value"].to_dict()
        self.assertAlmostEqual(flipped["Slope"], -2.2)
        self.assertAlmostEqual(flipped["p linear"], metrics["p linear"])

    def test_incompatible_methods_and_bad_orders_name_their_field(self):
        frame = _frame()
        order = _order("10", "1", "100", "3")
        for method in ("Welch", "Welch and Brown–Forsythe"):
            with self.assertRaises(FieldError) as caught:
                analyse("One-way ANOVA", frame, {**_base(), "Post-hoc": "None", "Method": method,
                                                 TREND: True, ORDER: order})
            self.assertEqual(caught.exception.field, TREND)
            self.assertIn("ordinary", str(caught.exception))
        for method in ("Repeated measures ANOVA", "Multifactor ANOVA"):
            with self.assertRaises(FieldError) as caught:
                analyse(method, frame, {**_base(), TREND: True, ORDER: order})
            self.assertEqual(caught.exception.field, TREND)
        with self.assertRaises(FieldError) as caught:
            analyse("One-way ANOVA", frame, {**_base(), TREND: True, ORDER: ["10", "1", "100", "3"]})
        self.assertEqual(caught.exception.field, ORDER)
        constant = frame.copy()
        constant["y"] = 1.0
        with self.assertRaises(FieldError) as caught:
            analyse("One-way ANOVA", constant, {**_base(), "Post-hoc": "None", TREND: True, ORDER: order})
        self.assertEqual(caught.exception.field, TREND)
        # The same constant column without the trend still uses the legacy error.
        with self.assertRaises(ValueError) as legacy:
            analyse("One-way ANOVA", constant, {**_base(), "Post-hoc": "None"})
        self.assertNotIsInstance(legacy.exception, FieldError)

    def test_two_groups_omit_the_nonlinear_p_and_bool_groups_stay_legacy(self):
        frame = _frame()
        small = frame[frame["group"].isin(["10", "1"])]
        result = analyse("One-way ANOVA", small, {**_base(), TREND: True, ORDER: _order("10", "1")})
        metrics = result.tables["Linear trend"]["Value"].to_dict()
        self.assertTrue(np.isnan(metrics["p nonlinear"]))
        self.assertIn("four", metrics["Note"])
        flags = pd.DataFrame({"group": [True, True, False, False], "y": [1.0, 2, 3, 4]})
        legacy = analyse("One-way ANOVA", flags, {**_base(), "Post-hoc": "None"})
        self.assertIn("ANOVA", legacy.tables)
        with self.assertRaises(FieldError) as caught:
            analyse("One-way ANOVA", flags, {**_base(), "Post-hoc": "None", TREND: True,
                                             ORDER: [{"kind": "text", "value": "True"}]})
        self.assertEqual(caught.exception.field, TREND)


if __name__ == "__main__":
    unittest.main()
