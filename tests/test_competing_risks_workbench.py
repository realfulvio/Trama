"""Competing risks through the dispatcher: options, sheets, figure and cancellation."""
import io
import json
from pathlib import Path
import threading
import unittest

import numpy as np
import pandas as pd

from analisi import competing_risks as engine
from analisi import competing_risks_workbench as cr
from analisi.field_error import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "competing_risks"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
METHOD = cr.COMPETING_RISKS


def fixture(name):
    kinds = {"Outcome": str, "Cohort": str} if name == "status-text" else None
    return pd.read_csv(DATA / f"{name}.csv", dtype=kinds)


def run(name, **overrides):
    return analyse(METHOD, fixture(name), {**EXPECTED[name]["options"], **overrides})


def synthetic(groups, causes, per_group=4, seed=1):
    rng = np.random.default_rng(seed)
    n = groups * per_group
    return pd.DataFrame({"t": rng.permutation(np.arange(1.0, n + 1)), "s": rng.integers(0, causes + 1, n),
                         "g": [f"G{i % groups}" for i in range(n)]})


def options(**changes):
    return {"Time": "t", "Status": "s", "Group": "g", "Censor code": "0", "Event codes": ["1", "2"], **changes}


def lines(figure):
    return {line.get_gid(): line for axes in figure.axes for line in axes.lines if line.get_gid()}


def bands(figure):
    return {item.get_gid(): item for axes in figure.axes for item in axes.collections if item.get_gid()}


class RegistrationTests(unittest.TestCase):
    def test_the_method_sits_under_survival_analysis_and_has_a_graph(self):
        self.assertIn(METHOD, GROUPS["Survival Analysis"])
        self.assertIn(METHOD, METHODS)
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertEqual(list(METHODS[METHOD]), [cr.TIME, cr.STATUS, cr.GROUP, cr.CENSOR, cr.EVENTS, cr.TIMES, cr.LEVEL,
                                                  cr.GRAY, cr.GRAPH, cr.GRAPH_CAUSE, cr.DISPLAY, cr.BANDS])

    def test_kind_names_agree_with_the_dialog_vocabulary(self):
        from analisi import workbench
        self.assertEqual(METHODS[METHOD][cr.GROUP], workbench.OPTIONAL)
        self.assertEqual(METHODS[METHOD][cr.CENSOR], workbench.TEXT)

    def test_defaults_are_the_documented_ones(self):
        self.assertEqual(cr.DEFAULTS, {"Censor code": "0", "Event codes": ["1", "2"], "Times": [],
                                       "Confidence level (%)": 95.0, "Gray tests": "Off", "Graph": "Selected cause",
                                       "Graph cause": "", "Display": "Fraction", "Show confidence bands": False})
        short = analyse(METHOD, fixture("ties"), {"Time": "Time", "Status": "Status"})
        self.assertEqual(list(short.tables), ["Cumulative incidence", "Settings"])

    def test_gray_makes_a_run_cancellable(self):
        self.assertFalse(cr.cancellable(METHOD, {"Gray tests": "Off"}))
        self.assertFalse(cr.cancellable(METHOD, {}))
        self.assertTrue(cr.cancellable(METHOD, {"Gray tests": "Omnibus"}))
        self.assertFalse(cr.cancellable("Cox regression", {"Gray tests": "Omnibus"}))


class SheetTests(unittest.TestCase):
    def test_sheet_names_follow_the_requested_options_in_a_fixed_order(self):
        self.assertEqual(list(run("cohorts", Times=[1]).tables), ["Cumulative incidence", "Time estimates", "Settings"])
        every = run("cohorts", Times=[1], **{"Gray tests": "Omnibus and pairwise"}).tables
        self.assertEqual(list(every), ["Cumulative incidence", "Time estimates", "Gray tests", "Gray pairwise",
                                       "Settings"])
        self.assertEqual(list(run("cohorts", **{"Gray tests": "Omnibus", "Times": []}).tables),
                         ["Cumulative incidence", "Gray tests", "Settings"])

    def test_every_sheet_has_a_range_index_and_real_columns(self):
        result = run("cohorts", Times=[1, 2], **{"Gray tests": "Omnibus and pairwise"})
        for name, table in result.tables.items():
            with self.subTest(name):
                self.assertIsInstance(table.index, pd.RangeIndex)
        self.assertEqual(list(result.tables["Cumulative incidence"].columns), cr.CURVE_COLUMNS)
        self.assertEqual(list(result.tables["Time estimates"].columns), cr.TIME_COLUMNS)
        self.assertEqual(list(result.tables["Gray tests"].columns), cr.GRAY_COLUMNS)
        self.assertEqual(list(result.tables["Gray pairwise"].columns), cr.PAIR_COLUMNS)
        self.assertEqual(list(result.tables["Settings"].columns), ["Setting", "Value"])

    def test_curve_rows_are_group_then_time_then_declared_cause(self):
        table = run("cohorts").tables["Cumulative incidence"]
        order = [(group, time, cause) for group, time, cause in zip(table["Group"], table["Time"], table["Cause"])]
        self.assertEqual(order, sorted(order, key=lambda row: (["A", "B", "C"].index(row[0]), row[1], row[2])))
        counts = table.groupby("Group", sort=False).size().tolist()
        self.assertEqual(sum(counts), len(table))
        self.assertTrue(all(count % 2 == 0 for count in counts))
        for column in ("At risk", "Cause events", "All events", "Censored"):
            self.assertTrue(pd.api.types.is_integer_dtype(table[column]), column)

    def test_probability_mass_closes_to_one_at_every_time(self):
        table = run("status-text").tables["Cumulative incidence"]
        for _, block in table.groupby(["Group", "Time"], sort=False):
            self.assertAlmostEqual(block["Event-free"].iloc[0] + block["CIF"].sum(), 1.0, places=12)

    def test_time_estimates_keep_the_request_order_and_repeats(self):
        result = run("ties", Times=[3, 1, 1, 6, 0, 0.5, 99]).tables["Time estimates"]
        self.assertEqual(result["Time"].tolist()[::2], [3, 1, 1, 6, 0, 0.5, 99])
        self.assertEqual(result["Cause"].tolist(), ["1", "2"] * 7)
        beyond = result[result["Time"] == 99]
        self.assertEqual(beyond["Status"].tolist(), ["Beyond follow-up"] * 2)
        self.assertTrue(beyond[["CIF", "Variance", "CI lower", "CI upper"]].isna().all().all())
        before = result[result["Time"] == 0.5]
        self.assertEqual(before["CIF"].tolist(), [0.0, 0.0])
        self.assertEqual(before["Variance"].tolist(), [0.0, 0.0])
        self.assertEqual(before["Status"].tolist(), ["CI unavailable"] * 2)
        at_jump = result[result["Time"] == 1]
        self.assertEqual(at_jump["CIF"].round(12).tolist(), [round(1 / 7, 12)] * 4)

    def test_gray_sheets_with_one_group_say_why(self):
        result = run("ties", **{"Gray tests": "Omnibus and pairwise"})
        gray = result.tables["Gray tests"]
        self.assertEqual(gray["Status"].tolist(), ["Unavailable", "Unavailable"])
        self.assertTrue(all("two groups" in reason for reason in gray["Reason"]))
        self.assertTrue(gray[["Chi square", "df", "p"]].isna().all().all())
        self.assertEqual(len(result.tables["Gray pairwise"]), 0)
        self.assertEqual(list(result.tables["Gray pairwise"].columns), cr.PAIR_COLUMNS)

    def test_holm_runs_over_available_pairs_inside_each_cause(self):
        table = run("status-text", **{"Gray tests": "Omnibus and pairwise"}).tables["Gray pairwise"]
        self.assertEqual(table["Cause"].tolist(), ["ritiro", "guasto", "altro"])
        altro = table[table["Cause"] == "altro"].iloc[0]
        self.assertEqual(altro["Status"], "Unavailable")
        self.assertTrue(np.isnan(altro["Adjusted p"]) and np.isnan(altro["p"]))
        available = table[table["Status"] == "OK"]
        np.testing.assert_allclose(available["Adjusted p"], available["p"])

    def test_all_censored_data_gives_zero_curves_and_unavailable_tests(self):
        result = run("no-events", **{"Gray tests": "Omnibus and pairwise"})
        curves = result.tables["Cumulative incidence"]
        self.assertTrue((curves["CIF"] == 0).all() and (curves["Variance"] == 0).all())
        self.assertTrue(curves[["CI lower", "CI upper"]].isna().all().all())
        self.assertTrue((result.tables["Gray tests"]["Status"] == "Unavailable").all())

    def test_settings_state_the_rules(self):
        table = run("cohorts", **{"Confidence level (%)": 90, "Gray tests": "Omnibus"}).tables["Settings"]
        values = dict(zip(table["Setting"], table["Value"]))
        self.assertEqual((int(values["Complete cases"]), int(values["Omitted cases"])), (27, 3))
        self.assertEqual(values["CI level (%)"], 90)
        for key in ("CI method", "Variance method", "Ties convention", "Gray method", "Multiplicity"):
            self.assertTrue(str(values[key]).strip(), key)
        self.assertIn("pointwise", values["CI method"].lower())
        self.assertIn("90%", values["CI method"])

    def test_a_group_label_with_a_dollar_sign_is_kept_literally(self):
        frame = pd.DataFrame({"t": [1.0, 2.0, 3.0, 4.0], "s": [1, 0, 2, 1], "g": ["$a$", "$a$", "b$", "b$"]})
        result = analyse(METHOD, frame, options())
        self.assertEqual(sorted(result.tables["Cumulative incidence"]["Group"].unique()), ["$a$", "b$"])
        for axes in result.figure.axes:
            for text in [axes.title, axes.xaxis.label, axes.yaxis.label, *axes.get_legend().get_texts()]:
                self.assertFalse(text.get_parse_math(), text.get_text())

    def test_the_worksheet_is_not_modified(self):
        frame = fixture("cohorts")
        before = frame.copy(deep=True)
        analyse(METHOD, frame, {**EXPECTED["cohorts"]["options"], "Gray tests": "Omnibus and pairwise"})
        pd.testing.assert_frame_equal(frame, before)

    def test_excluded_cells_arrive_as_missing_values_and_are_omitted(self):
        frame = pd.DataFrame({"t": pd.array([1, 2, 3, 4, 5, 6], dtype="Int64"),
                              "s": pd.array([1, 0, 2, pd.NA, 1, 0], dtype="Int64"),
                              "g": pd.array(["A", "A", "B", "B", pd.NA, "B"], dtype="string")})
        result = analyse(METHOD, frame, options())
        settings = dict(zip(result.tables["Settings"]["Setting"], result.tables["Settings"]["Value"]))
        self.assertEqual((settings["Complete cases"], settings["Omitted cases"]), (4, 2))


class OptionTests(unittest.TestCase):
    def assertField(self, field, **changes):
        with self.assertRaises(FieldError) as error:
            analyse(METHOD, synthetic(2, 2), options(**changes))
        self.assertEqual(error.exception.field, field, str(error.exception))
        return str(error.exception)

    def test_times_are_checked_value_by_value(self):
        for bad in ([-1], [1, float("inf")], [float("nan")], [True], ["abc"], [None], "1,2", 5):
            with self.subTest(bad):
                self.assertField("Times", Times=bad)
        self.assertField("Times", Times=[1.0] * 201)
        analyse(METHOD, synthetic(2, 2), options(Times=[1.0] * 200))
        self.assertIn("value 2", self.assertField("Times", Times=[1, -2]))

    def test_confidence_level_is_strictly_between_zero_and_one_hundred(self):
        for bad in (0, 100, -5, 120, float("nan"), True, "95", None):
            with self.subTest(bad):
                self.assertField("Confidence level (%)", **{"Confidence level (%)": bad})
        analyse(METHOD, synthetic(2, 2), options(**{"Confidence level (%)": 99.9}))

    def test_choices_and_flags(self):
        self.assertField("Gray tests", **{"Gray tests": "all"})
        self.assertField("Graph", Graph="Both")
        self.assertField("Display", Display="percent")
        self.assertField("Show confidence bands", **{"Show confidence bands": "yes"})
        for field in ("Gray tests", "Graph", "Display"):
            self.assertField(field, **{field: None})

    def test_graph_cause_must_be_a_declared_code_only_when_it_is_used(self):
        self.assertField("Graph cause", **{"Graph cause": "missing"})
        analyse(METHOD, synthetic(2, 2), options(**{"Graph cause": "2"}))
        analyse(METHOD, synthetic(2, 2), options(Graph="All causes", **{"Graph cause": "stale"}))
        self.assertField("Graph cause", **{"Graph cause": 7})

    def test_roles_and_codes_route_to_their_own_fields(self):
        self.assertField("Time", Time="nope")
        self.assertField("Status", Status="")
        self.assertField("Group", Group="nope")
        self.assertField("Group", Group="t")
        self.assertField("Event codes", **{"Event codes": ["1", "1"]})
        self.assertField("Event codes", **{"Event codes": []})
        self.assertField("Event codes", **{"Event codes": [1, 2]})
        self.assertField("Censor code", **{"Censor code": ""})
        self.assertField("Censor code", **{"Censor code": "1"})
        self.assertField("Status", **{"Event codes": ["1"]})

    def test_a_missing_group_means_one_series(self):
        result = analyse(METHOD, synthetic(1, 2), options(Group=None))
        self.assertEqual(result.tables["Cumulative incidence"]["Group"].unique().tolist(), ["All"])
        result = analyse(METHOD, synthetic(1, 2), options(Group=""))
        self.assertEqual(result.tables["Cumulative incidence"]["Group"].unique().tolist(), ["All"])

    def test_check_options_does_not_calculate_but_applies_every_limit(self):
        frame = synthetic(2, 2)
        plan = cr.check_options(frame, options(**{"Gray tests": "Omnibus"}))
        self.assertEqual(len(plan.dataset.groups), 2)
        self.assertGreater(plan.gray_work, 0)
        rng = np.random.default_rng(4)
        n = 100_000
        large = pd.DataFrame({"t": rng.random(n), "s": rng.integers(0, 4, n), "g": rng.integers(0, 12, n)})
        with self.assertRaises(FieldError) as error:
            cr.check_options(large, options(**{"Event codes": ["1", "2", "3"], "Gray tests": "Omnibus"}))
        self.assertIn(error.exception.field, {"Group", "Event codes", "Time", "Gray tests"})


class CancelTests(unittest.TestCase):
    def test_a_set_event_stops_the_calculation_before_any_result(self):
        stop = threading.Event()
        stop.set()
        for gray in ("Off", "Omnibus", "Omnibus and pairwise"):
            with self.subTest(gray), self.assertRaises(engine.CompetingRisksCancelled):
                analyse(METHOD, fixture("cohorts"), {**EXPECTED["cohorts"]["options"], "Gray tests": gray}, cancel=stop)

    def test_cancellation_is_a_monte_carlo_cancellation_for_the_shared_handlers(self):
        from analisi.monte_carlo import MonteCarloCancelled
        self.assertTrue(issubclass(engine.CompetingRisksCancelled, MonteCarloCancelled))

    def test_an_unset_event_changes_nothing(self):
        plain = analyse(METHOD, fixture("cohorts"), EXPECTED["cohorts"]["options"])
        watched = analyse(METHOD, fixture("cohorts"), EXPECTED["cohorts"]["options"], cancel=threading.Event())
        pd.testing.assert_frame_equal(plain.tables["Cumulative incidence"], watched.tables["Cumulative incidence"])


class FigureTests(unittest.TestCase):
    def test_selected_cause_draws_one_step_line_per_group_from_the_origin_to_the_follow_up_end(self):
        result = run("cohorts")
        found = lines(result.figure)
        self.assertEqual(sorted(found), ["competing-risk-curve-g1-c1", "competing-risk-curve-g2-c1",
                                         "competing-risk-curve-g3-c1"])
        table = result.tables["Cumulative incidence"]
        for index, group in enumerate(EXPECTED["cohorts"]["groups"], 1):
            line = found[f"competing-risk-curve-g{index}-c1"]
            block = table[(table["Group"] == group) & (table["Cause"] == "1")]
            self.assertEqual(line.get_drawstyle(), "steps-post")
            self.assertEqual((line.get_xdata()[0], line.get_ydata()[0]), (0.0, 0.0))
            self.assertEqual(line.get_xdata()[-1], block["Time"].max())
            self.assertAlmostEqual(line.get_ydata()[-1], block["CIF"].iloc[-1])
            jumps = block[block["Cause events"] > 0]
            np.testing.assert_allclose(line.get_xdata()[1:1 + len(jumps)], jumps["Time"])

    def test_graph_cause_picks_another_cause_and_keeps_its_index_in_the_id(self):
        found = lines(run("cohorts", **{"Graph cause": "2"}).figure)
        self.assertEqual(sorted(found), ["competing-risk-curve-g1-c2", "competing-risk-curve-g2-c2",
                                         "competing-risk-curve-g3-c2"])

    def test_percent_multiplies_the_figure_but_not_the_tables(self):
        fraction, percent = run("cohorts"), run("cohorts", Display="Percent")
        pd.testing.assert_frame_equal(fraction.tables["Cumulative incidence"], percent.tables["Cumulative incidence"])
        first, second = lines(fraction.figure), lines(percent.figure)
        for gid in first:
            np.testing.assert_allclose(second[gid].get_ydata(), np.asarray(first[gid].get_ydata()) * 100)
            np.testing.assert_array_equal(second[gid].get_xdata(), first[gid].get_xdata())
        self.assertIn("(%)", percent.figure.axes[0].get_ylabel())
        self.assertNotIn("(%)", fraction.figure.axes[0].get_ylabel())

    def test_a_jump_at_time_zero_keeps_the_origin_point(self):
        frame = pd.DataFrame({"t": [0.0, 2.0, 3.0], "s": [1, 0, 2]})
        line = lines(analyse(METHOD, frame, options(Group=None)).figure)["competing-risk-curve-g1-c1"]
        self.assertEqual(list(line.get_xdata()[:2]), [0.0, 0.0])
        self.assertEqual(list(line.get_ydata()[:2]), [0.0, 1 / 3])

    def test_a_group_without_the_cause_is_a_flat_line_to_its_last_time(self):
        frame = pd.DataFrame({"t": [1.0, 2.0, 5.0, 6.0], "s": [1, 0, 0, 0], "g": ["A", "A", "B", "B"]})
        found = lines(analyse(METHOD, frame, options()).figure)
        self.assertEqual(list(found["competing-risk-curve-g2-c1"].get_xdata()), [0.0, 6.0])
        self.assertEqual(list(found["competing-risk-curve-g2-c1"].get_ydata()), [0.0, 0.0])

    def test_bands_follow_the_step_and_break_where_the_interval_is_missing(self):
        result = run("cohorts", **{"Show confidence bands": True})
        shaded = bands(result.figure)
        self.assertEqual(sorted(shaded), ["competing-risk-band-g1-c1", "competing-risk-band-g2-c1",
                                          "competing-risk-band-g3-c1"])
        self.assertEqual(bands(run("cohorts").figure), {})
        frame = pd.DataFrame({"t": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
                              "s": [1, 1, 1, 0, 1, 0, 0, 0]})
        figure = analyse(METHOD, frame, options(Group=None, **{"Show confidence bands": True})).figure
        band = bands(figure)["competing-risk-band-g1-c1"]
        for path in band.get_paths():
            self.assertTrue(np.isfinite(path.vertices).all())
        # The jump at 1 has an interval; the (0, 0) origin never does, so the band does not start at zero.
        left = min(path.vertices[:, 0].min() for path in band.get_paths())
        self.assertEqual(left, 1.0)

    def test_percent_scales_the_bands_too(self):
        fraction = bands(run("cohorts", **{"Show confidence bands": True}).figure)
        percent = bands(run("cohorts", Display="Percent", **{"Show confidence bands": True}).figure)
        for gid, item in fraction.items():
            first = np.vstack([path.vertices for path in item.get_paths()])
            second = np.vstack([path.vertices for path in percent[gid].get_paths()])
            np.testing.assert_allclose(second[:, 1], first[:, 1] * 100)

    def test_all_causes_view_uses_colour_for_groups_dashes_for_causes_and_unique_legend_entries(self):
        result = run("cohorts", Graph="All causes", **{"Show confidence bands": True})
        found = lines(result.figure)
        self.assertEqual(len(found), 6)
        self.assertEqual(len({line.get_color() for line in found.values()}), 3)
        for gid, line in found.items():
            cause = gid.rsplit("-c", 1)[1]
            self.assertEqual(line.get_linestyle(), "-" if cause == "1" else "--")
        labels = [text.get_text() for text in result.figure.axes[0].get_legend().get_texts()]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(labels, ["A", "B", "C", "Cause 1", "Cause 2", "95% pointwise confidence band"])

    def test_a_large_scope_is_split_into_one_panel_per_cause_with_a_shared_group_legend(self):
        frame = synthetic(12, 6, per_group=6)
        result = analyse(METHOD, frame, options(**{"Event codes": [str(i) for i in range(1, 7)]}, Graph="All causes",
                                                 Display="Percent"))
        figure = result.figure
        used = [axes for axes in figure.axes if axes.axison]
        self.assertEqual(len(used), 6)
        found = lines(figure)
        self.assertEqual(len(found), 72)
        self.assertEqual(len(set(found)), 72)
        self.assertEqual(len(figure.legends), 1)
        labels = [text.get_text() for text in figure.legends[0].get_texts()]
        self.assertEqual(labels, [f"G{i}" for i in range(12)])
        self.assertEqual(len({line.get_color() for line in found.values()}), 12)
        for fmt in ("png", "svg", "pdf"):
            buffer = io.BytesIO()
            figure.savefig(buffer, format=fmt)
            self.assertGreater(buffer.tell(), 1000, fmt)

    def test_the_axes_are_registered_as_numeric_for_the_graph_tools(self):
        for graph in ("Selected cause", "All causes"):
            figure = run("cohorts", Graph=graph).figure
            for axes in figure.axes:
                self.assertEqual(axes._tramastat_numeric_axes, ("x", "y"))

    def test_one_group_without_bands_has_no_legend_in_the_selected_view(self):
        self.assertIsNone(run("ties").figure.axes[0].get_legend())
        self.assertIsNotNone(run("ties", **{"Show confidence bands": True}).figure.axes[0].get_legend())

    def test_axis_labels_are_the_worksheet_time_column_and_the_incidence(self):
        axes = run("status-text").figure.axes[0]
        self.assertEqual(axes.get_xlabel(), "Day")
        self.assertEqual(axes.get_ylabel(), "Cumulative incidence")
        self.assertEqual(axes.get_ylim()[0], 0)


if __name__ == "__main__":
    unittest.main()
