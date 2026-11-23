"""Kaplan–Meier, conservative log-log Hall–Wellner simultaneous bands.

The reference is the package oracle (``tests/data/survival_bands/verify.py``): its own Kolmogorov quantile
(series, bisection) and a plain-Python risk-set loop, independent of SciPy and of the engine.
"""
import importlib.util
import io
from math import isfinite
from pathlib import Path
import unittest
import warnings

import matplotlib.colors
import numpy as np
import pandas as pd
from scipy import stats

from analisi import survival_bands as bands
from analisi.workbench import GRAPH_METHODS, METHODS, analyse
from analisi import stats as engine

DATA = Path(__file__).resolve().parent / "data" / "survival_bands"
_spec = importlib.util.spec_from_file_location("survival_bands_oracle", DATA / "verify.py")
oracle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oracle)

KM = "Kaplan–Meier survival"
KEYS = {"Time": "Time", "Event": "Event", "Group": "Group"}
CHOICE = "Hall–Wellner simultaneous band"
SHEET = "Simultaneous confidence bands"
COLUMNS = ["Group", "Time", "At risk", "Events", "Survival", "Greenwood factor",
           "Simultaneous CI lower", "Simultaneous CI upper", "Status", "Reason"]


def fixture():
    return pd.read_csv(DATA / "fixture.csv")


def fixture_rows():
    import csv
    with (DATA / "fixture.csv").open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


class CriticalValueTests(unittest.TestCase):
    def test_matches_scipy_and_the_independent_series(self):
        for level in (50, 80, 90, 95, 97.5, 99, 99.9):
            with self.subTest(level=level):
                self.assertAlmostEqual(bands.critical_value(level), stats.kstwobign.isf(1 - level / 100), places=13)
                self.assertAlmostEqual(bands.critical_value(level), oracle.kolmogorov_critical(level), places=11)
        self.assertAlmostEqual(bands.critical_value(95), 1.3580986393225505, places=12)

    def test_refuses_levels_outside_the_open_interval(self):
        for level in (0, 100, -5, 101, np.nan, np.inf):
            with self.subTest(level=level), self.assertRaisesRegex(ValueError, "confidence level"):
                bands.critical_value(level)


class BandFrameTests(unittest.TestCase):
    def curves(self, data=None, level=95):
        curves, _ = engine.survival(fixture() if data is None else data, "Time", "Event", "Group", level=level,
                                    strict=False)
        return curves

    def test_every_group_and_time_matches_the_oracle(self):
        rows = fixture_rows()
        for level in (90, 95, 99):
            expected = oracle.oracle(rows, level)
            frame = bands.band_sheet(self.curves(level=level), level)
            self.assertEqual(list(frame.columns), COLUMNS)
            self.assertIsInstance(frame.index, pd.RangeIndex)
            oracle.compare(frame, expected)

    def test_censored_only_time_inherits_the_current_step(self):
        frame = bands.band_sheet(self.curves(), 95)
        control = frame[frame["Group"] == "Control"].set_index("Time")
        self.assertEqual(control.loc[1.0, ["At risk", "Events"]].tolist(), [8, 2])
        self.assertEqual(control.loc[2.0, "Events"], 0)
        for column in ("Survival", "Greenwood factor", "Simultaneous CI lower", "Simultaneous CI upper", "Status"):
            self.assertEqual(control.loc[2.0, column], control.loc[1.0, column], column)

    def test_unavailable_rows_say_why_and_keep_survival(self):
        frame = bands.band_sheet(self.curves(), 95)
        control = frame[frame["Group"] == "Control"].set_index("Time")
        terminal = control.loc[8.0]
        self.assertEqual((terminal["Survival"], terminal["Status"]), (0., "Unavailable"))
        self.assertTrue(np.isnan(terminal["Simultaneous CI lower"]) and np.isnan(terminal["Simultaneous CI upper"]))
        self.assertIn("zero", terminal["Reason"])
        self.assertFalse(isfinite(terminal["Greenwood factor"]))
        self.assertEqual(control.loc[1.0, "Reason"], "")
        censored = frame[frame["Group"] == "Censored"]
        self.assertTrue((censored["Status"] == "Unavailable").all())
        self.assertTrue((censored["Survival"] == 1).all() and (censored["Greenwood factor"] == 0).all())
        self.assertTrue(censored["Reason"].str.contains("no event").all())
        treatment = frame[frame["Group"] == "Treatment"].set_index("Time")
        self.assertEqual(treatment.loc[0.0, "Status"], "Unavailable")  # a censor before any event
        self.assertEqual(treatment.loc[2.0, "Status"], "Available")
        tie = frame[frame["Group"] == "Terminal tie"]
        self.assertEqual((tie["At risk"].tolist(), tie["Events"].tolist()), ([2], [2]))

    def test_second_group_with_a_different_n_uses_its_own_n(self):
        data = pd.DataFrame({"Time": [1, 2, 3, 4, 5, 6, 7, 8, 1, 3, 5], "Event": [1, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1],
                             "Group": ["A"] * 8 + ["B"] * 3})
        frame = bands.band_sheet(self.curves(data), 95)
        for label, size in (("A", 8), ("B", 3)):
            part = frame[frame["Group"] == label]
            self.assertEqual(part["At risk"].iloc[0], size)
        rows = data.astype({"Time": float}).to_dict("records")
        oracle.compare(frame, oracle.oracle([{k: str(v) for k, v in row.items()} for row in rows], 95))

    def test_a_tie_between_event_and_censor_keeps_the_censored_subject_at_risk(self):
        data = pd.DataFrame({"Time": [2, 2, 3, 4], "Event": [1, 0, 1, 0], "Group": "A"})
        frame = bands.band_sheet(self.curves(data), 95)
        self.assertEqual(frame["At risk"].tolist(), [4, 2, 1])
        self.assertAlmostEqual(frame.at[0, "Survival"], .75)
        self.assertAlmostEqual(frame.at[0, "Greenwood factor"], 1 / 12)

    def test_limits_enclose_the_estimate_and_widen_with_the_level(self):
        low = bands.band_sheet(self.curves(level=90), 90)
        mid = bands.band_sheet(self.curves(level=95), 95)
        high = bands.band_sheet(self.curves(level=99), 99)
        usable = mid["Status"] == "Available"
        self.assertTrue(usable.any())
        for first, second in ((low, mid), (mid, high)):
            self.assertTrue((first.loc[usable, "Simultaneous CI lower"] >= second.loc[usable, "Simultaneous CI lower"]).all())
            self.assertTrue((first.loc[usable, "Simultaneous CI upper"] <= second.loc[usable, "Simultaneous CI upper"]).all())
        self.assertTrue((mid.loc[usable, "Simultaneous CI lower"] <= mid.loc[usable, "Survival"]).all())
        self.assertTrue((mid.loc[usable, "Survival"] <= mid.loc[usable, "Simultaneous CI upper"]).all())

    def test_extreme_survival_values_stay_finite_and_silent(self):
        curve = pd.DataFrame({"Time": [1., 2., 3.], "At risk": [3, 2, 1], "Events": [0, 0, 0],
                              "Censored": [1, 1, 1], "Survival": [1 - 1.1102230246251565e-16, 1e-300, 5e-324]})
        curve["Events"] = [1, 1, 0]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            frame = bands.band_frame(curve, 95)
        usable = frame[frame["Status"] == "Available"]
        self.assertFalse(usable.empty)
        self.assertTrue(np.isfinite(usable[["Simultaneous CI lower", "Simultaneous CI upper"]].to_numpy()).all())
        self.assertTrue(((usable["Simultaneous CI lower"] >= 0) & (usable["Simultaneous CI upper"] <= 1)).all())


class DispatcherTests(unittest.TestCase):
    def saved(self, **options):
        return {"Confidence level (%)": 95, "Display units": "Percent", **KEYS, **options}

    def test_the_choice_is_the_last_uncertainty_option_and_the_default_does_not_change(self):
        from analisi.survival_plot import GRAPH_OPTIONS, NO_UNCERTAINTY, UNCERTAINTY
        choices = GRAPH_OPTIONS[UNCERTAINTY]
        self.assertEqual(choices[0], NO_UNCERTAINTY)
        self.assertEqual(choices[:4], ("None", "Standard error bars", "Pointwise confidence band",
                                       "Pointwise confidence bars"))
        self.assertEqual(choices[-1], CHOICE)
        self.assertEqual(len(choices), 5)

    def test_without_the_choice_no_new_sheet_exists(self):
        plain = analyse(KM, fixture(), self.saved())
        self.assertNotIn(SHEET, plain.tables)
        for choice in ("None", "Standard error bars", "Pointwise confidence band", "Pointwise confidence bars"):
            self.assertNotIn(SHEET, analyse(KM, fixture(), self.saved(Uncertainty=choice)).tables)

    def test_the_new_sheet_is_added_and_every_other_sheet_is_untouched(self):
        for view in ("Survival", "Cumulative events"):
            for level in (90, 95, 99):
                with self.subTest(view=view, level=level):
                    options = self.saved(Curve=view, **{"Confidence level (%)": level})
                    plain = analyse(KM, fixture(), options)
                    result = analyse(KM, fixture(), {**options, "Uncertainty": CHOICE})
                    self.assertEqual(list(result.tables), [*plain.tables, SHEET])
                    for name, table in plain.tables.items():
                        pd.testing.assert_frame_equal(table, result.tables[name])
                    sheet = result.tables[SHEET]
                    self.assertEqual(list(sheet.columns), COLUMNS)
                    oracle.compare(sheet, oracle.oracle(fixture_rows(), level))

    def test_the_sheet_stays_in_fractions_with_percent_display(self):
        result = analyse(KM, fixture(), self.saved(Uncertainty=CHOICE))
        sheet = result.tables[SHEET]
        self.assertLessEqual(sheet["Survival"].max(), 1.)
        self.assertLessEqual(sheet["Simultaneous CI upper"].max(), 1.)
        self.assertEqual(result.tables["Curve: Control"]["Survival (%)"].iloc[0], 75.)

    def test_one_curve_without_a_group(self):
        data = pd.DataFrame({"Time": [1, 2, 3, 4, 5], "Event": [1, 0, 1, 1, 0]})
        result = analyse(KM, data, {"Time": "Time", "Event": "Event", "Uncertainty": CHOICE})
        sheet = result.tables[SHEET]
        self.assertEqual(set(sheet["Group"]), {"All"})
        self.assertEqual(len(sheet), 5)

    def test_an_invalid_level_is_refused_before_anything_is_drawn(self):
        for level in (0, 100, 120):
            with self.subTest(level=level), self.assertRaises(ValueError):
                analyse(KM, fixture(), self.saved(Uncertainty=CHOICE, **{"Confidence level (%)": level}))

    def test_two_responses_keep_a_response_column_and_no_stray_index(self):
        data = fixture().assign(Relapse=lambda frame: 1 - frame["Event"])
        options = {"Time": "Time", "Event columns": ["Event", "Relapse"], "Grouping variables": ["Group"],
                   "Uncertainty": CHOICE}
        result = analyse(KM, data, options)
        sheet = result.tables[SHEET]
        self.assertEqual(list(sheet.columns), ["Response variable", *COLUMNS])
        self.assertEqual(set(sheet["Response variable"]), {"Event", "Relapse"})
        self.assertIsInstance(sheet.index, pd.RangeIndex)
        single = analyse(KM, data, {**options, "Event columns": ["Event"]}).tables[SHEET]
        part = sheet[sheet["Response variable"] == "Event"].drop(columns="Response variable").reset_index(drop=True)
        # Several responses number the groups as every other sheet of that run does: "1 · Group='Control'".
        self.assertEqual(part["Group"].str.extract(r"'(.*)'")[0].tolist(), single["Group"].tolist())
        pd.testing.assert_frame_equal(part.drop(columns="Group"), single.drop(columns="Group"))

    def test_two_grouping_variables_keep_the_canonical_columns(self):
        data = fixture().assign(Site=lambda frame: np.where(frame["Time"] % 2 == 0, "North", "South"))
        options = {"Time": "Time", "Event columns": ["Event"], "Grouping variables": ["Group", "Site"],
                   "Uncertainty": CHOICE}
        sheet = analyse(KM, data, options).tables[SHEET]
        self.assertEqual(list(sheet.columns), COLUMNS)
        self.assertTrue(sheet["Group"].str.contains(" · ").any())

    def test_catalog_and_methods_are_unchanged(self):
        self.assertIn(KM, METHODS)
        self.assertIn(KM, GRAPH_METHODS)


class FigureTests(unittest.TestCase):
    def options(self, **options):
        return {"Confidence level (%)": 95, **KEYS, "Uncertainty": CHOICE, **options}

    @staticmethod
    def band_artists(axes):
        return [artist for artist in axes.collections
                if str(artist.get_gid()).startswith("kaplan-meier-simultaneous-band-") and not str(artist.get_gid()).endswith("key")]

    @staticmethod
    def levels(artist):
        vertices = artist.get_paths()[0].vertices
        return vertices[:, 0], vertices[:, 1]

    def test_each_available_curve_gets_one_step_band_in_its_color(self):
        result = analyse(KM, fixture(), self.options())
        axes, = result.figure.axes
        artists = self.band_artists(axes)
        self.assertEqual(len(artists), 2)  # Control and Treatment: the other two groups have no limits
        colors = {line.get_label(): line.get_color() for line in axes.lines if not line.get_label().startswith("_")}
        for artist, group in zip(artists, ("Control", "Treatment")):
            np.testing.assert_allclose(artist.get_facecolor()[0][:3], matplotlib.colors.to_rgb(colors[group]))
            self.assertGreater(artist.get_facecolor()[0][3], 0)
            self.assertLess(artist.get_facecolor()[0][3], .5)
            self.assertEqual(artist.get_label(), "_nolegend_")
        _, texts = axes.get_legend_handles_labels()
        self.assertEqual(texts, ["Control", "Treatment", "Censored", "Terminal tie",
                                 "95% simultaneous bands"])
        self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], texts)

    def test_the_band_follows_the_sheet_and_stops_where_the_limits_stop(self):
        result = analyse(KM, fixture(), self.options(**{"Display units": "Fraction"}))
        axes, = result.figure.axes
        sheet = result.tables[SHEET]
        control = sheet[(sheet["Group"] == "Control") & (sheet["Status"] == "Available")]
        artist = self.band_artists(axes)[0]
        x, y = self.levels(artist)
        self.assertEqual(x.min(), control["Time"].min())
        self.assertEqual(x.max(), 8.)  # the last step runs to the next time, where the limits end
        for column in ("Simultaneous CI lower", "Simultaneous CI upper"):
            for value in control[column]:
                self.assertTrue(np.isclose(y, value, rtol=0, atol=1e-12).any(), (column, value))
        self.assertGreater(x.min(), 0)  # nothing before the first event, where S = 1

    def test_cumulative_percent_shows_one_minus_the_limits_times_one_hundred(self):
        survival = analyse(KM, fixture(), self.options(**{"Display units": "Fraction"}))
        cumulative = analyse(KM, fixture(), self.options(Curve="Cumulative events", **{"Display units": "Percent"}))
        sheet = cumulative.tables[SHEET]
        control = sheet[(sheet["Group"] == "Control") & (sheet["Status"] == "Available")]
        axes, = cumulative.figure.axes
        _, y = self.levels(self.band_artists(axes)[0])
        for low, high in zip(control["Simultaneous CI lower"], control["Simultaneous CI upper"]):
            self.assertTrue(np.isclose(y, 100 * (1 - high), rtol=0, atol=1e-10).any())
            self.assertTrue(np.isclose(y, 100 * (1 - low), rtol=0, atol=1e-10).any())
        _, plain = self.levels(self.band_artists(survival.figure.axes[0])[0])
        self.assertLessEqual(plain.max(), 1.0)
        self.assertGreater(y.max(), 1.0)
        pd.testing.assert_frame_equal(sheet, survival.tables[SHEET])

    def test_a_single_curve_has_its_band_and_level_in_the_legend(self):
        data = pd.DataFrame({"Time": [1, 2, 3, 4, 5, 6], "Event": [1, 0, 1, 1, 0, 1]})
        result = analyse(KM, data, {"Time": "Time", "Event": "Event", "Uncertainty": CHOICE,
                                    "Confidence level (%)": 90})
        axes, = result.figure.axes
        self.assertEqual(axes.get_legend_handles_labels()[1], ["All", "90% simultaneous band"])
        self.assertEqual(len(self.band_artists(axes)), 1)
        key = [artist for artist in axes.collections if str(artist.get_gid()).endswith("-key")][0]
        np.testing.assert_allclose(key.get_facecolor()[0][:3], self.band_artists(axes)[0].get_facecolor()[0][:3])

    def test_it_replaces_the_pointwise_drawing_and_the_risk_table_and_censor_marks_stay(self):
        plain = analyse(KM, fixture(), self.options(Uncertainty="Pointwise confidence band",
                                                    **{"Show risk table below graph": True}))
        result = analyse(KM, fixture(), self.options(**{"Show risk table below graph": True}))
        self.assertEqual(len(result.figure.axes), len(plain.figure.axes))
        axes, risk = result.figure.axes
        old_axes, old_risk = plain.figure.axes
        self.assertEqual(len(old_axes.collections), 4)  # four pointwise bands...
        self.assertEqual(len(self.band_artists(axes)), 2)  # ...and two simultaneous ones, not both
        self.assertFalse(any("Pointwise" in str(a.get_label()) for a in axes.collections))
        self.assertEqual([line.get_xdata().tolist() for line in axes.lines],
                         [line.get_xdata().tolist() for line in old_axes.lines])
        self.assertEqual([text.get_text() for text in risk.texts], [text.get_text() for text in old_risk.texts])

    def test_the_legend_key_is_not_wider_than_the_curve_labels_and_panels_keep_their_width(self):
        # A long key made the compact two-panel figure squeeze both panels to a sliver (seen at 1024×768).
        data = fixture().assign(Relapse=lambda frame: 1 - frame["Event"])
        options = {"Time": "Time", "Event columns": ["Event", "Relapse"], "Grouping variables": ["Group"],
                   "Confidence level (%)": 95}
        widest = {}
        for name, choice in (("pointwise", "Pointwise confidence band"), ("simultaneous", CHOICE)):
            figure = analyse(KM, data, {**options, "Uncertainty": choice}).figure
            figure.set_size_inches(7.5, 4.2)
            figure.savefig(io.BytesIO(), format="png", dpi=100)  # the layout is solved on save
            widest[name] = [max(len(text.get_text()) for text in axes.get_legend().get_texts()) for axes in figure.axes]
            for axes in figure.axes:
                self.assertGreater(axes.get_position().width, .3, name)
        self.assertLessEqual(max(widest["simultaneous"]), max(widest["pointwise"]) + 2)

    def test_the_figure_is_fully_vector_in_svg(self):
        result = analyse(KM, fixture(), self.options())
        buffer = io.StringIO()
        result.figure.savefig(buffer, format="svg")
        svg = buffer.getvalue()
        self.assertNotIn("<image", svg)
        self.assertIn("95% simultaneous bands", svg)

    def test_a_group_without_limits_still_shows_its_curve(self):
        result = analyse(KM, fixture(), self.options())
        axes, = result.figure.axes
        drawn = [line.get_label() for line in axes.lines if not line.get_label().startswith("_")]
        self.assertEqual(drawn, ["Control", "Treatment", "Censored", "Terminal tie"])


if __name__ == "__main__":
    unittest.main()
