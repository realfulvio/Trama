"""PCA component retention and parallel analysis."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi.field_error import FieldError
from analisi.i18n import translate
from analisi.pca_retention import (
    CHOICE_KEYS, CUMULATIVE_TARGET, EIGENVALUE, LABEL_KEYS, LOADINGS_SHEET, PARALLEL, PARALLEL_SHEET,
    PERCENTILE, REFERENCE_GID, RETAINED, SAVE, SCORES_SHEET, SEED, SELECTION, SELECTION_SHEET,
    SETTINGS_SHEET, SIMULATIONS,
)
from analisi.workbench import analyse

DATA = Path(__file__).parent / "data" / "pca_retention_070"
METHOD = "Principal component analysis"


def _recipe(name):
    recipes = json.loads((DATA / "recipes.json").read_text())
    return pd.DataFrame(json.loads((DATA / f"{name}.json").read_text())), recipes[name]


def _run(name, **changes):
    frame, options = _recipe(name)
    options = {**options, **changes}
    return analyse(METHOD, frame, options)


class RetentionTests(unittest.TestCase):
    def test_legacy_sheets_stay_complete_when_a_criterion_is_added(self):
        frame, options = _recipe("strong")
        historical = analyse(METHOD, frame, {"Variables": options["Variables"], "Standardize": True})
        selected = _run("strong")
        for name in ("Explained variance", "Eigenvectors", "Scores"):
            pd.testing.assert_frame_equal(selected.tables[name], historical.tables[name])
        self.assertEqual(list(selected.tables)[:3], list(historical.tables))
        self.assertNotIn(SELECTION_SHEET, historical.tables)

    def test_all_ignores_invalid_hidden_simulation_fields(self):
        frame, options = _recipe("strong")
        result = analyse(METHOD, frame, {
            "Variables": options["Variables"], "Standardize": True,
            SELECTION: "All", SEED: -1, SIMULATIONS: 0, PERCENTILE: 100.0,
            RETAINED: True, EIGENVALUE: float("nan"), CUMULATIVE_TARGET: 0.0, SAVE: "yes",
        })
        self.assertEqual(list(result.tables), ["Explained variance", "Eigenvectors", "Scores"])

    def test_orthogonal_fixture_keeps_only_the_passing_prefix(self):
        table = _run("prefix-orthogonal").tables[SELECTION_SHEET]
        retained = table["Retained"].tolist()
        passed = table["Rule pass"].tolist()
        self.assertNotEqual(retained, passed)
        first_fail = retained.index(False)
        self.assertTrue(all(retained[:first_fail]))
        self.assertFalse(any(retained[first_fail:]))
        self.assertTrue(any(passed[first_fail:]))

    def test_longer_study_keeps_the_first_replicates(self):
        short = _run("strong").tables[PARALLEL_SHEET]
        longer = _run("prefix-more").tables[PARALLEL_SHEET]
        np.testing.assert_allclose(longer.iloc[:len(short), 1:].to_numpy(), short.iloc[:, 1:].to_numpy())
        self.assertEqual(longer["Simulation"].tolist()[0], 1)

    def test_centered_scale_changes_eigenvalues_and_not_the_decision(self):
        centered = _run("centered").tables[SELECTION_SHEET]
        tiny = _run("tiny-units").tables[SELECTION_SHEET]
        np.testing.assert_allclose(tiny["Eigenvalue"], centered["Eigenvalue"] * 1e-16, rtol=1e-8, atol=0)
        np.testing.assert_allclose(tiny["Random percentile"], centered["Random percentile"] * 1e-16, rtol=1e-8, atol=0)
        self.assertEqual(tiny["Retained"].tolist(), centered["Retained"].tolist())
        np.testing.assert_allclose(tiny["Variance (%)"], centered["Variance (%)"], rtol=0, atol=1e-12)

    def test_source_rows_keep_the_original_index_after_missing_values(self):
        frame, _options = _recipe("missing")
        scores = _run("missing").tables[SCORES_SHEET]
        kept = frame[list(frame)].dropna().index.tolist()
        self.assertEqual(scores["Source row"].tolist(), kept)
        self.assertLess(len(scores), len(frame))

    def test_zero_components_keep_the_identifier_columns(self):
        result = _run("zero-selected")
        self.assertEqual(int(result.tables[SELECTION_SHEET]["Retained"].sum()), 0)
        self.assertEqual(list(result.tables[SCORES_SHEET].columns), ["Source row"])
        self.assertEqual(list(result.tables[LOADINGS_SHEET].columns), ["Variable"])
        self.assertFalse(result.tables[SCORES_SHEET].empty)
        self.assertNotIn(PARALLEL_SHEET, result.tables)
        self.assertTrue(pd.isna(result.tables[SETTINGS_SHEET].loc[0, "Simulations"]))

    def test_scree_adds_the_percentile_curve_without_renaming_the_observed_line(self):
        result = _run("strong")
        lines = result.figure.axes[0].get_lines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(str(lines[0].get_label()).startswith("_"))
        self.assertEqual(lines[1].get_gid(), REFERENCE_GID)
        self.assertIn("95", lines[1].get_label())
        self.assertIsNotNone(result.figure.axes[0].get_legend())
        hidden = _run("strong", **{SAVE: False})
        self.assertNotIn(PARALLEL_SHEET, hidden.tables)
        self.assertEqual(hidden.figure.axes[0].get_lines()[1].get_gid(), REFERENCE_GID)

    def test_other_views_keep_every_living_axis_and_no_null_curve(self):
        result = _run("strong", **{"Graph display": "Scores", "Horizontal PC": 1, "Vertical PC": 2})
        self.assertIn("PC2", result.figure.axes[0].get_ylabel())
        self.assertFalse(any(line.get_gid() == REFERENCE_GID for line in result.figure.axes[0].get_lines()))
        kaiser = _run("kaiser")
        self.assertEqual(len(kaiser.figure.axes[0].get_lines()), 1)
        self.assertTrue(pd.isna(kaiser.tables[SELECTION_SHEET]["Random mean"]).all())

    def test_fixed_count_beyond_the_rank_names_its_field(self):
        with self.assertRaises(FieldError) as caught:
            _run("strong", **{SELECTION: "Fixed number", RETAINED: 100})
        self.assertEqual(caught.exception.field, RETAINED)

    def test_invalid_numbers_name_the_active_field_and_bool_is_not_a_number(self):
        cases = (
            ({SEED: -1}, SEED),
            ({SIMULATIONS: 0}, SIMULATIONS),
            ({PERCENTILE: 100.0}, PERCENTILE),
            ({SELECTION: "Eigenvalue threshold", EIGENVALUE: float("nan")}, EIGENVALUE),
            ({SELECTION: "Cumulative variance", CUMULATIVE_TARGET: 0.0}, CUMULATIVE_TARGET),
            ({SELECTION: "Fixed number", RETAINED: True}, RETAINED),
            ({SIMULATIONS: True}, SIMULATIONS),
            ({SEED: False}, SEED),
            ({PERCENTILE: False}, PERCENTILE),
        )
        for changes, field in cases:
            with self.subTest(field=field, changes=changes):
                with self.assertRaises(FieldError) as caught:
                    _run("strong", **changes)
                self.assertEqual(caught.exception.field, field)

    def test_budget_and_width_fail_before_a_replicate_is_drawn(self):
        wide = pd.DataFrame(np.random.default_rng(0).normal(size=(4, 65)), columns=[f"V{i}" for i in range(65)])
        with patch("analisi.pca_retention._replicates", side_effect=AssertionError("allocated")):
            with self.assertRaises(FieldError) as width:
                analyse(METHOD, wide, {
                    "Variables": list(wide.columns), "Standardize": True, SELECTION: PARALLEL,
                    SIMULATIONS: 10, SEED: 1, PERCENTILE: 95.0, SAVE: False,
                })
            self.assertEqual(width.exception.field, "Variables")
            frame = pd.DataFrame(np.arange(400 * 40, dtype=float).reshape(400, 40),
                                 columns=[f"V{i}" for i in range(40)])
            with self.assertRaises(FieldError) as budget:
                analyse(METHOD, frame, {
                    "Variables": list(frame.columns), "Standardize": False, SELECTION: PARALLEL,
                    SIMULATIONS: 200, SEED: 1, PERCENTILE: 95.0, SAVE: False,
                })
            self.assertEqual(budget.exception.field, SIMULATIONS)

    def test_rank_two_at_one_hundred_percent_does_not_keep_the_empty_component(self):
        result = _run("rank-two")
        table = result.tables[SELECTION_SHEET]
        settings = result.tables[SETTINGS_SHEET].iloc[0]
        self.assertEqual(int(settings["Rank"]), 2)
        self.assertEqual(int(settings["Count"]), 2)
        self.assertEqual(table["Retained"].tolist(), [True, True, False])
        self.assertEqual(len(result.tables["PC graph coordinates"]), 3)

    def test_selection_labels_translate_and_the_recipe_values_stay_canonical(self):
        english = {
            "pca.select.selection": "Selection",
            "pca.select.retained": "Retained components",
            "pca.select.threshold": "Eigenvalue threshold",
            "pca.select.cumulative": "Cumulative variance (%)",
            "pca.select.simulations": "Parallel simulations",
            "pca.select.seed": "Parallel seed",
            "pca.select.percentile": "Parallel percentile (%)",
            "pca.select.save": "Save parallel simulations",
            "pca.select.choice.all": "All",
            "pca.select.choice.fixed": "Fixed number",
            "pca.select.choice.threshold": "Eigenvalue threshold",
            "pca.select.choice.cumulative": "Cumulative variance",
            "pca.select.choice.parallel": "Parallel analysis",
        }
        italian = {
            "pca.select.selection": "Selezione",
            "pca.select.retained": "Componenti trattenute",
            "pca.select.threshold": "Soglia degli autovalori",
            "pca.select.cumulative": "Varianza cumulata (%)",
            "pca.select.simulations": "Simulazioni parallele",
            "pca.select.seed": "Seme parallelo",
            "pca.select.percentile": "Percentile parallelo (%)",
            "pca.select.save": "Salva le simulazioni parallele",
            "pca.select.choice.all": "Tutte",
            "pca.select.choice.fixed": "Numero fisso",
            "pca.select.choice.threshold": "Soglia degli autovalori",
            "pca.select.choice.cumulative": "Varianza cumulata",
            "pca.select.choice.parallel": "Analisi parallela",
        }
        self.assertEqual(set(LABEL_KEYS.values()) | set(CHOICE_KEYS.values()), set(english))
        for key, text in english.items():
            self.assertEqual(translate("en", key), text)
            self.assertEqual(translate("it", key), italian[key])
        self.assertEqual(set(CHOICE_KEYS), {"All", "Fixed number", "Eigenvalue threshold",
                                            "Cumulative variance", "Parallel analysis"})


if __name__ == "__main__":
    unittest.main()
