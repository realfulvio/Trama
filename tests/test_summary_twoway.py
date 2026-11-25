"""Two-way ANOVA from cell summaries, checked against the fixed oracle."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
import time

import numpy as np
import pandas as pd

from analisi.data import load_project, save_project
from analisi.field_error import FieldError
from analisi.grouped_anova import METHOD as GROUPED
from analisi.i18n import set_language, ui
from analisi.stats import factorial_anova
from analisi.summary_anova import METHOD as ONE_WAY, summary_anova
from analisi.table_templates import GROUPED_FORMATS, table_frame
from analisi.summary_twoway import (
    ANOVA_SHEET, BALANCED_N, COLUMN_FACTOR, COLUMN_NAME, DISPERSION, DISPERSION_TYPE, EQUAL_WEIGHT,
    ERRORS, INPUT, MEAN, METHOD, RESIDUAL, ROW_FACTOR, ROW_LABELS, ROW_NAME, ROWS, SAMPLE_SIZE, SD, SEM,
    SETTINGS_SHEET, SOURCE_ROW, SUBCOLUMNS, SUMMARY_SHEET, TOTAL, UNEQUAL_N, VARIABLES, summary_twoway,
)
from analisi.summary_twoway_catalog import MESSAGES
from analisi.workbench import GROUPS, analyse

ROOT = Path(__file__).resolve().parents[1] / "tests" / "data" / "summary-twoway"
ORACLE = json.loads((ROOT / "oracolo.json").read_text(encoding="utf-8"))
TERMS = {"A": "A", "B": "B", "AxB": "A:B", "Residual": RESIDUAL, "Total": TOTAL}


def long_frame(name="bilanciato"):
    frame = pd.read_csv(ROOT / f"{name}.csv", dtype={"A": str, "B": str})
    return frame


def long_options(**extra):
    options = {INPUT: ROWS, ROW_FACTOR: "A", COLUMN_FACTOR: "B", MEAN: "Mean", DISPERSION: "SD",
               SAMPLE_SIZE: "N", DISPERSION_TYPE: SD, ROW_NAME: "A", COLUMN_NAME: "B"}
    options.update(extra)
    return options


def subcolumn_frame(name="Bilanciato"):
    tables = load_project(ROOT / "anova-riassunti.alab")
    return tables[name].frame()


def subcolumn_options(**extra):
    frame = subcolumn_frame()
    options = {INPUT: SUBCOLUMNS, ROW_LABELS: "Row title", VARIABLES: list(frame.columns[1:]),
               DISPERSION_TYPE: SD, ROW_NAME: "A", COLUMN_NAME: "B"}
    options.update(extra)
    return options


class OracleTests(TestCase):
    def assert_oracle(self, table, name):
        for key, values in ORACLE[name].items():
            row = table.loc[TERMS[key]]
            for field, expected in values.items():
                self.assertTrue(np.isclose(row[field], expected, rtol=1e-8, atol=1e-10),
                                (name, key, field, row[field], expected))

    def test_balanced_and_unbalanced_match_the_oracle_from_summaries(self):
        for name in ("bilanciato", "sbilanciato"):
            with self.subTest(name=name):
                result = summary_twoway(long_frame(name), long_options())
                self.assert_oracle(result.tables[ANOVA_SHEET], name)
                self.assertIsNone(result.figure)

    def test_subcolumns_match_the_same_oracle_and_keep_literal_names(self):
        balanced = summary_twoway(subcolumn_frame(), subcolumn_options())
        self.assert_oracle(balanced.tables[ANOVA_SHEET], "bilanciato")
        unbalanced = summary_twoway(subcolumn_frame("Sbilanciato"), subcolumn_options())
        self.assert_oracle(unbalanced.tables[ANOVA_SHEET], "sbilanciato")
        labels = unbalanced.tables[SUMMARY_SHEET]["A"].tolist()
        self.assertIn("Dose $", labels)
        self.assertEqual(labels, ["A0", "A0", "A1", "A1", "Dose $", "Dose $"])

    def test_sem_and_reordered_groups_keep_the_sums_of_squares(self):
        for name in ("bilanciato", "sbilanciato"):
            frame = long_frame(name)
            sem = frame.copy()
            sem["SEM"] = frame["SD"] / np.sqrt(frame["N"])
            options = long_options(**{DISPERSION: "SEM", DISPERSION_TYPE: SEM})
            direct = summary_twoway(sem, options).tables[ANOVA_SHEET]
            shuffled = summary_twoway(frame.sample(frac=1, random_state=3), long_options()).tables[ANOVA_SHEET]
            self.assert_oracle(direct, name)
            self.assert_oracle(shuffled, name)

    def test_blank_grouped_rows_keep_the_original_source_row_numbers(self):
        frame = table_frame(GROUPED_FORMATS["Mean, SD and N"], sample=False)
        frame.iloc[0] = ["A0", 2, 1, 3, 6, 1, 3]
        frame.iloc[2] = ["A1", 4, 1, 3, 12, 1, 3]
        options = {INPUT: SUBCOLUMNS, ROW_LABELS: "Row title", ROW_NAME: "A", COLUMN_NAME: "B"}
        result = summary_twoway(frame, options)
        self.assert_oracle(result.tables[ANOVA_SHEET], "bilanciato")
        self.assertEqual(result.tables[SUMMARY_SHEET][SOURCE_ROW].tolist(), [1, 1, 3, 3])
        frame.iat[1, 0] = "A2"
        with self.assertRaises(FieldError) as error:
            summary_twoway(frame, options)
        self.assertEqual(error.exception.field, VARIABLES)

    def test_changing_one_mean_matches_the_recalculated_fixture(self):
        frame = long_frame()
        frame.loc[(frame["A"] == "A1") & (frame["B"] == "B1"), "Mean"] = 14
        table = summary_twoway(frame, long_options()).tables[ANOVA_SHEET]
        self.assertTrue(np.isclose(table.loc["A", "F"], 75))
        self.assertTrue(np.isclose(table.loc["B", "F"], 147))
        self.assertTrue(np.isclose(table.loc["A:B", "F"], 27))
        self.assertTrue(np.isclose(table.loc[RESIDUAL, "SS"], 8))

    def test_type_iii_adds_to_the_corrected_total_only_when_the_grid_is_balanced(self):
        balanced = summary_twoway(long_frame(), long_options()).tables[ANOVA_SHEET]
        effects = balanced.loc[["A", "B", "A:B"], "SS"].sum()
        self.assertTrue(np.isclose(effects + balanced.loc[RESIDUAL, "SS"], balanced.loc[TOTAL, "SS"]))
        unbalanced = summary_twoway(long_frame("sbilanciato"), long_options()).tables
        table = unbalanced[ANOVA_SHEET]
        effects = table.loc[["A", "B", "A:B"], "SS"].sum()
        self.assertFalse(np.isclose(effects + table.loc[RESIDUAL, "SS"], table.loc[TOTAL, "SS"]))
        self.assertIn(UNEQUAL_N, unbalanced[SETTINGS_SHEET]["Value"].tolist())
        self.assertIn(EQUAL_WEIGHT, unbalanced[SETTINGS_SHEET]["Value"].tolist())
        self.assertIn(BALANCED_N, summary_twoway(long_frame(), long_options()).tables[SETTINGS_SHEET]["Value"].tolist())

    def test_the_engine_never_expands_sample_size_into_replicates(self):
        result = summary_twoway(long_frame(), long_options())
        used = result.tables[SUMMARY_SHEET]
        self.assertEqual(len(used), 4)
        self.assertEqual(used["N"].tolist(), [3, 3, 3, 3])
        self.assertEqual(int(used["N"].sum()), 12)
        with patch("analisi.grouped_anova.grouped_inputs", side_effect=AssertionError("expanded")):
            analyse(METHOD, long_frame(), long_options())

    def test_a_large_grid_stays_on_the_cell_count(self):
        levels = [f"L{i}" for i in range(10)]
        rows = [{"A": a, "B": b, "Mean": 1.0, "SD": 1.0, "N": 10**9} for a in levels for b in levels]
        started = time.perf_counter()
        result = summary_twoway(pd.DataFrame(rows), long_options())
        elapsed = time.perf_counter() - started
        used = result.tables[SUMMARY_SHEET]
        self.assertEqual(len(used), 100)
        self.assertEqual(int(used["N"].max()), 10**9)
        self.assertLess(elapsed, 1.0)
        self.assertEqual(int(result.tables[ANOVA_SHEET].loc[RESIDUAL, "df"]), 100 * (10**9 - 1))


class ValidationTests(TestCase):
    def test_malformed_summaries_name_the_field_and_leave_the_table_unchanged(self):
        frame = long_frame("sbilanciato")
        original = frame.copy()
        cases = {
            "N assente": frame.assign(N=np.nan),
            "N = 2,5": frame.assign(N=2.5),
            "N = 1": frame.assign(N=1),
            "SD negativa": frame.assign(SD=-1),
            "SEM infinito": frame.assign(SEM=np.inf),
            "cella duplicata": pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
            "combinazione mancante": frame.iloc[:-1].copy(),
            "tutte SD nulle": frame.assign(SD=0),
        }
        fields = {
            "N assente": SAMPLE_SIZE,
            "N = 2,5": SAMPLE_SIZE,
            "N = 1": SAMPLE_SIZE,
            "SD negativa": DISPERSION,
            "SEM infinito": DISPERSION,
            "cella duplicata": ROW_FACTOR,
            "combinazione mancante": ROW_FACTOR,
            "tutte SD nulle": DISPERSION,
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                options = long_options(**({DISPERSION: "SEM", DISPERSION_TYPE: SEM} if name == "SEM infinito" else {}))
                with self.assertRaises(FieldError) as error:
                    summary_twoway(data, options)
                self.assertEqual(error.exception.field, fields[name])
                pd.testing.assert_frame_equal(frame, original)

    def test_an_excluded_subcolumn_cell_is_a_field_error(self):
        tables = load_project(ROOT / "anova-riassunti.alab")
        dataset = tables["Bilanciato"]
        column = list(dataset.raw.columns).index("B1 [Mean]")
        dataset.excluded.add((1, column))
        with self.assertRaises(FieldError) as error:
            summary_twoway(dataset.frame(mask_excluded=True), subcolumn_options())
        self.assertEqual(error.exception.field, VARIABLES)
        self.assertIn("A1", str(error.exception))
        self.assertIn("Mean", str(error.exception))
        self.assertEqual(dataset.analyses, [])

    def test_repeated_measures_diagnostics_and_other_observation_options_are_refused(self):
        frame = long_frame()
        refused = [
            ("Subject", {**long_options(), "Subject": "Person"}),
            ("Repeated measures", {**long_options(), "Repeated measures": True}),
            ("ANOVA residual diagnostics", {**long_options(), "ANOVA residual diagnostics": True}),
            ("Sums of squares", {**long_options(), "Sums of squares": "Type I"}),
            ("Include interaction", {**long_options(), "Include interaction": False}),
            ("Post-hoc", {**long_options(), "Post-hoc": "Tukey"}),
        ]
        for field, options in refused:
            with self.subTest(field=field):
                with self.assertRaises(FieldError) as error:
                    summary_twoway(frame, options)
                self.assertEqual(error.exception.field, field)

    def test_messages_have_italian_text_and_the_command_is_beside_grouped_anova(self):
        english = {text for text, _ in MESSAGES.values()}
        self.assertTrue(set(ERRORS.values()) <= english)
        menu = GROUPS["Group Comparison"]
        self.assertEqual(menu[menu.index(GROUPED) + 1], METHOD)
        try:
            set_language("it")
            self.assertEqual(ui(METHOD), "ANOVA a due fattori da riepiloghi")
            with self.assertRaises(FieldError) as error:
                summary_twoway(long_frame().assign(SD=-1), long_options())
            from analisi.summary_twoway import format_error
            self.assertIn("non può essere negativa", format_error(error.exception))
        finally:
            set_language("en")


class ProjectTests(TestCase):
    def test_save_reopen_edit_undo_and_a_locked_sheet(self):
        from trama_qt.project import Project

        tables = load_project(ROOT / "anova-riassunti.alab")
        dataset = tables["Bilanciato"]
        options = subcolumn_options()
        dataset.analyses.append((METHOD, options))
        with TemporaryDirectory() as temp:
            path = Path(temp) / "anova-riassunti.alab"
            save_project(path, {"Bilanciato": dataset})
            loaded = load_project(path)["Bilanciato"]
            self.assertEqual(loaded.analyses, [(METHOD, options)])
            opened = analyse(METHOD, loaded.frame(), options)
            self.assertTrue(np.isclose(opened.tables[ANOVA_SHEET].loc["A", "F"], 48))
            exported = opened.tables[ANOVA_SHEET].to_csv()
            self.assertIn("48", exported)

            project = Project()
            project.tables["Bilanciato"] = loaded
            project.runs = Project.runs_for("Bilanciato", loaded)
            column = list(loaded.raw.columns).index("B1 [Mean]")
            project.edit_cell("Bilanciato", 1, column, "14")
            edited = analyse(METHOD, project.tables["Bilanciato"].frame(), options)
            self.assertTrue(np.isclose(edited.tables[ANOVA_SHEET].loc["A", "F"], 75))
            fresh = analyse(METHOD, project.tables["Bilanciato"].frame(), project.runs[0].options)
            pd.testing.assert_frame_equal(edited.tables[ANOVA_SHEET], fresh.tables[ANOVA_SHEET])
            project.undo()
            restored = analyse(METHOD, project.tables["Bilanciato"].frame(), options)
            self.assertTrue(np.isclose(restored.tables[ANOVA_SHEET].loc["A", "F"], 48))
            project.undo(redo=True)
            redone = analyse(METHOD, project.tables["Bilanciato"].frame(), options)
            self.assertTrue(np.isclose(redone.tables[ANOVA_SHEET].loc["B", "F"], 147))

            project.undo()
            project.set_sheet_frozen(("data", "Bilanciato"), True)
            before = project.tables["Bilanciato"].raw.copy()
            with self.assertRaises(ValueError):
                project.edit_cell("Bilanciato", 1, column, "14")
            pd.testing.assert_frame_equal(project.tables["Bilanciato"].raw, before)
            locked = analyse(METHOD, project.tables["Bilanciato"].frame(), options)
            self.assertTrue(np.isclose(locked.tables[ANOVA_SHEET].loc[RESIDUAL, "SS"], 8))

    def test_existing_grouped_and_one_way_summary_results_stay_put(self):
        worksheet = pd.DataFrame({
            "Labels": ["Warm", "Cold"],
            "Pump [1]": [8., 4.], "Pump [2]": [10., 6.],
            "Other [1]": [4., 3.], "Other [2]": [6., 4.],
        })
        options = {"Row labels": "Labels", "Y columns": list(worksheet)[1:],
                   "Row factor name": "Temperature", "Column factor name": "Treatment",
                   "Include interaction": True}
        actual = analyse(GROUPED, worksheet, options).tables[ANOVA_SHEET]
        expected = factorial_anova(pd.DataFrame({
            "Duration": [8., 10., 4., 6., 4., 6., 3., 4.],
            "Temperature": ["Warm", "Warm", "Cold", "Cold"] * 2,
            "Treatment": ["Pump"] * 4 + ["Other"] * 4,
        }), "Duration", ["Temperature", "Treatment"], 2)
        pd.testing.assert_frame_equal(actual, expected)
        summary = pd.DataFrame({"Group": ["A", "B", "C"], "Mean": [2., 4., 6.], "SD": [1., 1., 1.], "N": [3, 3, 3]})
        one_way = summary_anova(summary, {"Input": "Groups in rows", "Group": "Group", "Mean": "Mean",
                                          "Dispersion": "SD", "Sample size": "N", "Dispersion type": "SD",
                                          "Post-hoc": "None"})
        self.assertTrue(np.isclose(one_way.tables["ANOVA"].iloc[0]["F"], 12))
        self.assertEqual(ONE_WAY, "One-way ANOVA from summaries")
