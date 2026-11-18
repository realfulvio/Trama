"""Cox regression: scaled Schoenfeld residuals, Cox–Snell residuals and the cumulative hazard of the residuals."""
import dataclasses
import json
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from statsmodels.duration.hazard_regression import PHReg

from analisi import cox_fit_diagnostics as diagnostics, cox_outputs as cox, i18n
from analisi.cox_dialog import cox_message
from analisi.processing import FieldError
from analisi.workbench import analyse

DATA = Path(__file__).parent / "data" / "cox-fit-diagnostics"
TERMS = ["Dose", "Arm [B]"]
BASE = {"Time": "Time", "Event": "Event", "Predictors": ["Dose", "Arm"], "Categorical predictors": ["Arm"]}
SCALED, SNELL = diagnostics.SCALED, diagnostics.COX_SNELL
SHEETS = ["Coefficients", "Model", "Reference levels"]


def followup():
    return pd.read_csv(DATA / "followup.csv")


def recipe(ties="Efron", **extra):
    return {**BASE, "Ties": ties, **extra}


def run(ties="Efron", frame=None, **extra):
    return analyse("Cox regression", followup() if frame is None else frame, recipe(ties, **extra))


def everything(ties="Efron", frame=None, **extra):
    return run(ties, frame, **{cox.PREDICT: True, cox.PROFILES: [{"Label": "Reference", "Values": {
        "Dose": 1, "Arm": "A"}}], cox.DIAGNOSTICS: True, cox.SCHOENFELD: True, SCALED: True, SNELL: True, **extra})


def reference(frame, ties):
    """Explicit risk sets with a mask per event time, PHReg only for the coefficients and their covariance."""
    data = frame.dropna()
    time, event = data.Time.to_numpy(), data.Event.to_numpy().astype(bool)
    x = np.column_stack([data.Dose, data.Arm.eq("B")]).astype(float)
    fit = PHReg(time, x, status=event, ties=ties.lower()).fit()
    risk = np.exp(x @ fit.params)
    raw, expected = np.zeros_like(x), np.zeros(len(time))
    for t in sorted(set(time[event])):
        active, deaths = time >= t, (time == t) & event
        d = int(deaths.sum())
        s0, e0 = risk[active].sum(), risk[deaths].sum()
        s1, e1 = (risk[active, None] * x[active]).sum(axis=0), (risk[deaths, None] * x[deaths]).sum(axis=0)
        fractions = np.arange(d) / d if ties == "Efron" else np.zeros(1)
        raw[deaths] = x[deaths] - np.mean([(s1 - f * e1) / (s0 - f * e0) for f in fractions], axis=0)
        expected[active] += d / s0 * risk[active]
    return data, time, event, x, fit, raw, expected


class OracleTests(unittest.TestCase):
    def test_frozen_oracle_matches_the_sheets_for_both_ties_methods(self):
        frozen = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
        for ties in ("Breslow", "Efron"):
            with self.subTest(ties=ties):
                result = run(ties, **{SCALED: True, SNELL: True})
                self.assertEqual(list(result.tables), [*SHEETS, diagnostics.SCALED_SHEET, diagnostics.SNELL_SHEET,
                                                       diagnostics.SNELL_HAZARD_SHEET])
                for sheet, key in ((diagnostics.SCALED_SHEET, "scaled"), (diagnostics.SNELL_SHEET, "snell"),
                                   (diagnostics.SNELL_HAZARD_SHEET, "hazard")):
                    table, wanted = result.tables[sheet], pd.DataFrame(frozen[ties][key])
                    self.assertEqual(list(table.columns), list(wanted.columns), sheet)
                    pd.testing.assert_frame_equal(table, wanted.astype(table.dtypes.to_dict()), rtol=2e-8, atol=5e-11)

    def test_explicit_risk_sets_agree_row_by_row(self):
        frame = followup()
        for ties in ("Breslow", "Efron"):
            with self.subTest(ties=ties):
                data, time, event, x, fit, raw, expected = reference(frame, ties)
                result = run(ties, **{SCALED: True, SNELL: True, cox.SCHOENFELD: True})
                np.testing.assert_allclose(result.tables["Schoenfeld residuals"][TERMS], raw[event], rtol=1e-9)
                scaled = result.tables[diagnostics.SCALED_SHEET]
                np.testing.assert_allclose(scaled[TERMS], event.sum() * raw[event] @ fit.cov_params(), rtol=1e-9)
                snell = result.tables[diagnostics.SNELL_SHEET]
                np.testing.assert_allclose(snell[diagnostics.SNELL_COLUMN], expected, rtol=1e-10, atol=1e-14)
                self.assertEqual(snell["Source row"].tolist(), (data.index.to_numpy() + 1).tolist())
                self.assertEqual(snell["Event"].tolist(), event.astype(int).tolist())

    def test_breslow_covariance_is_the_inverse_of_the_explicit_information(self):
        """V of the single fit, checked against the information summed by hand over the risk sets."""
        data, time, event, x, fit, *_ = reference(followup(), "Breslow")
        risk = np.exp(x @ fit.params)
        information = np.zeros((2, 2))
        for t in time[event]:
            active = time >= t
            s0, s1 = risk[active].sum(), (risk[active, None] * x[active]).sum(axis=0)
            s2 = (risk[active, None, None] * x[active, :, None] * x[active, None, :]).sum(axis=0)
            information += s2 / s0 - np.outer(s1, s1) / s0**2
        np.testing.assert_allclose(np.linalg.inv(information), fit.cov_params(), rtol=1e-6)
        fitted = cox.fit_cox(followup(), recipe("Breslow"))
        np.testing.assert_allclose(fitted.cov, np.linalg.inv(information), rtol=1e-6)

    def test_efron_and_breslow_differ_where_events_are_tied(self):
        breslow = run("Breslow", **{SCALED: True}).tables[diagnostics.SCALED_SHEET]
        efron = run("Efron", **{SCALED: True}).tables[diagnostics.SCALED_SHEET]
        self.assertEqual(breslow["Source row"].tolist(), efron["Source row"].tolist())
        self.assertFalse(np.allclose(breslow[TERMS], efron[TERMS], rtol=1e-4))


class SheetTests(unittest.TestCase):
    def test_scaled_rows_follow_the_raw_residuals_and_add_nothing(self):
        result = run(**{SCALED: True, cox.SCHOENFELD: True})
        raw, scaled = result.tables["Schoenfeld residuals"], result.tables[diagnostics.SCALED_SHEET]
        self.assertEqual(list(scaled.columns), ["Source row", "Time", *TERMS])
        # Events only, in the order of the raw sheet: censorings and the row with an empty cell (8) have no residual.
        self.assertEqual(scaled["Source row"].tolist(), [2, 3, 6, 7, 9, 11, 12, 15, 17])
        self.assertEqual(scaled["Source row"].tolist(), raw["Source row"].tolist())
        self.assertEqual(scaled["Time"].tolist(), raw["Time"].tolist())
        self.assertTrue({1, 4, 8, 19}.isdisjoint(scaled["Source row"]))
        # Centered on the score: the raw residuals sum to zero at the fit, hence so do the scaled ones.
        np.testing.assert_allclose(scaled[TERMS].sum(), 0, atol=1e-6)

    def test_scaled_without_the_raw_sheet_equals_scaled_with_it(self):
        alone = run(**{SCALED: True}).tables[diagnostics.SCALED_SHEET]
        both = run(**{SCALED: True, cox.SCHOENFELD: True}).tables[diagnostics.SCALED_SHEET]
        pd.testing.assert_frame_equal(alone, both)
        self.assertNotIn("Schoenfeld residuals", run(**{SCALED: True}).tables)

    def test_cox_snell_residuals_are_the_expected_events_of_the_residual_sheet(self):
        both = run(**{cox.DIAGNOSTICS: True, SNELL: True})
        alone = run(**{SNELL: True})
        expected = both.tables["Cox residuals"]["Expected events"]
        np.testing.assert_array_equal(both.tables[diagnostics.SNELL_SHEET][diagnostics.SNELL_COLUMN], expected)
        np.testing.assert_allclose(alone.tables[diagnostics.SNELL_SHEET][diagnostics.SNELL_COLUMN], expected,
                                   rtol=1e-13)
        self.assertEqual(list(alone.tables[diagnostics.SNELL_SHEET].columns),
                         ["Source row", "Time", "Event", diagnostics.SNELL_COLUMN])

    def test_a_censoring_before_the_first_jump_keeps_a_real_zero(self):
        snell = run(**{SNELL: True}).tables[diagnostics.SNELL_SHEET]
        row = snell.set_index("Source row").loc[1]
        self.assertEqual((row["Time"], row["Event"], row[diagnostics.SNELL_COLUMN]), (0.5, 0, 0.0))
        self.assertEqual(int((snell[diagnostics.SNELL_COLUMN] == 0).sum()), 1)
        table = run(**{SNELL: True}).tables[diagnostics.SNELL_HAZARD_SHEET]
        first = table.iloc[0]
        self.assertEqual((first["Residual"], first["Events"], first["Censored"], first["Cumulative hazard"]),
                         (0.0, 0, 1, 0.0))

    def test_equal_residuals_share_one_row_and_split_events_from_censorings(self):
        """Rows 2 and 19 have the same time and covariates: one residual, one event and one censoring."""
        snell = run(**{SNELL: True}).tables[diagnostics.SNELL_SHEET].set_index("Source row")
        shared = snell.loc[[2, 19], diagnostics.SNELL_COLUMN]
        self.assertEqual(shared.iat[0], shared.iat[1])
        table = run(**{SNELL: True}).tables[diagnostics.SNELL_HAZARD_SHEET]
        row = table[table["Residual"] == shared.iat[0]].iloc[0]
        self.assertEqual((row["Events"], row["Censored"], row["At risk"]), (1, 1, 17))
        self.assertAlmostEqual(row["Cumulative hazard"], 1 / 17)

    def test_hazard_table_matches_a_brute_force_scan_on_tied_data(self):
        rng = np.random.default_rng(21)
        n = 400
        frame = pd.DataFrame({"Time": rng.integers(1, 15, n).astype(float), "Event": rng.integers(0, 2, n),
                              "Dose": rng.integers(0, 3, n).astype(float), "Arm": rng.choice(list("AB"), n)})
        result = run(frame=frame, **{SNELL: True})
        snell = result.tables[diagnostics.SNELL_SHEET]
        residual, event = snell[diagnostics.SNELL_COLUMN].to_numpy(), snell["Event"].to_numpy().astype(bool)
        table, hazard = result.tables[diagnostics.SNELL_HAZARD_SHEET], 0.
        self.assertEqual(table["Residual"].tolist(), sorted(set(residual)))
        for _, row in table.iterrows():
            u = row["Residual"]
            self.assertEqual(row["At risk"], int((residual >= u).sum()))
            self.assertEqual(row["Events"], int(((residual == u) & event).sum()))
            self.assertEqual(row["Censored"], int(((residual == u) & ~event).sum()))
            hazard += row["Events"] / row["At risk"]
            self.assertEqual(row["Cumulative hazard"], hazard)
        self.assertEqual(table["Events"].sum(), event.sum())
        self.assertEqual(table["Events"].sum() + table["Censored"].sum(), n)

    def test_all_outputs_keep_the_earlier_sheets_and_their_order(self):
        result = everything()
        self.assertEqual(list(result.tables), [
            *SHEETS, "Baseline survival", "Predicted survival", "Cox residuals", "Schoenfeld residuals",
            diagnostics.SCALED_SHEET, diagnostics.SNELL_SHEET, diagnostics.SNELL_HAZARD_SHEET])
        earlier = run(**{cox.PREDICT: True, cox.PROFILES: [{"Label": "Reference", "Values": {"Dose": 1, "Arm": "A"}}],
                         cox.DIAGNOSTICS: True, cox.SCHOENFELD: True})
        self.assertEqual(list(earlier.tables), list(result.tables)[:7])
        for name in earlier.tables:
            pd.testing.assert_frame_equal(result.tables[name], earlier.tables[name], check_exact=True)

    def test_the_new_outputs_are_independent_of_the_earlier_checkboxes(self):
        for extra in ({SCALED: True}, {SNELL: True}, {SCALED: True, SNELL: True}):
            with self.subTest(extra=extra):
                result = run(**extra)
                self.assertEqual(list(result.tables)[3:], [name for name, on in (
                    (diagnostics.SCALED_SHEET, SCALED in extra), (diagnostics.SNELL_SHEET, SNELL in extra),
                    (diagnostics.SNELL_HAZARD_SHEET, SNELL in extra)) if on])


class CompatibilityTests(unittest.TestCase):
    def test_recipes_without_the_new_keys_or_with_them_off_return_the_original_output(self):
        frame = followup()
        for ties in ("Breslow", "Efron"):
            with self.subTest(ties=ties):
                original = {**recipe(ties), cox.PREDICT: True, cox.DIAGNOSTICS: True, cox.SCHOENFELD: True,
                            cox.PROFILES: [{"Label": "P", "Values": {"Dose": 2, "Arm": "B"}}]}
                before = analyse("Cox regression", frame, original)
                after = analyse("Cox regression", frame, {**original, SCALED: False, SNELL: False,
                                                          diagnostics.X_AXIS: diagnostics.EVENT_TIME})
                self.assertEqual(list(before.tables), list(after.tables))
                for name in before.tables:
                    pd.testing.assert_frame_equal(before.tables[name], after.tables[name], check_exact=True)
                self.assertEqual(before.figure.axes[0].get_title(), after.figure.axes[0].get_title())
                np.testing.assert_array_equal(before.figure.axes[0].lines[0].get_xydata(),
                                              after.figure.axes[0].lines[0].get_xydata())

    def test_the_fit_is_called_once_whatever_is_asked(self):
        calls = []
        original = PHReg.fit

        def counted(self, *args, **kwargs):
            calls.append(1)
            return original(self, *args, **kwargs)

        with patch.object(PHReg, "fit", counted):
            everything(**{cox.GRAPH: cox.SNELL_GRAPH})
            run(**{SCALED: True, SNELL: True})
            run(**{SCALED: True, cox.SCHOENFELD: True, cox.GRAPH: cox.SCALED_GRAPH})
        self.assertEqual(len(calls), 3)


class GraphTests(unittest.TestCase):
    def test_automatic_precedence_ends_with_the_scaled_view_then_cox_snell(self):
        titles = []
        for extra in ({cox.PREDICT: True, SCALED: True, SNELL: True}, {cox.DIAGNOSTICS: True, SCALED: True},
                      {cox.SCHOENFELD: True, SCALED: True, SNELL: True}, {SCALED: True, SNELL: True}, {SNELL: True}):
            if cox.PREDICT in extra:
                extra = {**extra, cox.PROFILES: [{"Label": "P", "Values": {"Dose": 1, "Arm": "A"}}]}
            titles.append(run(**extra).figure.axes[0].get_title())
        self.assertEqual(titles, ["Predicted survival (Cox)", "Cox deviance residuals", "Schoenfeld residuals: Dose",
                                  "Scaled Schoenfeld residuals: Dose", "Cox–Snell residuals"])
        self.assertIsNone(run().figure)

    def test_each_view_needs_its_output(self):
        for graph, output in ((cox.SCALED_GRAPH, SCALED), (cox.SNELL_GRAPH, SNELL)):
            with self.subTest(graph=graph), self.assertRaises(FieldError) as raised:
                run(**{cox.GRAPH: graph, **{name: True for name in (SCALED, SNELL) if name != output}})
            self.assertEqual(raised.exception.field, cox.GRAPH)
            self.assertEqual(str(raised.exception), f"Turn on {output} to display {graph.lower()}.")

    def test_scaled_graph_is_points_only_against_time_or_the_source_row(self):
        result = run(**{SCALED: True, cox.GRAPH: cox.SCALED_GRAPH, cox.GRAPH_TERM: "Arm [B]"})
        sheet = result.tables[diagnostics.SCALED_SHEET]
        axes = result.figure.axes[0]
        np.testing.assert_allclose(axes.collections[0].get_offsets(), sheet[["Time", "Arm [B]"]].to_numpy())
        self.assertEqual((axes.get_xlabel(), axes.get_ylabel()), ("Time", "Scaled Schoenfeld residual (Arm [B])"))
        # The only line is the y = 0 mark: nothing joins the observations.
        self.assertEqual(len(axes.lines), 1)
        np.testing.assert_array_equal(axes.lines[0].get_ydata(), [0, 0])
        by_row = run(**{SCALED: True, cox.GRAPH: cox.SCALED_GRAPH, diagnostics.X_AXIS: diagnostics.SOURCE_ROW})
        offsets = by_row.figure.axes[0].collections[0].get_offsets()
        np.testing.assert_allclose(offsets, sheet[["Source row", "Dose"]].to_numpy())
        self.assertEqual(by_row.figure.axes[0].get_xlabel(), "Source row")

    def test_the_default_term_is_the_first_and_a_dummy_term_can_be_chosen(self):
        first = run(**{SCALED: True, cox.GRAPH: cox.SCALED_GRAPH}).figure.axes[0]
        self.assertTrue(first.get_title().endswith(": Dose"))
        dummy = run(**{SCALED: True, cox.GRAPH: cox.SCALED_GRAPH, cox.GRAPH_TERM: "Arm [B]"}).figure.axes[0]
        self.assertTrue(dummy.get_title().endswith(": Arm [B]"))

    def test_invalid_term_and_axis_name_their_control(self):
        for extra, field in (({cox.GRAPH_TERM: "Arm"}, cox.GRAPH_TERM), ({diagnostics.X_AXIS: "Time"}, diagnostics.X_AXIS)):
            with self.subTest(field=field), self.assertRaises(FieldError) as raised:
                run(**{SCALED: True, cox.GRAPH: cox.SCALED_GRAPH, **extra})
            self.assertEqual(raised.exception.field, field)
        # The axis only matters for the scaled view: another view ignores a stale value.
        run(**{SCALED: True, SNELL: True, cox.GRAPH: cox.SNELL_GRAPH, diagnostics.X_AXIS: "Time"})

    def test_time_zero_is_a_valid_event_time(self):
        frame = followup().copy()
        frame.loc[1, "Time"] = 0.0  # row 2: an event at time zero
        result = run(frame=frame, **{SCALED: True, cox.GRAPH: cox.SCALED_GRAPH})
        offsets = result.figure.axes[0].collections[0].get_offsets()
        self.assertEqual(float(offsets[:, 0].min()), 0.0)
        self.assertLessEqual(result.figure.axes[0].get_xlim()[0], 0.0)

    def test_cox_snell_plot_is_a_post_step_from_the_origin_with_its_diagonal(self):
        result = run(**{SNELL: True, cox.GRAPH: cox.SNELL_GRAPH})
        table = result.tables[diagnostics.SNELL_HAZARD_SHEET]
        axes = result.figure.axes[0]
        step, diagonal = axes.lines
        self.assertEqual(step.get_drawstyle(), "steps-post")
        points = step.get_xydata()
        # The first residual is a real zero: the origin is the first row, not an extra point.
        np.testing.assert_allclose(points, table[["Residual", "Cumulative hazard"]].to_numpy())
        np.testing.assert_allclose(points[0], [0, 0])
        last = table["Residual"].iat[-1]
        np.testing.assert_allclose(diagonal.get_xydata(), [[0, 0], [last, last]])
        self.assertEqual([line.get_label() for line in axes.lines], ["Cumulative hazard of the residuals", "y = x"])
        self.assertIsNotNone(axes.get_legend())
        self.assertEqual(axes.get_xscale(), "linear")
        self.assertEqual(axes.get_yscale(), "linear")
        # A censoring-only residual adds a flat point, not a jump.
        flat = table[table["Events"] == 0]
        self.assertGreater(len(flat), 1)
        steps = np.diff(points[:, 1])
        self.assertTrue((steps[(table["Events"] == 0).to_numpy()[1:]] == 0).all())

    def test_the_curve_starts_at_the_origin_when_every_residual_is_positive(self):
        frame = followup().iloc[1:].copy()  # without the early censoring: no true zero residual
        result = run(frame=frame, **{SNELL: True, cox.GRAPH: cox.SNELL_GRAPH})
        table = result.tables[diagnostics.SNELL_HAZARD_SHEET]
        self.assertGreater(table["Residual"].iat[0], 0)
        points = result.figure.axes[0].lines[0].get_xydata()
        np.testing.assert_allclose(points[0], [0, 0])
        self.assertEqual(len(points), len(table) + 1)

    def test_visibility_follows_the_view_that_is_really_drawn(self):
        visible = cox.cox_visibility
        self.assertEqual(visible(False, cox.AUTOMATIC), {cox.PROFILES: False, cox.GRAPH_TERM: False, cox.X_AXIS: False})
        self.assertEqual(visible(False, cox.SCALED_GRAPH, scaled=True),
                         {cox.PROFILES: False, cox.GRAPH_TERM: True, cox.X_AXIS: True})
        self.assertEqual(visible(False, cox.AUTOMATIC, scaled=True),
                         {cox.PROFILES: False, cox.GRAPH_TERM: True, cox.X_AXIS: True})
        # Raw Schoenfeld shows the term but never the axis; Cox–Snell shows neither.
        self.assertEqual(visible(False, cox.AUTOMATIC, schoenfeld=True, scaled=True),
                         {cox.PROFILES: False, cox.GRAPH_TERM: True, cox.X_AXIS: False})
        self.assertEqual(visible(False, cox.SNELL_GRAPH, snell=True),
                         {cox.PROFILES: False, cox.GRAPH_TERM: False, cox.X_AXIS: False})
        self.assertEqual(visible(True, cox.AUTOMATIC, scaled=True)[cox.X_AXIS], False)


class DataTests(unittest.TestCase):
    def test_an_excluded_predictor_cell_of_an_event_removes_the_row_and_changes_m(self):
        frame = followup()
        base = run(frame=frame, **{SCALED: True, SNELL: True})
        masked = frame.copy()
        masked.loc[1, "Dose"] = np.nan  # row 2, an event
        result = run(frame=masked, **{SCALED: True, SNELL: True})
        self.assertNotIn(2, result.tables[diagnostics.SCALED_SHEET]["Source row"].tolist())
        self.assertNotIn(2, result.tables[diagnostics.SNELL_SHEET]["Source row"].tolist())
        self.assertEqual(len(result.tables[diagnostics.SCALED_SHEET]), len(base.tables[diagnostics.SCALED_SHEET]) - 1)
        data, time, event, x, fit, raw, expected = reference(masked, "Efron")
        np.testing.assert_allclose(result.tables[diagnostics.SCALED_SHEET][TERMS],
                                   event.sum() * raw[event] @ fit.cov_params(), rtol=1e-9)
        np.testing.assert_allclose(result.tables[diagnostics.SNELL_SHEET][diagnostics.SNELL_COLUMN], expected,
                                   rtol=1e-10, atol=1e-14)

    def test_a_changed_time_changes_the_tables_consistently(self):
        frame = followup()
        frame.loc[4, "Time"] = 11.5  # row 5, a censoring at 3 moves to 11.5
        result = run(frame=frame, **{SCALED: True, SNELL: True})
        data, time, event, x, fit, raw, expected = reference(frame, "Efron")
        np.testing.assert_allclose(result.tables[diagnostics.SCALED_SHEET][TERMS],
                                   event.sum() * raw[event] @ fit.cov_params(), rtol=1e-9)
        np.testing.assert_allclose(result.tables[diagnostics.SNELL_SHEET][diagnostics.SNELL_COLUMN], expected,
                                   rtol=1e-10, atol=1e-14)

    def test_text_levels_for_event_and_censoring(self):
        frame = followup().astype({"Event": object})
        frame["Event"] = np.where(frame["Event"] == 1, "Died", "Alive")
        text = run(frame=frame, **{cox.EVENT_VALUE: "Died", cox.CENSOR_VALUE: "Alive", SCALED: True, SNELL: True})
        numeric = run(**{SCALED: True, SNELL: True})
        for name in (diagnostics.SCALED_SHEET, diagnostics.SNELL_SHEET, diagnostics.SNELL_HAZARD_SHEET):
            pd.testing.assert_frame_equal(text.tables[name], numeric.tables[name], check_exact=True)

    def test_many_events_and_censorings_at_one_instant(self):
        frame = pd.DataFrame({"Time": [1, 2, 2, 2, 2, 3, 3, 4, 5, 5, 6, 6, 7, 8, 9],
                              "Event": [1, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 1],
                              "Dose": [1, 2, 0, 1, 2, 3, 0, 2, 1, 3, 1, 0, 2, 3, 1],
                              "Arm": list("ABABABABABABABA")})
        for ties in ("Breslow", "Efron"):
            with self.subTest(ties=ties):
                result = run(ties, frame=frame, **{SCALED: True, SNELL: True})
                data, time, event, x, fit, raw, expected = reference(frame, ties)
                np.testing.assert_allclose(result.tables[diagnostics.SCALED_SHEET][TERMS],
                                           event.sum() * raw[event] @ fit.cov_params(), rtol=1e-8)
                np.testing.assert_allclose(result.tables[diagnostics.SNELL_SHEET][diagnostics.SNELL_COLUMN],
                                           expected, rtol=1e-9)
                table = result.tables[diagnostics.SNELL_HAZARD_SHEET]
                self.assertEqual(int(table["Events"].sum()), int(event.sum()))
                self.assertEqual(int(table["At risk"].iat[0]), len(frame))

    def test_a_category_other_than_the_alphabetical_first_keeps_the_model_reference(self):
        frame = followup().assign(Arm=lambda f: f.Arm.map({"A": "Zeta", "B": "Alpha"}))
        result = run(frame=frame, **{SCALED: True, cox.GRAPH: cox.SCALED_GRAPH, cox.GRAPH_TERM: "Arm [Zeta]"})
        self.assertEqual(list(result.tables[diagnostics.SCALED_SHEET].columns), ["Source row", "Time", "Dose", "Arm [Zeta]"])
        self.assertTrue(result.figure.axes[0].get_title().endswith(": Arm [Zeta]"))


class NumericLimitTests(unittest.TestCase):
    @staticmethod
    def synthetic(shift=0., n=80, seed=8):
        rng = np.random.default_rng(seed)
        return pd.DataFrame({"Time": rng.exponential(5, n).round(3) + .01, "Event": (rng.random(n) < .7).astype(int),
                             "X": rng.normal(size=n) + shift, "Z": rng.normal(size=n)})

    options = {"Time": "Time", "Event": "Event", "Predictors": ["X", "Z"], "Categorical predictors": [], "Ties": "Efron"}

    def test_the_stable_product_equals_the_baseline_route(self):
        fit = cox.fit_cox(self.synthetic(), self.options)
        direct = cox.expected_events(fit, cox.baseline(fit))
        np.testing.assert_allclose(diagnostics.stable_expected_events(fit), direct, rtol=1e-11, atol=0)
        np.testing.assert_array_equal(direct == 0, diagnostics.stable_expected_events(fit) == 0)

    def test_baseline_and_hazard_ratio_far_from_one_still_meet_in_a_finite_product(self):
        """A shift of the design by s changes eta by s·beta and the baseline inversely: the product is invariant."""
        fit = cox.fit_cox(self.synthetic(), self.options)
        wanted = cox.expected_events(fit, cox.baseline(fit))
        shift = 2000. / float(fit.beta[0])
        moved = dataclasses.replace(fit, design=fit.design.assign(X=fit.design["X"] + shift))
        with self.assertRaises(ValueError):
            cox.baseline(moved)  # H0 itself is not representable ...
        stable = diagnostics.stable_expected_events(moved)
        np.testing.assert_allclose(stable, wanted, rtol=1e-8)  # ... but H0 · exp(eta) is.

    def test_far_from_zero_predictors_give_cox_snell_through_the_stable_route(self):
        frame = self.synthetic(shift=1e6)
        o = {**self.options, "Predictors": ["X"], SNELL: True, SCALED: True}
        result = analyse("Cox regression", frame, o)
        snell = result.tables[diagnostics.SNELL_SHEET]
        residual = snell[diagnostics.SNELL_COLUMN]
        first = snell.loc[snell["Event"] == 1, "Time"].min()
        self.assertTrue(np.isfinite(residual).all())
        self.assertTrue((residual[snell["Time"] >= first] > 0).all() and (residual[snell["Time"] < first] == 0).all())
        # With the Breslow baseline the residuals add up to the number of events for any beta.
        np.testing.assert_allclose(residual.sum(), snell["Event"].sum(), rtol=1e-9)
        self.assertTrue(np.isfinite(result.tables[diagnostics.SCALED_SHEET].to_numpy()).all())
        # The earlier output that needs H0 itself keeps its original error.
        with self.assertRaises(ValueError) as raised:
            analyse("Cox regression", frame, {**o, cox.DIAGNOSTICS: True})
        self.assertIn("not representable", str(raised.exception))

    def test_a_covariance_that_is_not_finite_names_the_scaled_control(self):
        fit = cox.fit_cox(followup().dropna(), recipe())
        raw = cox.schoenfeld(fit)
        for bad in (np.full((2, 2), np.nan), np.full((2, 2), np.inf), np.eye(3), None, np.diag([1., -1e-3]),
                    np.zeros((2, 2))):
            with self.subTest(cov=bad), self.assertRaises(FieldError) as raised:
                diagnostics.scaled_schoenfeld(dataclasses.replace(fit, cov=bad), raw)
            self.assertEqual(raised.exception.field, SCALED)
        overflow = dataclasses.replace(fit, cov=np.full((2, 2), 1e308))
        with self.assertRaises(FieldError) as raised:
            diagnostics.scaled_schoenfeld(overflow, raw)
        self.assertEqual(raised.exception.field, SCALED)
        with self.assertRaises(FieldError) as raised:
            diagnostics.scaled_schoenfeld(fit, raw.iloc[:-1])
        self.assertEqual(raised.exception.field, SCALED)

    def test_cox_snell_refuses_values_it_cannot_represent_instead_of_writing_zero(self):
        fit = cox.fit_cox(followup().dropna(), recipe())
        good = cox.expected_events(fit, cox.baseline(fit))
        for name, bad in (("nan", np.where(np.arange(len(good)) == 4, np.nan, good)),
                          ("inf", np.where(np.arange(len(good)) == 4, np.inf, good)),
                          ("negative", np.where(np.arange(len(good)) == 4, -1., good)),
                          ("underflow", np.where(fit.time == fit.time.max(), 0., good)),
                          ("shape", good[:-1])):
            with self.subTest(case=name), self.assertRaises(FieldError) as raised:
                diagnostics.cox_snell_residuals(fit, bad)
            self.assertEqual(raised.exception.field, SNELL)
        diagnostics.cox_snell_residuals(fit, good)

    def test_an_ill_conditioned_fit_returns_no_partial_result(self):
        frame = self.synthetic()
        separated = frame.assign(S=np.where(frame.Event == 1, 5., 0.) + np.arange(len(frame)) * 1e-9)
        cases = (("collinear", frame.assign(X2=frame.X * 2), ["X", "X2"]), ("constant", frame.assign(X2=1.), ["X", "X2"]),
                 ("separation", separated, ["S"]))
        for name, odd, predictors in cases:
            with self.subTest(case=name), warnings.catch_warnings(), self.assertRaises(ValueError) as raised:
                # statsmodels warns about a negative variance before the fit is refused.
                warnings.simplefilter("ignore", RuntimeWarning)
                analyse("Cox regression", odd, {**self.options, "Predictors": predictors, SCALED: True, SNELL: True})
            self.assertNotIsInstance(raised.exception, KeyError)
            self.assertIsNone(getattr(raised.exception, "field", None))

    def test_a_graph_requested_without_a_baseline_event_fails_before_any_table(self):
        frame = followup().assign(Event=0)
        with self.assertRaises(ValueError):
            run(frame=frame, **{SCALED: True, SNELL: True})


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.active_language())

    def test_every_engine_message_has_an_italian_text_with_the_same_english_source(self):
        for key, text in diagnostics.MESSAGES.items():
            with self.subTest(key=key):
                self.assertEqual(i18n.translate("en", f"cox.error.{key}"), text)
                self.assertNotEqual(i18n.translate("it", f"cox.error.{key}"), text)

    def test_messages_translate_and_keep_worksheet_text_literal(self):
        i18n.set_language("it")
        with self.assertRaises(FieldError) as raised:
            run(**{cox.GRAPH: cox.SCALED_GRAPH})
        self.assertEqual(cox_message(raised.exception),
                         "Attiva Residui di Schoenfeld scalati per mostrare schoenfeld scalati.")
        with self.assertRaises(FieldError) as raised:
            run(**{SCALED: True, cox.GRAPH: cox.SCALED_GRAPH, cox.GRAPH_TERM: "Dose x"})
        self.assertEqual(cox_message(raised.exception), "Scegli uno dei termini del modello: Dose, Arm [B].")
        with self.assertRaises(FieldError) as raised:
            run(**{SCALED: True, cox.GRAPH: cox.SCALED_GRAPH, diagnostics.X_AXIS: "Tempo"})
        self.assertIn("Tempo dell’evento", cox_message(raised.exception))
        i18n.set_language("en")
        self.assertEqual(cox_message(FieldError("x", "Anything else stays as written.")), "Anything else stays as written.")

    def test_labels_and_choices_have_italian_captions(self):
        i18n.set_language("it")
        self.assertEqual([i18n.ui(name) for name in (SCALED, SNELL, diagnostics.X_AXIS)],
                         ["Residui di Schoenfeld scalati", "Diagnostica Cox–Snell", "Asse X di Schoenfeld"])
        self.assertEqual([i18n.ui(value) for value in (cox.SCALED_GRAPH, cox.SNELL_GRAPH, *diagnostics.X_AXES)],
                         ["Schoenfeld scalati", "Grafico Cox–Snell", "Tempo dell’evento", "Riga di origine"])


if __name__ == "__main__":
    unittest.main()
