"""Cox regression: status codes, Breslow baseline, predicted survival and residual sheets."""
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize
from statsmodels.duration.hazard_regression import PHReg

from analisi import cox_outputs as cox, models
from analisi.processing import FieldError
from analisi.workbench import analyse

FIXTURE = Path(__file__).parent / "data" / "cox-profiles.csv"
SHEETS = ["Coefficients", "Model", "Reference levels"]
# Independent values for the fixture: Arm [B] solves the score equation of each ties method.
BETA = {"Breslow": -0.5488459915769891, "Efron": -0.580338684863295}
HAZARD = {"Breslow": [0.10113186788348506, 0.21364210633787933, 0.5106932205646628, 0.7513536698903811,
                      1.068287575298068, 1.456242957379465],
          "Efron": [0.10205598051370167, 0.21571115087954087, 0.5151515129205786, 0.757904278450546,
                    1.0784769454472904, 1.4691463887398932]}


def fixture():
    return pd.read_csv(FIXTURE)


def options(ties="Efron", **extra):
    base = {"Time": "Time", "Event": "Event", "Predictors": ["Arm"], "Categorical predictors": ["Arm"], "Ties": ties,
            cox.EVENT_VALUE: "Death", cox.CENSOR_VALUE: "Censored"}
    return {**base, **extra}


def profiles(*groups):
    return [{"Label": group, "Values": {"Arm": group}} for group in groups]


def full(ties="Efron", frame=None, **extra):
    o = options(ties, **{cox.PREDICT: True, cox.PROFILES: profiles("A", "B"), cox.DIAGNOSTICS: True,
                         cox.SCHOENFELD: True, **extra})
    return analyse("Cox regression", fixture() if frame is None else frame, o)


def oracle(frame, x, ties):
    """Direct score root, Breslow increments and residuals for one covariate."""
    time = frame.Time.to_numpy(dtype=float)
    status = (frame.Event == "Death").to_numpy()
    times = np.unique(time[status])

    def means(beta, t):
        w = np.exp(beta * x)
        death, risk = (time == t) & status, time >= t
        d = death.sum()
        fractions = np.arange(d) / d if ties == "Efron" else np.zeros(d)
        return death, ((w * x)[risk].sum() - fractions * (w * x)[death].sum()) / (
            w[risk].sum() - fractions * w[death].sum())

    beta = optimize.brentq(lambda b: sum(x[d].sum() - m.sum() for d, m in (means(b, t) for t in times)),
                           -10, 10, xtol=1e-13)
    hr = np.exp(beta * x)
    hazard = np.cumsum([((time == t) & status).sum() / hr[time >= t].sum() for t in times])
    mu = np.r_[0., hazard][np.searchsorted(times, time, side="right")] * hr
    schoenfeld = np.full(len(x), np.nan)
    for t in times:
        death, m = means(beta, t)
        schoenfeld[death] = x[death] - m.mean()
    return beta, times, hazard, status - mu, schoenfeld


class FixtureTests(unittest.TestCase):
    def test_both_ties_methods_match_the_independent_score_and_baseline(self):
        frame = fixture()
        x = (frame.Arm == "B").to_numpy(dtype=float)
        for ties in ("Breslow", "Efron"):
            with self.subTest(ties=ties):
                result = full(ties)
                beta, times, hazard, martingale, schoenfeld = oracle(frame, x, ties)
                self.assertAlmostEqual(result.tables["Coefficients"].loc["Arm [B]", "Estimate"], BETA[ties], 7)
                self.assertAlmostEqual(beta, BETA[ties], 10)
                sheet = result.tables["Baseline survival"]
                self.assertEqual(list(sheet.columns), ["Time", "Events", "Baseline hazard increment",
                                                       "Baseline cumulative hazard", "Baseline survival"])
                np.testing.assert_allclose(sheet["Time"], times)
                np.testing.assert_allclose(sheet["Baseline cumulative hazard"], HAZARD[ties], rtol=1e-8)
                np.testing.assert_allclose(sheet["Baseline cumulative hazard"], hazard, rtol=1e-8)
                np.testing.assert_allclose(sheet["Baseline hazard increment"].cumsum(),
                                           sheet["Baseline cumulative hazard"], rtol=1e-12)
                self.assertEqual(sheet["Events"].tolist(), [1, 1, 2, 1, 1, 1])
                rows = result.tables["Cox residuals"]
                np.testing.assert_allclose(rows["Martingale residual"], martingale, rtol=1e-8, atol=1e-10)
                scaled = result.tables["Schoenfeld residuals"]
                np.testing.assert_allclose(scaled["Arm [B]"], schoenfeld[~np.isnan(schoenfeld)], rtol=1e-8)
                self.assertEqual(scaled["Source row"].tolist(), [1, 2, 5, 6, 8, 9, 11])
                self.assertAlmostEqual(scaled["Arm [B]"].sum(), 0, 10)
                self.assertAlmostEqual(rows["Martingale residual"].sum(), 0, 10)

    def test_tied_events_at_time_four_separate_breslow_and_efron(self):
        """Two deaths at time 4: Efron removes half of their weight in the second risk-set mean."""
        breslow, efron = full("Breslow"), full("Efron")
        tied = {name: result.tables["Schoenfeld residuals"].set_index("Source row").loc[[5, 6], "Arm [B]"]
                for name, result in (("Breslow", breslow), ("Efron", efron))}
        self.assertAlmostEqual(tied["Breslow"].iat[0], -0.25737221443304154, 10)
        self.assertAlmostEqual(tied["Efron"].iat[0], -0.2735327014797717, 10)
        increments = {name: result.tables["Baseline survival"].set_index("Time").loc[4, "Baseline hazard increment"]
                      for name, result in (("Breslow", breslow), ("Efron", efron))}
        self.assertAlmostEqual(increments["Breslow"], 0.29705111422678343, 10)
        self.assertAlmostEqual(increments["Efron"], 0.2994403620410377, 10)

    def test_censoring_tied_with_an_event_stays_in_the_risk_set(self):
        result = full("Breslow")
        rows = result.tables["Cox residuals"].set_index("Source row")
        # Row 3 is censored at 2 like the death in row 2: its expected events include the jump at 2.
        hazard_at_two = HAZARD["Breslow"][1]
        self.assertAlmostEqual(rows.loc[3, "Expected events"], hazard_at_two, 10)
        self.assertAlmostEqual(rows.loc[2, "Expected events"], hazard_at_two * np.exp(BETA["Breslow"]), 8)

    def test_predicted_curves_use_the_same_jumps_for_every_profile(self):
        result = full("Efron")
        predicted = result.tables["Predicted survival"]
        self.assertEqual(list(predicted.columns), ["Profile", "Time", "Survival"])
        self.assertEqual(predicted["Profile"].tolist(), ["A"] * 6 + ["B"] * 6)
        hazard = np.array(HAZARD["Efron"])
        np.testing.assert_allclose(predicted["Survival"][:6], np.exp(-hazard), rtol=1e-8)
        np.testing.assert_allclose(predicted["Survival"][6:], np.exp(-hazard * np.exp(BETA["Efron"])), rtol=1e-8)
        np.testing.assert_allclose(result.tables["Baseline survival"]["Baseline survival"], predicted["Survival"][:6])
        axes = result.figure.axes[0]
        self.assertEqual(len(axes.lines), 2)
        x, y = axes.lines[0].get_data()
        # Drawing points: the start at (0, 1) and the extension to the last observed time 9.
        self.assertEqual((x[0], y[0], x[-1]), (0, 1, 9))
        np.testing.assert_allclose(y[1:-1], predicted["Survival"][:6])

    def test_deviance_residuals(self):
        result = full("Breslow")
        rows = result.tables["Cox residuals"]
        self.assertEqual(list(rows.columns), ["Source row", "Time", "Event", "Linear predictor", "Hazard ratio",
                                              "Expected events", "Martingale residual", "Deviance residual"])
        self.assertEqual(rows["Event"].tolist(), [1, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1, 0])
        m, d = rows["Martingale residual"], rows["Event"]
        expected = np.sign(m) * np.sqrt(-2 * (m + d * np.log(rows["Expected events"])))
        np.testing.assert_allclose(rows["Deviance residual"], expected)
        self.assertAlmostEqual(rows["Deviance residual"].iat[0], 1.6688090717632422, 10)


class StatusCodeTests(unittest.TestCase):
    def test_numeric_codes_default_to_one_and_zero(self):
        frame = fixture().assign(Event=lambda f: (f.Event == "Death").astype(int))
        o = {**options(), cox.EVENT_VALUE: "1", cox.CENSOR_VALUE: "0"}
        new = analyse("Cox regression", frame, o).tables["Coefficients"]
        old = models.cox_regression(frame, "Time", "Event", ["Arm"], ["Arm"], "efron")["Coefficients"]
        pd.testing.assert_frame_equal(new, old)
        without_codes = {key: value for key, value in o.items() if key not in cox.STATUS_DEFAULTS}
        pd.testing.assert_frame_equal(analyse("Cox regression", frame, {**without_codes, cox.DIAGNOSTICS: False})
                                      .tables["Coefficients"], old)

    def test_other_numeric_codes(self):
        frame = fixture().assign(Event=lambda f: np.where(f.Event == "Death", 2, 7))
        result = analyse("Cox regression", frame, {**options(), cox.EVENT_VALUE: "2", cox.CENSOR_VALUE: "7"})
        self.assertAlmostEqual(result.tables["Coefficients"].loc["Arm [B]", "Estimate"], BETA["Efron"], 7)
        with self.assertRaises(FieldError) as raised:
            analyse("Cox regression", frame, {**options(), cox.EVENT_VALUE: "Death", cox.CENSOR_VALUE: "7"})
        self.assertEqual(raised.exception.field, cox.EVENT_VALUE)

    def test_empty_cells_are_missing_not_censored(self):
        frame = fixture().astype({"Event": object})
        frame.loc[0, "Event"] = ""
        frame.loc[2, "Event"] = None
        rows = analyse("Cox regression", frame, options(**{cox.DIAGNOSTICS: True})).tables["Cox residuals"]
        self.assertEqual(rows["Source row"].tolist(), [2, 4, 5, 6, 7, 8, 9, 10, 11, 12])
        numeric = fixture().assign(Event=lambda f: (f.Event == "Death").astype(float))
        numeric.loc[3, "Event"] = np.nan
        o = options(**{cox.EVENT_VALUE: "1", cox.CENSOR_VALUE: "0", cox.DIAGNOSTICS: True})
        self.assertNotIn(4, analyse("Cox regression", numeric, o).tables["Cox residuals"]["Source row"].tolist())

    def test_unknown_and_invalid_codes_name_their_field(self):
        frame = fixture()
        frame.loc[4, "Event"] = "Dead"
        with self.assertRaises(FieldError) as raised:
            analyse("Cox regression", frame, options())
        self.assertEqual(raised.exception.field, "Event")
        self.assertIn("'Dead' at row 5", str(raised.exception))
        self.assertIn("'Death', 'Censored'", str(raised.exception))
        for codes, field in ((("Died", "Censored"), "Event"), (("Death", "Death"), cox.CENSOR_VALUE),
                             (("", "Censored"), cox.EVENT_VALUE), (("Alive", "Censored"), "Event")):
            with self.subTest(codes=codes), self.assertRaises(FieldError) as raised:
                analyse("Cox regression", fixture(),
                        options(**{cox.EVENT_VALUE: codes[0], cox.CENSOR_VALUE: codes[1]}))
            self.assertEqual(raised.exception.field, field)

    def test_event_value_absent_from_the_column(self):
        frame = fixture().assign(Event="Censored")
        frame.loc[0, "Event"] = "Death"
        frame.loc[0, "Event"] = "Censored"
        with self.assertRaises(FieldError) as raised:
            analyse("Cox regression", frame, options())
        self.assertEqual(raised.exception.field, cox.EVENT_VALUE)

    def test_text_digits_match_as_written(self):
        frame = fixture().assign(Event=lambda f: np.where(f.Event == "Death", "1", "0").astype(object))
        result = analyse("Cox regression", frame, options(**{cox.EVENT_VALUE: "1", cox.CENSOR_VALUE: "0"}))
        self.assertAlmostEqual(result.tables["Coefficients"].loc["Arm [B]", "Estimate"], BETA["Efron"], 7)

    def test_existing_fit_criteria_are_kept(self):
        frame = fixture()
        frame.loc[0, "Time"] = -1
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            analyse("Cox regression", frame, options())
        single = fixture().assign(Event="Censored")
        single.loc[0, "Event"] = "Death"
        with self.assertRaisesRegex(ValueError, "two events"):
            analyse("Cox regression", single, options())
        twin = fixture().assign(Copy=lambda f: f.Arm)
        with self.assertRaisesRegex(ValueError, "rank deficient"):
            analyse("Cox regression", twin, options(Predictors=["Arm", "Copy"],
                                                     **{"Categorical predictors": ["Arm", "Copy"]}))


class ProfileTests(unittest.TestCase):
    def frame(self):
        frame = fixture()
        frame["Age"] = [61, 54, 70, 49, 66, 58, 63, 51, 72, 45, 68, 57]
        frame["Site"] = ["N", "S", "S", "N", "N", "S", "N", "S", "N", "S", "S", "N"]
        return frame

    def multi(self, frame, profiles_, **extra):
        o = options(Predictors=["Arm", "Age", "Site"], **{"Categorical predictors": ["Arm", "Site"],
                                                           cox.PREDICT: True, cox.PROFILES: profiles_, **extra})
        return analyse("Cox regression", frame, o)

    def test_several_predictors_and_a_continuous_role(self):
        frame = self.frame()
        result = self.multi(frame, [{"Label": "Old B in S", "Values": {"Arm": "B", "Age": "70,5", "Site": "S"}},
                                    {"Label": "Reference", "Values": {"Arm": "A", "Age": 0, "Site": "N"}}])
        beta = result.tables["Coefficients"]["Estimate"]
        self.assertEqual(list(beta.index), ["Arm [B]", "Age", "Site [S]"])
        hazard = result.tables["Baseline survival"]["Baseline cumulative hazard"].to_numpy()
        predicted = result.tables["Predicted survival"]
        eta = beta["Arm [B]"] + 70.5 * beta["Age"] + beta["Site [S]"]
        np.testing.assert_allclose(predicted.query("Profile == 'Old B in S'")["Survival"],
                                   np.exp(-hazard * np.exp(eta)), rtol=1e-10)
        np.testing.assert_allclose(predicted.query("Profile == 'Reference'")["Survival"], np.exp(-hazard), rtol=1e-10)

    def test_shifting_a_continuous_predictor_keeps_the_curves(self):
        frame = self.frame()
        values = {"Arm": "B", "Age": 60, "Site": "N"}
        plain = self.multi(frame, [{"Label": "P", "Values": values}])
        shifted = self.multi(frame.assign(Age=frame.Age + 1e4), [{"Label": "P", "Values": {**values, "Age": 1e4 + 60}}])
        np.testing.assert_allclose(plain.tables["Predicted survival"]["Survival"],
                                   shifted.tables["Predicted survival"]["Survival"], rtol=1e-6)

    def test_changing_only_the_profiles_keeps_the_fit(self):
        first, second = full(**{cox.PROFILES: profiles("A")}), full(**{cox.PROFILES: profiles("B", "A")})
        for sheet in (*SHEETS, "Baseline survival", "Cox residuals", "Schoenfeld residuals"):
            pd.testing.assert_frame_equal(first.tables[sheet], second.tables[sheet])
        self.assertEqual(second.tables["Predicted survival"]["Profile"].unique().tolist(), ["B", "A"])

    def test_profile_errors_are_explicit(self):
        frame = self.frame()
        good = {"Arm": "A", "Age": 50, "Site": "N"}
        cases = (([{"Label": "X", "Values": {**good, "Arm": "C"}}], "not a category of Arm. Categories: A, B"),
                 ([{"Label": "X", "Values": {"Arm": "A", "Age": 50}}], "needs a value for Site"),
                 ([{"Label": "X", "Values": {**good, "Age": "old"}}], "Age needs a finite number"),
                 ([{"Label": "X", "Values": {**good, "Age": float("inf")}}], "Age needs a finite number"),
                 ([{"Label": "X", "Values": {**good, "Dose": 1}}], "not a predictor"),
                 ([{"Label": "X", "Values": good}, {"Label": "X", "Values": good}], "unique"),
                 ([{"Label": " ", "Values": good}], "needs a label"),
                 ([], "Add 1 to 12"),
                 ([{"Label": str(i), "Values": good} for i in range(13)], "Add 1 to 12"))
        for value, message in cases:
            with self.subTest(message=message), self.assertRaises(FieldError) as raised:
                self.multi(frame, value)
            self.assertEqual(raised.exception.field, cox.PROFILES)
            self.assertIn(message, str(raised.exception))

    def test_unrepresentable_profile(self):
        frame = self.frame()
        with self.assertRaisesRegex(FieldError, "not representable"):
            self.multi(frame, [{"Label": "Huge", "Values": {"Arm": "A", "Age": 1e300, "Site": "N"}}])


class RowIdentityTests(unittest.TestCase):
    def test_excluded_row_keeps_source_positions(self):
        frame = fixture()
        frame.loc[6, "Time"] = np.nan
        result = full("Breslow", frame)
        self.assertEqual(result.tables["Cox residuals"]["Source row"].tolist(), [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12])
        self.assertEqual(result.tables["Model"].loc["Incomplete rows", "Value"], 1)

    def test_editing_a_status_recalculates_baseline_and_residuals(self):
        frame = fixture()
        frame.loc[0, "Event"] = "Censored"
        frame.loc[11, "Time"] = 10
        before, after = full("Breslow"), full("Breslow", frame)
        self.assertEqual(after.tables["Baseline survival"]["Time"].tolist(), [2, 4, 6, 7, 8])
        self.assertEqual(after.tables["Cox residuals"]["Event"].iat[0], 0)
        self.assertEqual(after.tables["Cox residuals"]["Time"].iat[-1], 10)
        self.assertFalse(np.allclose(before.tables["Cox residuals"]["Martingale residual"],
                                     after.tables["Cox residuals"]["Martingale residual"]))

    def test_censoring_before_the_first_event(self):
        frame = pd.concat([pd.DataFrame({"Time": [.5], "Event": ["Censored"], "Arm": ["B"]}), fixture()],
                          ignore_index=True)
        rows = full("Efron", frame).tables["Cox residuals"]
        first = rows.iloc[0]
        self.assertEqual((first["Source row"], first["Expected events"], first["Martingale residual"],
                          first["Deviance residual"]), (1, 0, 0, 0))

    def test_non_default_index(self):
        frame = fixture().set_index(pd.Index(list("abcdefghijkl")))
        rows = full("Efron", frame).tables["Cox residuals"]
        self.assertEqual(rows["Source row"].tolist(), list(range(1, 13)))


class SchoenfeldTests(unittest.TestCase):
    def test_without_censoring_matches_statsmodels(self):
        rng = np.random.default_rng(3)
        frame = pd.DataFrame({"T": rng.permutation(np.arange(1, 16)).astype(float), "E": 1,
                              "X": rng.normal(size=15), "G": rng.choice(list("PQR"), 15)})
        design = pd.get_dummies(frame[["X", "G"]], drop_first=True, dtype=float)
        for ties in ("Breslow", "Efron"):
            o = {"Time": "T", "Event": "E", "Predictors": ["X", "G"], "Categorical predictors": ["G"], "Ties": ties,
                 cox.SCHOENFELD: True}
            sheet = analyse("Cox regression", frame, o).tables["Schoenfeld residuals"]
            library = PHReg(frame["T"], design, status=frame["E"], ties=ties.lower()).fit()
            np.testing.assert_allclose(sheet[["X", "G [Q]", "G [R]"]], library.schoenfeld_residuals, atol=1e-12)
            self.assertEqual(sheet["Source row"].tolist(), list(range(1, 16)))
            np.testing.assert_allclose(sheet[["X", "G [Q]", "G [R]"]].sum(), 0, atol=1e-8)


class GraphAndLegacyTests(unittest.TestCase):
    def test_recipe_without_new_options_returns_the_original_sheets(self):
        frame = fixture().assign(Event=lambda f: (f.Event == "Death").astype(int))
        legacy = {"Time": "Time", "Event": "Event", "Predictors": ["Arm"], "Categorical predictors": ["Arm"],
                  "Ties": "Efron"}
        old = analyse("Cox regression", frame, legacy)
        self.assertEqual(list(old.tables), SHEETS)
        self.assertIsNone(old.figure)
        expected = models.cox_regression(frame, "Time", "Event", ["Arm"], ["Arm"], "efron")
        for name in SHEETS:
            pd.testing.assert_frame_equal(old.tables[name], expected[name])

    def test_new_options_off_return_the_same_sheets(self):
        result = analyse("Cox regression", fixture(), options(**{cox.GRAPH: cox.AUTOMATIC}))
        self.assertEqual(list(result.tables), SHEETS)
        self.assertIsNone(result.figure)

    def test_graph_display_picks_the_figure_not_the_tables(self):
        deviance = full("Breslow", **{cox.GRAPH: cox.DEVIANCE_GRAPH})
        curves = full("Breslow")
        self.assertEqual(list(deviance.tables), list(curves.tables))
        rows = deviance.tables["Cox residuals"]
        axes = deviance.figure.axes[0]
        np.testing.assert_allclose(axes.collections[0].get_offsets(),
                                   rows[["Linear predictor", "Deviance residual"]].to_numpy())
        schoenfeld = full("Breslow", **{cox.GRAPH: cox.SCHOENFELD_GRAPH, cox.GRAPH_TERM: "Arm [B]"})
        sheet = schoenfeld.tables["Schoenfeld residuals"]
        np.testing.assert_allclose(schoenfeld.figure.axes[0].collections[0].get_offsets(),
                                   sheet[["Time", "Arm [B]"]].to_numpy())
        only = analyse("Cox regression", fixture(), options(**{cox.DIAGNOSTICS: True}))
        self.assertEqual(only.figure.axes[0].get_ylabel(), "Deviance residual")

    def test_graph_display_needs_its_output(self):
        with self.assertRaises(FieldError) as raised:
            analyse("Cox regression", fixture(), options(**{cox.GRAPH: cox.DEVIANCE_GRAPH}))
        self.assertEqual(raised.exception.field, cox.GRAPH)
        with self.assertRaises(FieldError) as raised:
            full(**{cox.GRAPH: cox.SCHOENFELD_GRAPH, cox.GRAPH_TERM: "Arm"})
        self.assertEqual(raised.exception.field, cox.GRAPH_TERM)
        self.assertIn("Arm [B]", str(raised.exception))

    def test_visibility(self):
        self.assertEqual(cox.cox_visibility(False, cox.AUTOMATIC),
                         {cox.PROFILES: False, cox.GRAPH_TERM: False, cox.X_AXIS: False})
        self.assertEqual(cox.cox_visibility(True, cox.SCHOENFELD_GRAPH),
                         {cox.PROFILES: True, cox.GRAPH_TERM: True, cox.X_AXIS: False})


if __name__ == "__main__":
    unittest.main()
