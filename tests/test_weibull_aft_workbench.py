"""Weibull AFT regression through the dispatcher: registration, sheets, profile figure and exports."""
import io
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from analisi import weibull_aft as engine
from analisi import weibull_aft_workbench as aft
from analisi.field_error import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "weibull_aft"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = aft.WEIBULL_AFT
FOLLOW_UP = pd.read_csv(DATA / "follow-up.csv")
PROFILES = [{"Name": "Control", "Values": {"Treatment": 0}}, {"Name": "Treated", "Values": {"Treatment": 1}}]
TIMES = [0, 2, 4, 8]


def options(**changes):
    return {"Time": "Time", "Event": "Status", "Event value": "event", "Censor value": "censored",
            "Predictors": ["Treatment"], "Categorical predictors": [], "Shape mode": "Fixed", "Shape": 1.5, **changes}


def run(frame=None, **changes):
    return analyse(METHOD, FOLLOW_UP if frame is None else frame, options(**changes))


def profile_lines(figure):
    return {line.get_gid(): line for axes in figure.axes for line in axes.lines if line.get_gid()}


def exported(figure, fmt):
    buffer = io.BytesIO()
    figure.savefig(buffer, format=fmt)
    return buffer.getvalue()


def mixed(n=40, seed=7):
    rng = np.random.default_rng(seed)
    arm = rng.choice(["A", "B", "C"], n)
    time = rng.weibull(1.4, n) * np.exp(1.5 + 0.4 * (arm == "B") - 0.3 * (arm == "C"))
    return pd.DataFrame({"t": time, "d": (np.arange(n) % 3 != 0).astype(int), "x": rng.normal(5, 1, n), "arm": arm})


class RegistrationTests(unittest.TestCase):
    def test_the_method_sits_under_survival_analysis_and_has_a_graph(self):
        self.assertEqual(METHOD, "Weibull AFT regression")
        self.assertIn(METHOD, GROUPS["Survival Analysis"])
        self.assertIn(METHOD, METHODS)
        self.assertIn(METHOD, GRAPH_METHODS)

    def test_the_dialog_fields_are_the_specified_ones_in_order(self):
        self.assertEqual(list(METHODS[METHOD]), ["Time", "Event", "Event value", "Censor value", "Predictors",
                                                 "Categorical predictors", "Shape mode", "Shape",
                                                 "Confidence level (%)", "Profiles", "Times", "Show graph"])
        self.assertEqual(aft.DEFAULTS, {"Event value": "1", "Censor value": "0"})

    def test_the_shape_belongs_to_the_fixed_mode_only(self):
        self.assertEqual(aft.visibility("Fixed"), {"Shape": True})
        self.assertEqual(aft.visibility("Estimated ML"), {"Shape": False})

    def test_existing_survival_methods_keep_their_place_before_the_new_one(self):
        group = GROUPS["Survival Analysis"]
        self.assertEqual(group[:2], ("Kaplan–Meier survival", "Cox regression"))
        self.assertEqual(group.count(METHOD), 1)
        for name in group:
            self.assertIn(name, METHODS)


class SheetTests(unittest.TestCase):
    def test_a_plain_fit_has_three_sheets(self):
        result = run()
        self.assertEqual(list(result.tables), ["Coefficients", "Model fit", "Fitted survival"])
        self.assertIsNone(result.figure)

    def test_profiles_add_the_curves_and_categories_add_the_reference_levels(self):
        frame = mixed()
        result = analyse(METHOD, frame, {"Time": "t", "Event": "d", "Event value": "1", "Censor value": "0",
                                         "Predictors": ["x", "arm"], "Categorical predictors": ["arm"],
                                         "Shape mode": "Estimated ML",
                                         "Profiles": [{"Name": "P", "Values": {"x": 5, "arm": "B"}}]})
        self.assertEqual(list(result.tables), ["Coefficients", "Model fit", "Fitted survival", "Survival curves",
                                               "Reference levels"])
        self.assertEqual(result.tables["Reference levels"].loc["arm", "Reference"], "A")
        self.assertEqual(list(result.tables["Coefficients"].index),
                         ["Intercept", "x", "arm [B]", "arm [C]"])
        self.assertEqual(len(result.tables["Survival curves"]), 101)

    def test_every_sheet_has_a_real_column_set_and_the_worksheet_is_not_changed(self):
        before = FOLLOW_UP.copy(deep=True)
        result = run(Profiles=PROFILES, Times=TIMES)
        pd.testing.assert_frame_equal(FOLLOW_UP, before)
        self.assertEqual(list(result.tables["Coefficients"].columns),
                         ["Estimate", "SE", "p", "Lower", "Upper", "Time ratio", "Ratio lower", "Ratio upper"])
        self.assertEqual(list(result.tables["Fitted survival"].columns),
                         ["Source row", "Time", "Event", "Median time", "Survival at time"])
        self.assertEqual(list(result.tables["Survival curves"].columns),
                         ["Profile", "Time", "Survival", "Extrapolated"])
        for name, table in result.tables.items():
            if name != "Reference levels":
                self.assertTrue(isinstance(table.index, pd.RangeIndex) or list(table.index) == ["Intercept", "Treatment"],
                                name)

    def test_the_default_times_are_101_points_from_zero_to_the_longest_observed_time(self):
        table = run(Profiles=PROFILES).tables["Survival curves"]
        control = table[table["Profile"] == "Control"]
        self.assertEqual(len(control), 101)
        self.assertEqual(control["Time"].iloc[0], 0.0)
        self.assertEqual(control["Time"].iloc[-1], FOLLOW_UP["Time"].max())
        self.assertEqual(control["Survival"].iloc[0], 1.0)
        self.assertTrue((control["Extrapolated"] == "No").all())
        self.assertTrue(control["Survival"].is_monotonic_decreasing)

    def test_an_explicit_time_beyond_the_follow_up_is_flagged_as_extrapolated(self):
        self.assertEqual(FOLLOW_UP["Time"].max(), 17.0)
        table = run(Profiles=PROFILES, Times=[0, 2, 17, 20]).tables["Survival curves"]
        self.assertEqual(list(table["Extrapolated"][:4]), ["No", "No", "No", "Yes"])

    def test_curve_rows_follow_the_profile_order_then_the_time_order(self):
        table = run(Profiles=PROFILES, Times=TIMES).tables["Survival curves"]
        self.assertEqual(list(table["Profile"]), ["Control"] * 4 + ["Treated"] * 4)
        self.assertEqual(list(table["Time"]), TIMES * 2)
        np.testing.assert_allclose(table["Survival"].to_numpy().reshape(2, 4), EXPECTED["fixed"]["survival"],
                                   rtol=1e-9, atol=1e-12)

    def test_the_fit_sheet_states_the_rules_that_were_applied(self):
        fit = run().tables["Model fit"].iloc[0]
        self.assertEqual((fit["N"], fit["Events"], fit["Censored"], fit["Incomplete rows"]), (16, 10, 6, 0))
        self.assertEqual(fit["Shape mode"], "Fixed")
        self.assertEqual(fit["Parameters"], 2)
        self.assertTrue(np.isnan(fit["Shape lower"]))
        estimated = run(**{"Shape mode": "Estimated ML"}).tables["Model fit"].iloc[0]
        self.assertEqual(estimated["Parameters"], 3)
        self.assertLess(estimated["Shape lower"], estimated["Shape"])
        self.assertGreater(estimated["Shape upper"], estimated["Shape"])

    def test_missing_cells_are_dropped_and_counted_and_the_source_row_stays_physical(self):
        frame = FOLLOW_UP.copy()
        frame.loc[3, "Time"] = np.nan
        frame.loc[9, "Treatment"] = np.nan
        result = run(frame)
        self.assertEqual(result.tables["Model fit"].iloc[0]["Incomplete rows"], 2)
        self.assertEqual(list(result.tables["Fitted survival"]["Source row"]),
                         [r for r in range(1, 17) if r not in (4, 10)])

    def test_the_run_is_deterministic_and_fits_once(self):
        first, second = run(Profiles=PROFILES, Times=TIMES), run(Profiles=PROFILES, Times=TIMES)
        for name in first.tables:
            pd.testing.assert_frame_equal(first.tables[name], second.tables[name])


class OptionTests(unittest.TestCase):
    def raised(self, **changes):
        with self.assertRaises(FieldError) as caught:
            run(**changes)
        return caught.exception

    def test_errors_belong_to_the_field_that_must_change(self):
        self.assertEqual(self.raised(Time="Missing").field, "Time")
        self.assertEqual(self.raised(Event="Time").field, "Event")
        # A cell that matches neither code is the column's problem (Cox convention); a text code for a numeric column
        # is the code's.
        self.assertEqual(self.raised(**{"Event value": "oops"}).field, "Event")
        coded = FOLLOW_UP.assign(Status=lambda f: (f["Status"] == "event").astype(int))
        with self.assertRaises(FieldError) as caught:
            run(coded, **{"Event value": "yes", "Censor value": "0"})
        self.assertEqual(caught.exception.field, "Event value")
        self.assertEqual(self.raised(**{"Censor value": "event"}).field, "Censor value")
        self.assertEqual(self.raised(Predictors=["Time"]).field, "Predictors")
        self.assertEqual(self.raised(**{"Shape": 100}).field, "Shape")
        self.assertEqual(self.raised(**{"Confidence level (%)": 100}).field, "Confidence level (%)")
        self.assertEqual(self.raised(**{"Show graph": True}).field, "Profiles")
        self.assertEqual(self.raised(Profiles=PROFILES, Times=[0, 8, 2]).field, "Times")

    def test_a_hidden_shape_is_never_validated(self):
        result = run(**{"Shape mode": "Estimated ML", "Shape": "not a number"})
        self.assertEqual(result.tables["Model fit"].iloc[0]["Shape mode"], "Estimated ML")

    def test_a_missing_key_takes_its_default(self):
        short = analyse(METHOD, FOLLOW_UP.assign(Status=lambda f: (f["Status"] == "event").astype(int)),
                        {"Time": "Time", "Event": "Status", "Predictors": ["Treatment"]})
        self.assertEqual(short.tables["Model fit"].iloc[0]["Events"], 10)

    def test_the_budgets_are_checked_without_a_fit(self):
        profiles = [{"Name": f"P{i}", "Values": {"Treatment": i % 2}} for i in range(12)]
        with self.assertRaises(FieldError) as caught:
            aft.check_options(FOLLOW_UP, options(Profiles=profiles, Times=list(np.arange(1.0, 420))))
        self.assertEqual(caught.exception.field, "Times")
        self.assertEqual(engine.MAX_CURVE_PAIRS, 5_000)


class FigureTests(unittest.TestCase):
    def test_one_vector_line_per_profile_through_the_points_of_the_sheet(self):
        result = run(Profiles=PROFILES, Times=TIMES, **{"Show graph": True})
        figure = result.figure
        self.assertEqual(len(figure.axes), 1)
        found = profile_lines(figure)
        self.assertEqual(sorted(found), ["aft-profile-1", "aft-profile-2"])
        for index, values in enumerate(EXPECTED["fixed"]["survival"], 1):
            line = found[f"aft-profile-{index}"]
            np.testing.assert_allclose(line.get_xdata(), TIMES)
            np.testing.assert_allclose(line.get_ydata(), values, rtol=1e-9, atol=1e-12)
        self.assertEqual(figure.axes[0].get_ylim(), (0.0, 1.0))
        self.assertEqual(figure.axes[0]._tramastat_numeric_axes, ("x", "y"))

    def test_labels_are_the_worksheet_names_and_are_not_parsed_as_math(self):
        profiles = [{"Name": "$a$ & {b}", "Values": {"Treatment": 0}}, {"Name": "B", "Values": {"Treatment": 1}}]
        frame = FOLLOW_UP.rename(columns={"Time": "T$1"})
        figure = analyse(METHOD, frame, options(Time="T$1", Profiles=profiles, Times=TIMES, **{"Show graph": True})).figure
        axes = figure.axes[0]
        self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()][:2], ["$a$ & {b}", "B"])
        self.assertEqual(axes.get_xlabel(), "T$1")
        for text in (axes.title, axes.xaxis.label, axes.yaxis.label, *axes.get_legend().get_texts()):
            self.assertFalse(text.get_parse_math())

    def test_the_default_curve_starts_at_one_and_the_extrapolated_band_appears_only_beyond_the_follow_up(self):
        inside = run(Profiles=PROFILES, **{"Show graph": True}).figure.axes[0]
        self.assertEqual([patch for patch in inside.patches if patch.get_gid() == "aft-extrapolated"], [])
        line = profile_lines(inside.figure)["aft-profile-1"]
        self.assertEqual(line.get_ydata()[0], 1.0)
        self.assertEqual(len(line.get_xdata()), 101)
        self.assertEqual(line.get_marker(), "None")
        beyond = run(Profiles=PROFILES, Times=[0, 4, 20], **{"Show graph": True}).figure.axes[0]
        spans = [patch for patch in beyond.patches if patch.get_gid() == "aft-extrapolated"]
        self.assertEqual(len(spans), 1)
        self.assertIn("Extrapolated", [t.get_text() for t in beyond.get_legend().get_texts()][-1])
        self.assertEqual(profile_lines(beyond.figure)["aft-profile-1"].get_marker(), "o")

    def test_more_profiles_than_colours_change_the_dash_not_only_the_colour(self):
        profiles = [{"Name": f"P{i}", "Values": {"Treatment": i % 2}} for i in range(12)]
        found = profile_lines(run(Profiles=profiles, Times=TIMES, **{"Show graph": True}).figure)
        self.assertEqual(len(found), 12)
        styles = {(line.get_color(), line.get_linestyle()) for line in found.values()}
        self.assertEqual(len(styles), 12)

    def test_no_figure_without_the_switch(self):
        self.assertIsNone(run(Profiles=PROFILES, Times=TIMES).figure)

    def test_exports_keep_the_lines_as_vector_paths(self):
        figure = run(Profiles=PROFILES, Times=TIMES, **{"Show graph": True}).figure
        svg = exported(figure, "svg")
        self.assertIn(b'id="aft-profile-1"', svg)
        self.assertIn(b"aft-profile-2", svg)
        self.assertNotIn(b"<image", svg)
        pdf = exported(figure, "pdf")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertNotIn(b"/Subtype /Image", pdf)
        png = exported(figure, "png")
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertGreater(len(png), 1000)

    def test_the_tables_export_to_csv_with_every_value(self):
        result = run(Profiles=PROFILES, Times=TIMES)
        for name, table in result.tables.items():
            text = table.to_csv(index=name in ("Coefficients", "Reference levels"))
            self.assertGreater(len(text.splitlines()), 1, name)
        curves = pd.read_csv(io.StringIO(result.tables["Survival curves"].to_csv(index=False)))
        np.testing.assert_allclose(curves["Survival"], result.tables["Survival curves"]["Survival"], rtol=1e-12)


if __name__ == "__main__":
    unittest.main()
