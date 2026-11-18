"""Scree, loadings and the symmetric PCA biplot."""
import unittest

import numpy as np
import pandas as pd

from analisi.exploration import pca
from analisi.pca_graphs import (BIPLOT, GRAPH, HORIZONTAL, LABEL, LOADINGS, PROPORTION, SCORES, SCREE,
                                SHOW_LABELS, VERTICAL, pca_result)
from analisi.processing import FieldError
from analisi.workbench import analyse


def fixture():
    """Six symmetric complete rows and one incomplete row. Sample eigenvalues are 1.6 and 0.4."""
    return pd.DataFrame({
        "A": [1.4142135623730951, -1.4142135623730951, 0.7071067811865476, -0.7071067811865476, 0.0, 0.0, np.nan],
        "B": [1.4142135623730951, -1.4142135623730951, -0.7071067811865476, 0.7071067811865476, 0.0, 0.0, 9.0],
        "Label": ["città A", "città B", "gruppo $C", "gruppo <D>", "centro", "centro", "incompleta"],
    })


def _view(frame, view, **extra):
    options = {"Variables": ["A", "B"], "Standardize": False, GRAPH: view, HORIZONTAL: 1, VERTICAL: 2,
               LABEL: "Label", SHOW_LABELS: True, **extra}
    return pca_result(frame, options)


def _centered(frame, variables, standardize):
    values = frame.dropna(subset=variables)[variables].to_numpy(dtype=float)
    centered = values - values.mean(axis=0)
    if standardize:
        centered = centered / centered.std(axis=0, ddof=1)
    return centered


class PcaGraphTests(unittest.TestCase):
    def test_historical_sheets_match_pca_for_every_view(self):
        frame = fixture()
        parts, eigenvectors, scores = pca(frame, ["A", "B"], False)
        for view in (SCORES, LOADINGS, BIPLOT, SCREE, PROPORTION):
            result = _view(frame, view)
            pd.testing.assert_frame_equal(result.tables["Explained variance"], parts)
            pd.testing.assert_frame_equal(result.tables["Eigenvectors"], eigenvectors)
            pd.testing.assert_frame_equal(result.tables["Scores"], scores)
            self.assertIsNotNone(result.figure)
        np.testing.assert_allclose(parts["Eigenvalue"], [1.6, 0.4])
        np.testing.assert_allclose(frame.dropna(subset=["A", "B"])[["A", "B"]].std(ddof=1), [1, 1])

    def test_biplot_reconstructs_the_centered_matrix_with_canonical_signs(self):
        frame = fixture()
        result = _view(frame, BIPLOT)
        table = result.tables["PC graph coordinates"]
        rows = table.loc[table.Kind == "Row", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        variables = table.loc[table.Kind == "Variable", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        np.testing.assert_allclose(rows @ variables.T, _centered(frame, ["A", "B"], False), atol=1e-12)
        vectors = result.tables["Eigenvectors"].to_numpy()
        # Equal-magnitude entries can choose different sign anchors across LAPACK builds.
        # The eigensystem, orthogonality and actual canonical anchor are the contract.
        np.testing.assert_allclose(np.abs(vectors), np.full((2, 2), np.sqrt(.5)), atol=1e-12)
        np.testing.assert_allclose(vectors.T @ vectors, np.eye(2), atol=1e-12)
        covariance = np.cov(_centered(frame, ["A", "B"], False), rowvar=False)
        np.testing.assert_allclose(covariance @ vectors, vectors * [1.6, .4], atol=1e-12)
        for column in vectors.T:
            self.assertGreater(column[np.argmax(np.abs(column))], 0)
        self.assertEqual(table.loc[table.Kind == "Row", "Label"].tolist(),
                         ["città A", "città B", "gruppo $C", "gruppo <D>", "centro", "centro"])
        self.assertEqual(table.loc[table.Kind == "Row", "Identity"].tolist(), [0, 1, 2, 3, 4, 5])
        self.assertIn("U·sqrt(D)", result.tables["Settings"].loc["Biplot", "Value"])
        self.assertIn("not correlations", result.tables["Settings"].loc["Loadings", "Value"])
        self.assertIn("gruppo", "".join(text.get_text() for text in result.figure.axes[0].texts))

    def test_swapped_axes_and_standardization_keep_the_reconstruction(self):
        frame = fixture()
        swapped = _view(frame, BIPLOT, **{HORIZONTAL: 2, VERTICAL: 1})
        table = swapped.tables["PC graph coordinates"]
        rows = table.loc[table.Kind == "Row", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        variables = table.loc[table.Kind == "Variable", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        np.testing.assert_allclose(rows @ variables.T, _centered(frame, ["A", "B"], False), atol=1e-12)
        scaled = pd.DataFrame({"A": [1, 2, 3, 4, 5, 6.0], "B": [2, 8, 3, 9, 4, 1.0]})
        result = pca_result(scaled, {"Variables": ["A", "B"], "Standardize": True, GRAPH: BIPLOT,
                                      HORIZONTAL: 1, VERTICAL: 2})
        table = result.tables["PC graph coordinates"]
        rows = table.loc[table.Kind == "Row", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        variables = table.loc[table.Kind == "Variable", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        np.testing.assert_allclose(rows @ variables.T, _centered(scaled, ["A", "B"], True))
        self.assertIn("correlations", result.tables["Settings"].loc["Loadings", "Value"])

    def test_scores_and_loadings_follow_the_selected_components(self):
        frame = fixture()
        scores = _view(frame, SCORES)
        self.assertEqual(list(scores.tables["PC graph coordinates"].columns),
                         ["Source row", "Label", "Horizontal", "Vertical"])
        np.testing.assert_allclose(scores.tables["PC graph coordinates"]["Horizontal"],
                                   scores.tables["Scores"]["PC1"])
        loadings = _view(frame, LOADINGS)
        expected = scores.tables["Eigenvectors"].to_numpy() * np.sqrt([1.6, 0.4])
        np.testing.assert_allclose(loadings.tables["PC graph coordinates"][["Horizontal", "Vertical"]], expected)
        self.assertEqual(loadings.figure.axes[0].get_xlabel(), "PC1 (80%)")
        self.assertEqual(loadings.figure.axes[0].get_ylabel(), "PC2 (20%)")

    def test_observation_colors_preserve_groups_and_the_fitted_coordinates(self):
        frame = fixture().assign(Cohort=[1, "1", "1", 1, None, None, "Dropped"])
        for view in (SCORES, BIPLOT):
            with self.subTest(view=view):
                ordinary = _view(frame, view)
                colored = _view(frame, view, **{"Color groups by": "Cohort"})
                for name in ("Explained variance", "Eigenvectors", "Scores"):
                    pd.testing.assert_frame_equal(ordinary.tables[name], colored.tables[name])
                table = colored.tables["PC graph coordinates"]
                pd.testing.assert_frame_equal(table.drop(columns="Color group"), ordinary.tables["PC graph coordinates"])
                self.assertEqual(table["Color group"].iloc[:6].tolist(), [1, "1", "1", 1, None, None])
                axes = colored.figure.axes[0]
                self.assertEqual([len(artist.get_offsets()) for artist in axes.collections], [2, 2, 2])
                self.assertEqual([artist._tramastat_legend_key for artist in axes.collections],
                                 ["group:int:1", "group:str:1", "gid:pca-missing-color-group"])
                self.assertEqual(axes.get_legend().get_title().get_text(), "Cohort")
        for view in (LOADINGS, SCREE, PROPORTION):
            skipped = _view(frame, view, **{"Color groups by": "Unknown"})
            self.assertNotIn("Color group", skipped.tables["PC graph coordinates"])
        with self.assertRaises(FieldError) as missing:
            _view(frame, SCORES, **{"Color groups by": "Unknown"})
        self.assertEqual(missing.exception.field, "Color groups by")

    def test_scree_and_proportion_keep_every_component(self):
        frame = fixture()
        scree = _view(frame, SCREE, **{HORIZONTAL: 99})
        table = scree.tables["PC graph coordinates"]
        np.testing.assert_allclose(table["Eigenvalue"], [1.6, 0.4])
        self.assertEqual(table["PC"].tolist(), [1, 2])
        proportion = _view(frame, PROPORTION)
        self.assertEqual([line.get_label() for line in proportion.figure.axes[0].get_lines()],
                         ["Variance (%)", "Cumulative (%)"])
        self.assertIsNotNone(proportion.figure.axes[0].get_legend())

    def test_equal_missing_and_empty_components_name_the_selector(self):
        frame = fixture()
        with self.assertRaises(FieldError) as equal:
            _view(frame, BIPLOT, **{HORIZONTAL: 1, VERTICAL: 1})
        self.assertEqual(equal.exception.field, VERTICAL)
        with self.assertRaises(FieldError) as missing:
            _view(frame, BIPLOT, **{HORIZONTAL: 99})
        self.assertEqual(missing.exception.field, HORIZONTAL)
        constant = pd.DataFrame({"A": [1, 1, 1, 1.0], "B": [1, 2, 3, 4.0]})
        with self.assertRaisesRegex(ValueError, "constant"):
            pca_result(constant, {"Variables": ["A", "B"], "Standardize": False, GRAPH: BIPLOT})
        rank = pd.DataFrame({"A": [1, 2, 3, 4.0], "B": [2, 4, 6, 8.0]})
        with self.assertRaises(FieldError) as dead:
            pca_result(rank, {"Variables": ["A", "B"], "Standardize": True, GRAPH: SCORES,
                              HORIZONTAL: 1, VERTICAL: 2})
        self.assertEqual(dead.exception.field, VERTICAL)
        scree = pca_result(rank, {"Variables": ["A", "B"], "Standardize": True, GRAPH: SCREE,
                                  HORIZONTAL: 1, VERTICAL: 2})
        self.assertEqual(len(scree.tables["PC graph coordinates"]), 2)

    def test_missing_rows_duplicate_indexes_and_a_foreign_label(self):
        frame = fixture()
        frame.index = [3, 3, 4, 8, 8, 9, 10]
        result = _view(frame, SCORES)
        self.assertEqual(result.tables["PC graph coordinates"]["Source row"].tolist(), [3, 3, 4, 8, 8, 9])
        with self.assertRaises(FieldError) as caught:
            _view(frame, SCORES, **{LABEL: "A"})
        self.assertEqual(caught.exception.field, LABEL)

    def test_more_than_sixty_labels_stay_in_the_sheet_and_leave_the_figure(self):
        rng = np.random.default_rng(4)
        frame = pd.DataFrame({"A": rng.normal(size=61), "B": rng.normal(size=61),
                              "Label": [f"riga {i}" for i in range(61)]})
        result = pca_result(frame, {"Variables": ["A", "B"], "Standardize": False, GRAPH: SCORES,
                                    SHOW_LABELS: True, LABEL: "Label"})
        self.assertEqual(result.tables["PC graph coordinates"]["Label"].tolist(), frame["Label"].tolist())
        self.assertEqual(len(result.figure.axes[0].texts), 0)
        self.assertIn("more than 60", result.tables["Settings"].loc["Row labels", "Value"])

    def test_repeated_eigenvalues_match_reconstruction_and_subspace(self):
        rng = np.random.default_rng(1)
        eye = np.eye(8) - np.ones((8, 8)) / 8
        basis = np.linalg.eigh(eye)[1][:, -3:]
        rotation = np.linalg.qr(rng.normal(size=(3, 3)))[0]
        singular = np.array([3.0, 3.0, 1.0])
        values = (basis * singular) @ rotation.T
        frame = pd.DataFrame(values, columns=["A", "B", "C"])
        result = pca_result(frame, {"Variables": ["A", "B", "C"], "Standardize": False, GRAPH: BIPLOT,
                                    HORIZONTAL: 1, VERTICAL: 2})
        eigenvalues = result.tables["Explained variance"]["Eigenvalue"].to_numpy()
        self.assertAlmostEqual(eigenvalues[0], eigenvalues[1], places=8)
        rows, variables = _full(result, frame)
        np.testing.assert_allclose(rows @ variables.T, _centered(frame, ["A", "B", "C"], False), atol=1e-8)
        fitted = result.tables["Eigenvectors"].to_numpy()[:, :2]
        expected = rotation[:, :2]
        np.testing.assert_allclose(fitted @ fitted.T, expected @ expected.T, atol=1e-8)


class PcaDispatchTests(unittest.TestCase):
    def test_recipe_without_graph_keys_keeps_the_historical_scatter(self):
        frame = fixture()
        result = analyse("Principal component analysis", frame, {"Variables": ["A", "B"], "Standardize": False})
        self.assertEqual(list(result.tables), ["Explained variance", "Eigenvectors", "Scores"])
        self.assertEqual((result.figure.axes[0].get_xlabel(), result.figure.axes[0].get_ylabel()), ("PC1", "PC2"))
        np.testing.assert_allclose(result.tables["Explained variance"]["Eigenvalue"], [1.6, 0.4])

    def test_analyse_reconstructs_the_biplot_and_rejects_equal_components(self):
        frame = fixture()
        result = analyse("Principal component analysis", frame, {
            "Variables": ["A", "B"], "Standardize": False, GRAPH: BIPLOT, HORIZONTAL: 1, VERTICAL: 2,
            LABEL: "Label", SHOW_LABELS: True})
        table = result.tables["PC graph coordinates"]
        rows = table.loc[table.Kind == "Row", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        variables = table.loc[table.Kind == "Variable", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        np.testing.assert_allclose(rows @ variables.T, _centered(frame, ["A", "B"], False), atol=1e-12)
        self.assertIsNotNone(result.figure)
        with self.assertRaises(FieldError) as caught:
            analyse("Principal component analysis", frame, {
                "Variables": ["A", "B"], "Standardize": False, GRAPH: BIPLOT, HORIZONTAL: 1, VERTICAL: 1})
        self.assertEqual(caught.exception.field, VERTICAL)

    def test_dialog_labels_keep_english_keys_and_translate(self):
        from analisi.i18n import translate

        english = {
            "analysis.pca.tab": "Graph",
            "analysis.pca.display": "Graph display",
            "analysis.pca.horizontal": "Horizontal PC",
            "analysis.pca.vertical": "Vertical PC",
            "analysis.pca.label": "Label column",
            "analysis.pca.show": "Show row labels",
        }
        italian = {
            "analysis.pca.tab": "Grafico",
            "analysis.pca.display": "Vista del grafico",
            "analysis.pca.horizontal": "Componente orizzontale",
            "analysis.pca.vertical": "Componente verticale",
            "analysis.pca.label": "Colonna etichette",
            "analysis.pca.show": "Mostra etichette di riga",
        }
        for key, text in english.items():
            self.assertEqual(translate("en", key), text)
            self.assertEqual(translate("it", key), italian[key])


def _full(result, frame):
    """Rebuild every symmetric coordinate from the historical sheets, including a dead component."""
    scores = result.tables["Scores"].to_numpy(dtype=float)
    eigenvectors = result.tables["Eigenvectors"].to_numpy(dtype=float)
    eigenvalues = result.tables["Explained variance"]["Eigenvalue"].to_numpy(dtype=float)
    singular = np.sqrt(np.clip(eigenvalues, 0, None) * (len(scores) - 1))
    root = np.sqrt(singular)
    dead = eigenvalues <= float(eigenvalues.max()) * 1e-10
    rows, variables = scores.copy(), eigenvectors.copy()
    for index, (empty, scale) in enumerate(zip(dead, root)):
        if empty or scale == 0:
            rows[:, index] = 0
            variables[:, index] = 0
        else:
            rows[:, index] /= scale
            variables[:, index] *= scale
    return rows, variables
